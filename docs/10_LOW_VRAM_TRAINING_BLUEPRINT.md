> **V3 优先级提示（2026-10-24）**：本文件是 v2 通用基础说明。**纯配置模式是固定判定线的真实 4K/5K/6K，不是风格倾向**；新增的条件训练、模式分流、异常演出能力限制与按模式评分请以 `docs/12..18` 为准。若本文与 V3 冲突，以 V3 为准。

# 10｜PhiAiMadeOs：8GB 显存适配的完整训练架构与优化规则

## 1. 核心决策：三模型**顺序训练**，而非单个 7B 或端到端全曲 Transformer

```
（一次性 CPU 离线流程）
音频 + 真实谱面
   ↓ 解码、格式校验、BPM/offset 精确积分、歌曲分组
时间校正 IR + 节拍网格 + 传统 DSP 特征 + (可选) 预训练嵌入缓存
   ↓ float16 缓存/小窗口索引
┌──────────────────────────────────────────┐
│ Stage 1: NoteRhythmNet（单独在 GPU 训练）│
│ 输入音频/节拍 → 事件是否出现、类型、时差、Hold 持续 │
└───────────────────────┬──────────────────┘
                        ↓ 冻结 / 训练后离线推理
┌──────────────────────────────────────────┐
│ Stage 2: LineMotionNet（单独训练）        │
│ 音频 + Note 时间序列 → 判定线数目/运动原型/运动参数 │
└───────────────────────┬──────────────────┘
                        ↓ 冻结 / 训练后离线推理
┌──────────────────────────────────────────┐
│ Stage 3: PlacementNet（单独训练）         │
│ Note + 判定线轨迹 → 线归属、X、上下侧及特殊参数 │
└───────────────────────┬──────────────────┘
                        ↓
             确定性约束修复 + 非 AI 审计 + 人工评分
                        ↓
                       RPE ZIP
```

**绝不同时将三个模型及其优化器放到 8GB GPU。** 阶段之间产生离线条件缓存/预测缓存。第二/三阶段可采用人工真实条件做 teacher forcing；随后用上一阶段**验证集输出**检查误差累积，防止训练时见到完美上游而推理时崩溃。

## 2. 特征编码：CPU 预计算，不在线跑重型声学编码器

- 统一采样率 `22050Hz` mono；音频解码 `ffmpeg` 流式加载；单曲处理，禁止整个 500 首同时驻内存。
- 生成：`log_mel(80 bins)`, `RMS`, `spectral_flux/onset`, `chroma(12)`, `beat candidates/downbeat candidates`；把每种特征的帧率、normalization 和 extractor 版本写入 metadata。
- 训练时采用 `25Hz` 或 `~43Hz` 特征帧率，窗口最大 `audio_frames≤384`；音符 timing 仍使用**高精度拍点/秒数映射**，不能只按 25Hz 量化而丢精度。
- `float16` 文件缓存，逐窗口读取 `mmap`；缺失/坏文件通过日志隔离，不能自动全量重算导致内存暴涨。
- 若将来使用 MERT/MuScriptor 类大模型：只允许**独立离线逐首 CPU/GPU 批次生成嵌入**，提取完就结束进程释放显存。不得和谱面 Transformer 联合占显存；模型与音频授权、实际 CPU/RAM 能否承担须先做试验。
- 对 500 首，总音频小时数和特征磁盘大小依歌曲长度而变化；缓存总量以 manifest 实测，不靠固定臆测。

## 3. 切片与事件空间

初版以**4 小节中心窗口**为训练样本，可加左右各 1 小节上下文。非 4/4、变 BPM 和非网格音符必须正常处理，不能认为固定 4/4 全曲通用。

候选节奏槽：每 4/4 小节 `48` 个基准子位置（可表示常见二分/四分/三连/六连/十二连等）；4 小节为 `192` 个候选槽。对弱起、复杂不规则拍号、超密谱另添加 onset proposal 和局部细分候选，限制每样本最多 `256` 槽；槽只是条件候选，模型输出额外连续 time residual（秒或 beat）。**禁止把所有 Note 无条件吸附到网格。**

首版硬性上限（超出拆窗而不是截断标签）：

| 张量/上限 | 初始值 | 备注 |
|---|---:|---|
| batch | 1 | 后续以 profile 决定是否提升 |
| 音频帧 T | 384 | 边界重叠、超过拆窗 |
| Note 候选槽 Q | 192，最大 256 | 测试非 4/4 和变速曲 |
| 同窗口运动事件 | 64 | 超限另切分，不删训练标签 |
| 同时活跃判定线 | 8 | 超限训练集标记复杂层级、升级模型前不可有损转换 |
| d_model | 192 | 紧张时回退 128 |
| attention heads | 4 | head_dim 48 |
| Note Transformer 层数 | 4 | FFN=4×192=768 |
| Line Transformer 层数 | 3 | FFN=768 |
| Placement Transformer 层数 | 3 | FFN=768 |

不承诺这些上限覆盖全部复杂谱面：**复杂输入可以不支持，但不允许静默丢事件。**

## 4. 模型 I/O 和训练目标（不是伪代码占位）

### Stage 1：NoteRhythmNet

输入：`audio_features [B,T,96~112]`（合并 mel/onset/RMS/chroma 等）、`time_features`（BPM、拍号、段落、目标难度等）；`query_slots [B,Q,K]`。先用小型 Conv1D/MLP 压缩音频特征，再用 2 层音频 self-attention + 4 层 cross-attention decoder 查询拍点。

输出：

- `presence` 是否存在事件：BCE/Focal Loss，处理大量空槽；
- `kind` 四类音符 Tap/Hold/Drag/Flick：masked CE，仅正样本计损失；
- `chord_count` 或多事件槽（上限明确）：CE；同一个时间可能多押；
- `time_residual` 连续时间偏移：Huber Loss，带单位和 clamp 范围；
- `hold_duration` 仅 Hold 使用：log-space Huber/离散 bins；
- `density/phrase` 可选辅助头：每小节负载，防止铺面平均密度塌缩。

使用 `BCE + λtype CE + λtime Huber + λhold Huber + λcount CE`，每项 loss 权重写配置，用**有效正样本数**归一，空窗口不能 NaN。评估 Note 时间 F1（多容差）、密度、类型混淆矩阵、比例偏差。

### Stage 2：LineMotionNet

不能直接学习「每帧随意 X/Y/角度」：先 CPU 从授权谱面运动轨迹提取长度对齐、可逆映射的局部 motif（position、rotation、alpha、speed 以及相互关系），例如 KMeans 得到**不大于 64 个**轨迹原型，保存 `prototype_dictionary` 的版本。**原型需附带 easing/event 边界，不允许只保留轨迹而丢失原始运动事件。**

模型以音频 + Stage1 Note events（训练时先用真实事件，然后阶段性混入 Stage1 预测）为条件，学习：

- `line_count`（1..8）和父子 DAG/引用（超上限则 fail/另行研究）；
- `motion_prototype` 多线同步/单线运动的分类；
- `event_boundary`、`duration`、`x/y/angle/alpha/speed/easing` 的残差参数；
- `continuation_state`：窗口交界处衔接，约束位置速度/方向连续或显式 hard-cut。

损失包含 prototype CE、事件边界时差、轨迹重建、父子合法性惩罚、跨窗连续性。线事件预测不确定时采用明确标注的**安全运动模板回退**，不能称为网络成功学习到复杂演出。

### Stage 3：PlacementNet

条件：Stage1 音符时间/类型 + Stage2 判定线轨迹 + 音频 + 目标难度。
输出：`line_id`、相对 `positionX`、`above`、`yOffset`、`note_speed`（以 IR 定义为准）。采用 Transformer 3 层 + 类别/连续回归头；对**真实判定时刻**计算经父线变换后的屏幕坐标，做可导或非导几何约束。不能只判断相对坐标差。

损失：线归属 CE、位置 Huber、上下侧 CE、与合法可玩区域/多押组合有关的软约束；禁用确定性的「距离过大就一律删除」规则。部分打击法需要真人评价，所以几何约束仅能做风险提示或安全阈值修复。

### 避免模型只输出空谱/静线

采样按歌曲分组、难度/密度均衡；正负槽加权或 focal loss；评估列出所有类别召回率与静线比例。如果模型只有 Tap 或只有一条不动的线，自动评估失败，不标记 usable。

## 5. 8GB 训练优化的**强制项**

| 优先级 | 必须执行 | 说明 |
|---|---|---|
| P0 | **单次只训练一个模型** | 优化器不共存，阶段之间卸载 GPU 进程 |
| P0 | micro_batch=1、gradient_accumulation=16 | 有效 batch=16（对实际窗口样本），不要为了“有效 batch”硬堆显存 |
| P0 | AMP `bf16` 若支持，否则 `fp16+GradScaler`，再退 `fp32` | loss 保持 fp32 稳定，检测 NaN/Inf |
| P0 | CPU cache + mmap，DataLoader workers=0 | 16GB RAM 不能常驻 500 曲音频 |
| P0 | 窗口序列上限 384/192/64 | 过长就拆窗，**不可丢真实标签** |
| P0 | checkpoint 存 CPU tensor / safetensors，原子重命名 | 可重启恢复，禁止 GPU tensors 常驻登记进程 |
| P1 | 优先用 PyTorch 原生 SDPA / scaled_dot_product_attention | 不依赖第三方 flash-attn 编译；兼容性需实测 |
| P1 | activation checkpointing 只用于确实 OOM 的注意力层 | 节省激活，牺牲算力；profiling 对比后开启 |
| P1 | AdamW 小模型基础优化器 | 如果优化器状态成为瓶颈，测试 `foreach=False`/8-bit optimizer 但不是强制依赖 |
| P1 | 分桶（时间窗长、线数、难度） | 降低 padding 和异常峰值 |
| P1 | 缓存第 2/3 阶段上游条件 | 不让三个模型的反向传播图联通 |
| P2 | `torch.compile`、高阶量化、LoRA/QLoRA | 仅在基线稳定后做 A/B 实测；不是小模型训练的默认救命方案 |

注意：`torch.cuda.empty_cache()` 不能减少张量实际占用；开启 optimizer offload/梯度 CPU 卸载会令 16GB 主存压力增大。不要默认采用 ZeRO / DeepSpeed / FSDP，多卡分布式方案对单卡 8GB 无意义甚至增加开销。

## 6. 硬内存门禁与自适应回退

启动前收集：`torch.cuda.mem_get_info()`、device_name、driver version、`torch.version.cuda`、`get_arch_list`、CPU total/available、SSD 空闲，生成诊断 JSON。

profile：最低执行 `100 optimizer steps` 的真实 forward/backward/AdamW/AMP/累积计算（不是只跑 inference）；记录 `max_memory_reserved()`、`max_memory_allocated()`、进程 RSS、step time，并以曲目最长窗口/线数接近上限复验。

**工程预算**：8GB 物理 GPU 上要求训练 peak reserved **≤6.2 GiB**，留余量供驱动/桌面/渲染；这只是健康门槛，实际 `free memory` 可能比 8GB 少，仍需运行前预检查。WSL Python RSS 目标 **≤5~6GiB**（Linux 9GB 限额）。若未达标按下列顺序回退：

```
关闭其他 GPU/内存应用
 → 改 micro_batch=1（默认已是 1）
 → 将最长窗口/上下文缩短（保证标签不丢）
 → activation checkpointing（比较速度）
 → d_model 192 → 128、layers 4 → 3【改变架构版本，须重新训练】
 → 更保守的 stage-specific 任务
 → CPU 小样本功能测试 / 明确报告硬件不够
```

OOM 处理：保存 crash report、样本 ID、形状、显存/RSS；结束/重启训练进程（CUDA OOM 后不要盲目继续不一致 step）；降低配置重新 profile。不允许误把 `torch.cuda.empty_cache()` 写为“彻底解决 OOM”。

## 7. 数据质量优先于模型规模

- 500 首歌曲必须 song-group split，建议 400/50/50；多难度、剪辑、翻奏须 group 去重。
- 训练每个窗口都必须有明确 chart seconds 与 audio seconds 映射，**BPM 是积分的分段函数、Offset 不允许凭猜测修正**。
- 训练适当抽样高难/低难/稀疏/密集、静线/复杂线；不允许使用仅高评分造成极端密度单一分布却不监控。
- 音量/EQ 微扰可在缓存特征级别做轻量增强；移速/时间伸缩会改变 label 时间，只有成对更新标签才能用。
- 断点后 resume 必须恢复 optimizer、scheduler、随机状态（PyTorch、NumPy、Python）和数据采样器状态；恢复成功进行 checksum/step 对照。
- 验证比较：规则基线 vs Note-only vs Note+Line vs Placement 全流程；测试集最后只跑一次冻结模型；真人评分独立于模型 loss。

## 8. 训练工序（以 500 曲为例）

1. **IR 解析 10~20 首**：真实 RPE/官方许可格式与 offset 验证，round-trip 后进数据库。
2. **全量建库**：CPU 单进程按曲串行解码并提取缓存；坏曲隔离；运行内存记录。
3. **Stage 1**：NoteRhythmNet，从 baseline 到真正收敛，以验证集做 early stop；产生 stage1 冻结 checkpoint。
4. **Stage 2**：CPU 聚类 motion motifs，训练 LineMotionNet；无运动标签的谱面可作为负例，但不能占满训练。
5. **Stage 3**：生成/缓存 stage1+2 的条件序列，再训练 PlacementNet。
6. **整曲推理**：全曲规划器 + 重叠窗口生成 + 事件去重 + 跨窗口 line continuity + 导出；仅一次一个模型使用 GPU，可先逐段分阶段运行。
7. **非 AI 审计**：绝不运行 torch 模型。对齐、波形、几何、格式、事件与风险；出具可定位警告。
8. **人工评分/退回**：WebAudio 同步播放器与 100 分打分、问题时间轴标记。反馈记录归档；不把人工评分直接复制为逐音符标签。

## 9. 必须统计的指标

- 技术可运行：GPU 显存峰值、GPU 空闲、CPU RSS 峰值、每步训练耗时、epoch 耗时、磁盘缓存占用、OOM、断点恢复成功率。
- Note：容差 F1、类型召回、Hold 端点误差、每小节密度偏差、非空谱率、多押命中。
- Line：原型分布、多线率、运动事件边界、线数误差、运动连续性、父子引用合法率；几何异常率。
- 整体：Phira 可解析率、模拟全曲渲染正确率、非 AI WARN/BLOCK 分布、人工评分、真人玩谱完成率。

真实模型完成定义：**非零授权数据训练并可复载，能处理保留测试歌曲以外的新音乐，完整谱面有 Note 和动态判定线，多问题可定位/退回/重生成，至少完成一首 Phira 本地真机试玩**。如无法达到，如实显示 `experimental` 而不是冒充可用模型。

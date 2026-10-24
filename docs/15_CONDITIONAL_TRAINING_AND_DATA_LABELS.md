# 15｜V3 条件式模型训练与 500 首数据标注：8GB 显存设计

## A. 不能把 UI 参数当魔法开关
只有数据存在相应观测且训练损失落实控制目标，模型才能学会条件。不能只把 `wildness=80` 拼进 prompt 就宣称可控。500 首音乐足够研究首版，但如果只有常规谱，几乎不可能从中学出可信的 4K/5K/6K 或真实异像机制。不同数据稀缺度下保留真实的 fallback 并明确来源。

## B. 输入输出、阶段结构
- 音乐 features：离线 CPU 逐曲计算 80-bin log-mel、onset、RMS、chroma、BPM/拍点，不要把 500 首音乐一次放入内存；采用 mmap 分窗训练。
- `difficulty_class`：4 类 embedding；`difficulty_value`：数字归一化/MLP；重叠区不合并。
- `chart_mode`：regular/pure_keys/anomaly 的 embedding；`key_count`：0(非 K),4,5,6 的 embedding；掩码不适用条件。
- `performance_intensity` 与 `wildness`：各自独立的连续 0..1 数值经 Fourier/RBF 或 MLP 投影。强烈推荐训练时 **feature dropout** 防止 500 首条件变量与某首歌曲 ID 绑定；条件退化/重采样必须标记且符合音乐-谱面的真标签。
- `performance_style`：有限枚举 embedding；`generation_priority`：训练初期作为推理约束而非强求数据中天然存在匹配标签。
- 初版：条件 token prefix + 每层特征 FiLM（可选逐层，先用 prefix/MLP 做对照，不要过度复杂导致小样本过拟合）。
- **Stage 1** `NoteRhythmNet` 学节奏事件/类型/hold/chord；所有 mode 可共享主干，但 loss 按模式分组，难度/密度校准辅助头。
- **Stage 2** `LineMotionNet` 只在 regular/anomaly 训练动态线；pure_keys 完全旁路并调用静态判定线构造器，`pure_keys` 不该贡献 LineMotionNet 的“静线”损失淹没其他样本。
- **Stage 3** `PlacementNet`: 自由布局 head 学 line_id/x/above/几何关系；`KLanePlacementHead` 在纯配置学固定 `lane_index`、同帧 chord mask、键位 pattern、hold 占用；两条 head 可共享低层但 loss 与 batch 独立加权。
- **Stage 4** 仅在已验证低显存情况下进行轻量联合优化（小头/蒸馏），不在 GPU 同时保存 3 套 AdamW 优化器；模型 bundle 保存三个独立 checkpoint + 条件标准化配置 + lane head + feature schema。

## C. 硬件约束（默认）
RTX 5060 8GB、16GB RAM：`microbatch=1`, `grad_accum=16`, `d_model=192`, 音频时间帧上限 384，note slots 192～256，梯度混合精度、mmap、dataloader workers=0，Sequential GPU stages；优先减少层数/窗口，避免运行 MOSS/LLM。使用 `configs/rtx5060_8gb.yaml` 和 `configs/generation_v3.yaml`，按 `docs/11_AGENT_EXECUTION_AND_GATES.md` 在目标机跑 100 optimizer steps 与真实最长窗口，**不能保证未实际实测的 5060 永不 OOM**。

GPU 分流：`note → release → (regular/anomaly) line → release → placement_head → release → audit(CPU) → browser(CPU/WebGL)`。训练与推理排他占用 GPU，单卡任务锁。

## D. 标签来源：可观测的、推导的、人工的必须区分

| 字段 | 首选来源 | 缺失策略 |
|---|---|---|
| `chart_mode` | 作者标注/格式语义/人工确认 | 不能确定则 `unknown`，不进分路训练 |
| `key_count` | 人工/已知纯配置的轨道结构校验 | `null`，禁止猜测 |
| `difficulty_class/value` | 谱面元信息、可信人工校订 | 标记 unknown，别以音符数臆造 IN 17 |
| `performance_intensity` | 基于单位拍的平移/旋转/加速度/可见性统计后人工校准 | `label_source=estimated` + confidence |
| `performance_style` | 人工分类（允许多个候选/unknown） | 不参与有监督风格 loss |
| `wildness` | 独立组合指标 + 人工抽样评分：节奏熵、断句/不规则、运动强度、非套路 pattern；**模式内归一化** | 只有 proxy，不视为地面真值 |
| `density` | 每拍 Notes / chord / hold 时长量化统计 | 自动 |
| `special_features` | 结构中可确证特征 + 人工验证客户端 | 未验证则 unknown，不训练能力标签 |
| `playability` | 真实人工审核结果 | 缺失；不能用审计 WARN 冒充真人评分 |

`condition_label.schema.json` 提供 `label_source`、`confidence`、`annotator`、`version`。训练时可单独屏蔽低置信标签或降权；不得将未授权/没有标注的谱面悄悄归入默认高质量数据。

## E. 样本分层与数据量门槛
- 按歌曲音频指纹和元数据相关组拆 train/val/test：建议 `400/50/50` **歌曲**，并分别统计三种 mode、4/5/6K、难度和线复杂度是否覆盖；同音不同难度也需同组。
- 真实标注优先：先标 50～100 份覆盖各模式，复标其中 10% 测标签一致性；再批量扩展。模型可辅助预标但不得把无人工核实的预测作为可靠监督。
- 若某模式没有足够数据，训练 dashboard 显示 `coverage_insufficient`；模式仍可提供显式 `baseline` 或 `hybrid`，但**不作为可选择的已训练模型能力**。
- 导入时记录 format、歌曲指纹、谱师/许可、RPE offset、BPM map、多模式类别、版号、哪一部分是弱标注/合成数据。
- 可训练样本需一条完整原音频、其谱面的格式回读、对齐检验；从 500 首切出的多个 window 不能算不同歌曲。波形编码缓存要有 extractor hash。

## F. 增强与防止条件失效
- 仅合法地同时变更音乐与谱面的时间尺度，不能把音频随机 stretch 后却保留原谱面 timing。
- 高难度并不等于更大 wildness；区分技术负荷与结构意外程度。训练时监控条件 mutual information、distribution overlap；必要时使用同歌多难度 pairs 监督难度变化，不能凭空创造不存在的“同歌低狂野/高狂野”配对。
- 条件随机丢弃 (classifier-free style) 可用，但相应标签缺失/不确定时 mask loss；不能把 unknown 默认为 `regular` 或 wildness=0。
- 将规则 baseline 引擎视为可对照系统，不能把由 baseline 生成的伪数据与人工高评分谱面的标记混淆。

## G. 训练目标与复合损失（首版）
- Stage1: `L = λpresence BCE/Focal + λtype CE + λtime Huber + λhold Huber + λchord CE + λdensity Huber`。以带 mask 的正样本数归一，支持非整数格点时间 residual。
- Stage2: `L = λmotif CE + λboundary Huber + λtrajectory smoothL1 + λcontinuity + λparent_valid`。仅 regular/anomaly 数据。
- Stage3 regular/anomaly: `L = λline CE + λx Huber + λabove CE + λconstraint`。
- Stage3 pure_keys: `L = λlane maskedCE + λchord multilabelBCE + λpattern CE + λholdoccupancy`；K mask 必须**在 softmax 前**执行。
- 难度/狂野度条件校准用对应统计量的**弱约束**辅助项；不牺牲 Beat 对齐/几何合法性。条件 loss 权重在 YAML 可调且记录 experiment id。

## H. 检验是否真正学会“条件生成”
同一未见音乐、相同 seed 和模型 bundle，逐项改变一个条件：
1. EZ 5 vs IN 15 vs AT 17，统计 note 密度、pattern/双押频率及真人体验。**不是单纯越难越密**。
2. `pure_keys K=4/5/6`，每条候选只有 K 个合法落点，线静止且各自导出可用。
3. regular `performance_intensity=0/50/100`，运动统计应有趋势；允许不能保证每一首单调，但总体趋势需成立。
4. `wildness=0/50/100`，不规律性指标应总体有趋势但静线不变、不可判定率不升高。
5. anomaly 特殊开关只有 `CapabilityRegistry` 支持时能生效，生成日志说明具体 `model|template|manual` 来源。

人工评分要按模式分别汇总，否则 4K 无动态线会被误判“演出不足”。评价同一曲的 multiple candidates 不能作为跨歌曲训练/验证独立数据；逐次保存评审时间与审阅者身份。

## I. Model Bundle 版本与前端接入
`bundle.json`：`bundle_id`, `stage_checkpoint_hashes`, `condition_schema_version`, `ir_version`, `training_dataset_hash`, `feature_extractor_hash`, `modes_supported`, `key_counts_supported`, `difficulty_ranges_supported`, `special_capability_ids`, `status(experimental|validated|retired)`, `training_hardware_profile`, `eval_metrics`。
- 生成页面在 `GET /api/v1/models` 读取能力并灰掉不支持的选项。
- 训练能完成 ≠ 生成质量验证通过；`validated` 需要跨歌 holdout、非 AI 审计、模式不变式与 Phira 真人试玩证据。
- 不能用虚构 checkpoint id 或空权重放进 registry 来通过 UI。

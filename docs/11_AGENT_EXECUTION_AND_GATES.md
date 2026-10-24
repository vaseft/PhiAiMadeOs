> **V3 优先级提示（2026-10-24）**：本文件是 v2 通用基础说明。**纯配置模式是固定判定线的真实 4K/5K/6K，不是风格倾向**；新增的条件训练、模式分流、异常演出能力限制与按模式评分请以 `docs/12..18` 为准。若本文与 V3 冲突，以 V3 为准。

# 11｜Codex 开发路线、指令与验收门禁（5060/8GB/16GB 特化）

## A. Codex 的工作规则

- 必须在目标设备真实运行才允许把 5060 适配标为 `verified`；没有 RTX 5060 的开发环境只能提交代码与基准脚本，标为 `untested_on_target`。
- 不许用空白网页、随机输出固定几行 Tap、只做模型 forward 或合成样本 loss 下降充当真实训练完成。
- 先实现 format/IR、测试播放器与审核，再进入真实训练；但**环境 GPU 测试必须最早做**，避免后来发现 5060 wheel 不兼容。
- 任意工作之前读取 `AGENTS.md`、`CODEX_START.md`、`docs/09_RTX5060_8GB_DEPLOYMENT.md`、`docs/10_LOW_VRAM_TRAINING_BLUEPRINT.md`。
- 用户只有 16GB RAM，因此训练时**不要默认启动 Docker Desktop、Redis、MLflow Server、JupyterLab、多个 Uvicorn workers、另一个本地 LLM**。
- 用户数据（包括合法获取的自制谱面、官方谱面等）输入前需明确授权；不实现绕过 DRM 的批量下载/破解；外部分发及训练合法性分开检查。

## B. 逐阶段必须执行的任务（按顺序，不可跳级）

| 门禁 | Codex 要实现/执行 | 明确验收证据 |
|---|---|---|
| G0 系统适配 | `diagnose_hardware.py` 真机 CUDA 前后向 | GPU 型号/SM/torch+CUDA/version、日志；失败分类 |
| G1 显存适配 | `benchmark_tiny_train.py` 100 steps 与真实数据最大窗口各至少一次 | reserved、allocated、RSS、耗时、峰值上限；OOM 降级轨迹 |
| G2 数据正确 | 原曲+谱面 → BPM/offset 精确秒数 IR，ZIP round-trip | 10–20 个版权明确的 fixtures + diff |
| G3 特征缓存 | 500 首（先 10 首）按曲 CPU streaming 提取 logmel/节拍；缓存版本化 | 单曲 RSS 峰值、缓存 size、内存不随曲数持续增加 |
| G4 模型阶段1 | NoteRhythmNet 实训→持久化→恢复，跨歌 val，固定线能玩 | checkpoint + 真实 training metrics + 生成示例 |
| G5 阶段2 | LineMotionNet 原型学习/连续轨迹、event round-trip | 动态线不崩坏、覆盖样本和新歌检查 |
| G6 阶段3 | PlacementNet 归线+坐标，几何安全 | 多线多种 Note 完整生成，无违规删事件 |
| G7 非 AI 审核 | NumPy/SciPy/librosa classical + geometry，不引用任何 torch/神经网络 | 虚假偏移能报警、合法切分不误 BLOCK |
| G8 UI | 同步播放、波形/风险、拖动、评分、比较版本 | Browser E2E/截图/本地人工记录 |
| G9 发布 | RPE ZIP 导出、真实 Phira 本地导入并真人玩谱 | Phira 版本、录制/记录、通过/拒绝理由 |

> `G1` 的合成压力测试和 `G4` 真数据训练不是同一件事：G1 通过不证明 500 曲生成质量达标。

## C. 模型实现细节必须落地

- 明确 `model.py` 中每张输入/输出的 Tensor shape，写入单元测试，且 batch=1 能训练。
- 短序列滑窗用 **窗口重叠**，换 BPM 后的 Note 仍按连续绝对音频秒数验证，不能只在每窗口内相对时间看起来正确。
- train/val/test 始终按**歌曲指纹/发行版归属**分组；禁用根据 note 窗口随机切分导致的信息泄漏。
- trainer 使用真正梯度累积：`loss /= grad_accum_steps`，积累完再 `scaler.step()/optimizer.step()`，梯度正常清零；处理 epoch 尾不足积累步数的余数。
- Gradient clipping、NaN/Inf、warmup、val early stop、best/last atomic checkpoint、CPU safetensors、resume RNG / optimizer 状态有测试。
- 显存 profile 建立预算报告：除了最大 `allocated/reserved` 还要记录可用显存与进程峰值；`empty_cache()` 不能掩盖峰值。
- GPU 生成 worker 与训练 worker 同时运行时 API 必须拒绝排队之外的 GPU 任务，且在状态页面解释原因。
- 遇到 OOM 时优先自动保存问题配置和诊断，停止本次 GPU 任务，用户许可后重启更低配置；不要未经通知改模型宽度后继续载入旧权重。

## D. 手动审核必须先于发布

需要界面：曲目列表、模型版本/训练来源、波形+Note/line 轨道、实时可视播放、自动风险定位、滑动拖动、六维评分、评语、`退回修改`、`通过`、`实际试玩确认`。

AI 生成 → 非 AI 审核（格式 BLOCK、DSP WARN）→ 人工审核评分 → 导出 → Phira 真人试玩。评分不能被伪造或由模型自己生成。审计 `WARN` 与 `BLOCK` 在 UI 中区分颜色及处理流程。只有真实试玩证据才能进入 PLAYTEST_CONFIRMED。

## E. 技术栈一致性和验收报告

- 配置来源：`configs/rtx5060_8gb.yaml`，不得用 `configs/example.yaml` 中更高内存参数覆盖。
- Python：3.12 + PyTorch 2.9.1 cu128（初期可复现基准，可逐版升级但每次需重新 smoke test）+ FastAPI + NumPy/SciPy/librosa + SoundFile + ffmpeg + safetensors + SQLite。
- JS：Vue3 + TS + Vite，浏览器 `AudioContext` 时间基准，谱面渲染统一几何求值器。
- 独立 GPU 训练进程，不把 checkpoint 载入 FastAPI。
- 任何安装问题与实际版本保存到 `runs/environment.json` 和 `requirements/lock.txt`（后者由实际运行 pip freeze 生成）。

### 阶段汇报格式（必须写实际结果，不得编造）

```text
门禁：G1 PROFILE
硬件：<nvidia-smi / RAM>
模型/输入形状：<原样记录>
依赖：<torch / cuda / python>
实测步数：<N>
峰值显存 reserved/allocated：<实测 GiB>
CPU RSS 峰值：<实测 GiB>
执行结果：PASS/FAIL/UNTESTED
下一步：<唯一的具体行动>
```

## F. 故障分支

- Torch 未启用 CUDA：不能继续 G1，先解决驱动+wheel 兼容。
- 合成 profile ≤6.2 GiB，但真数据异常 OOM：记录失败样本和输入 shape，修复长尾数据拆窗，再复验；禁止硬剪标签。
- GPU 可训练但系统 RAM 不足：DataLoader 0 worker、逐曲缓存、关闭 UI、限制 API worker、缩短音频帧；确保 Windows/WSL swap 状态可见。
- 模型“会跑却不会编谱”：增加数据多样性/完善 loss/校验标签，不靠把 d_model 从 192 拉到 1024 解决。
- Phira 不兼容：优先修格式/Offset/渲染协议，不能把所有解析错误归咎于 AI 模型。

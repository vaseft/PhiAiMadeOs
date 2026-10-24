
# 【V4 最新约束｜2026-10-24，优先于以下 V3 描述】

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

> **V3 优先级提示（2026-10-24）**：本文件是 v2 通用基础说明。**纯配置模式是固定判定线的真实 4K/5K/6K，不是风格倾向**；新增的条件训练、模式分流、异常演出能力限制与按模式评分请以 `docs/12..18` 为准。若本文与 V3 冲突，以 V3 为准。

# 04｜生成后、人工审核前：严格非 AI 检验器

## 1. 位置与要求

此模块必须在 `generation` 完成之后、允许真人审阅之前运行。它可以重用纯数学音频信号特征库，如 NumPy、SciPy、librosa（经典信号处理接口），**禁止导入任何训练权重、深度学习 BPM/onset 模型、语言模型或用生成模型给自己打分**。独立进程/容器可通过依赖白名单审计。

自动结果分为：`BLOCK`（硬错误无法接受）、`WARN`（需要人看）、`INFO`（数据事实）。“非 AI 检验通过”不是“谱面实际可玩”的充分条件。DSP 是检测高风险节奏问题，不是给音乐创造性做唯一标准。

## 2. 固定管线（此顺序是强制的）

### A. 格式与引用约束 [BLOCK]
1. IR Schema/RPE 结构、字段类型；序列化不含 NaN/Infinity。
2. 所有 music/illustration/assets 路径存在且只指向包内合法相对路径，无 zip-slip/重复冲突。
3. `0 < bpm < configurable_max`、BPM 段单调且有有效起点、事件时间有序、Hold 终点 > 起点、line id 有效。
4. 父子线必须无自引用、无循环、索引合法。事件数、线数、长度、数组大小均有安全上限。
5. 可识别 note/事件类型，未知字段保留并明确标注“不支持”范围。
6. 所有会实际判定的音符均位于可解析的歌曲时间范围（尾部可留用户定义延迟）。

### B. 音乐 DSP 特征 [INFO/WARN]
- **仅经典信号处理**：重采样、RMS/能量、静音片段、STFT/频谱通量 onset-strength、多频带 onset、局部 tempo 自相关/DP beat tracking、spectral centroid，可选传统 chroma。
- 输出 `onset_times_ms`、`onset_strength`、`beat_grid_candidates`、`rms_curve`、`silence_intervals` 和每区域 `confidence/provenance`（表示算法稳定程度，而非模型概率）。
- 不要假定每个 onset 都该落 Note；onset 能量弱的钢琴连音、旋律变化、弱起、鼓点外拍都可能合理。
- BPM 的 0.5x / 2x 候选应同时输出，检测器不能仅凭单个估计否决变拍/半拍谱面。

### C. 音符/音频相关性（仅 WARN）
- 从“真实判定开始时间”抽取音符，按音符开始时间合并多押；Hold 尾部不等于独立 onset，长 Drag 链不应无限制造错误警告。
- 使用音频时间轴和 offset 映射计算音符时间，与附近 onset 峰做容差匹配；输出差值分布（median、P90、直方图）与曲线叠加。
- 指标参考：`anchor_onset_hit_rate`、`anchor_abs_error_p50_ms`、`unexpected_dense_in_low_rms`、`timing_drift_slope`，不能单项自动判定谱面质量。
- **支持可配置弱音节/静音阈值**，留白无音符时不罚分；不同段落给单独统计，避免整首平均掩盖某一段错位。
- **参考阈值只是研发起点**：强谱通量峰 ±50~80ms 检索窗口；检测到持续偏移超过 80ms 时提示 `OFFSET_SUSPECT`，但不直接移动音符；大段静音出现高密度真实 Tap 时警告（演出/弱声可能例外）。阈值须由标注过的正常人类谱面校准并允许关闭。
- 音乐本身节拍含 rubato 或 BPM 切换时，显式将低置信节拍区域设为“信息不足，不自动评分”。

### D. 节奏模式与难度 [WARN/INFO]
- 每小节 Note 密度、分音比例、间隔分布、双押/三押比、Hold 占比、局部极端密度、长时间突然静默；比较目标难度分位数（基于**训练集授权谱面的描述统计**，不是训练神经网络）。
- 这些仅辅助人工标注 `PATTERN_UNUSUAL`、`DENSITY_SPIKE`；可能是刻意设计，绝不能把所有极端段落自动改成平均密度。

### E. 判定线/可玩几何 [BLOCK/WARN]
- 检验父子拓扑、事件数学定义、ease 索引、连续性和所有参数边界；严重非法参数 `BLOCK`。
- 在每个 Note 判定时刻 `t_hit` 计算世界变换 `T_line(t)`，将局部 Note `positionX` 与 `above/yOffset` 映射到屏幕落点；复现父线旋转/缩放的实际组合顺序。
- 计算同时刻多指触控数、落点重合/过近风险、相邻 Note 视野跨越速度、Hold 持续位置轨迹、Flick 触控可执行方向、运动线把音符带出屏幕的时长。
- 对旋转角做角度环绕处理（避免 359°→0° 被误判 359° 跳跃）；叠加事件按实际客户端语义求值。
- 几何“过快”“遮挡”属于 **WARN**，除非输入无效/非有限值。屏幕尺寸、触屏限制、谱面难度要求可配置。
- 必须报告音符 ID、判定线 ID、开始/结束毫秒、严重程度、计算指标、截取的状态，前端点击能跳转。

### F. round-trip 与打包 [BLOCK]
`IR -> export RPE -> safe ZIP -> reload -> IR`，比较时间/类型/线层级/事件。选择真实客户端支持的最低特性集合；有损丢弃不可自动当作 PASS。

## 3. 自动评分的正确边界

推荐审计输出 `audit_status`、`summary_counts`、`metrics`、`issues[]`、`feature_cache_ref`，可以有 0~100 的 **风险展示分**，但应命名为 `audit_health_index`，不得命名为“音乐质量”或“人工可玩性分”。

最简规则：任意 `BLOCK` = `AUDIT_BLOCKED`；无 BLOCK 有 WARN = `AUDIT_WARNED`；无 BLOCK/WARN = `READY_FOR_REVIEW`。全部候选均可在调试模式打开预览；默认仅在无致命错误时允许人工通过。

## 4. Issue 结构

```json
{
  "code": "OFFSET_SUSPECT",
  "severity": "WARN",
  "start_ms": 12000,
  "end_ms": 16000,
  "note_ids": ["note_132", "note_133"],
  "line_ids": ["line_02"],
  "message": "本小节的音符起点相对音频强onset存在持续偏移，需人工试听",
  "evidence": {"median_delta_ms": 96.4, "matching_window_ms": 80},
  "suggested_action": "review_only"
}
```

## 5. 校准与防误伤

- 准备“通过真人审核”的授权真谱以及故意整体平移 ±100ms、加倍密度、制造父线循环、插入不合理 Hold 的对照集合。
- 目标是识别**已知注入异常**并控制对正常真谱的误报；不可仅凭模拟程序自己的模型生成输出做校准。
- 匹配算法限制一条独立 onset 与一个时间锚事件的匹配关系，允许多押合并；结果显示分区统计、置信区间和低信息区域。
- `confidence` 不足时返回 `UNKNOWN`，不假装完美。实际参数在 `configs/example.yaml` 配置。


# 【V4 最新约束｜2026-10-24，优先于以下 V3 描述】

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

# 18｜交给 Codex 的 V3 增量开发执行单（必须写代码）

**此清单对 V2 的 G0..G9 增加 V3 条件模式门禁。** 唯一产品名：PhiAiMadeOs。目标机器 RTX 5060 8GB VRAM + 16GB RAM，需真机测试才能给出适配承诺。

## P0 已知错误先修正
- 全仓搜索 `4k_style`/`5k_style`/`6k_style`/`layout_density_mode`/“风格倾向”并修正为真正 `pure_keys`、`key_count={4,5,6}`。
- 对旧请求 schema 版本 `v2` 显式提示弃用，不能将 style 值静默转换并声称是 4K。
- 凡 pure_keys，判定线一条或多条但**始终静止**，没有动态演出；UI 演出强度强制 0。

## M0 环境与仓库
- 保留现有工程；读取 docs 12..18 及 schemas/configs；建立 `src/phiaimadeos/conditions/`, `generation/`, `chart_core/`, `models/`, `audit/`, `review/` 和 `web/`；构建 `scripts/validate_v3_contracts.py`，跑通过的结果写入 `runs/`。
- 真机执行 `scripts/diagnose_hardware.py --require-cuda`，`scripts/benchmark_tiny_train.py --steps 100 --grad-accum 16 --max-vram-gb 6.2`。非目标机器标 `UNTESTED`。

## M1 请求与数据模型（先做最小垂直切片）
- 实现 Pydantic `GenerationRequestV3` + enum、跨字段校验、ConditionNormalizer，记录 `request/effective/overrides`。
- SQLite/Alembic 安全迁移；`GET /models`, `GET /capabilities`, `POST /generation-conditions/normalize`。
- 添加 pytest 测试 M01..M14，不需要模型就能全部跑通。

## M2 纯配置固定 K 模式
- 解析实际有授权的 Phira 4K/5K/6K 示例；实现 `LaneLayoutAdapter` 与 `FixedJudgementLineBuilder`，确定 RPE `positionX` 映射。
- 先实现 deterministic `FixedLaneBaseline(K)` 可玩且标 `baseline_only`；审计端写 `FixedLaneInvariantChecker`，在生成前、导出后均执行。
- 实现 `LaneRenderer`，支持同步波形、真实 K 列、Hold、多押、键位统计。Phira 测试记录 4K/5K/6K 分别一张。
- 注意：baseline 用于验证格式与手感，不可对用户称“已经训练了 4K 模型”。

## M3 条件式数据标注
- Chart IR v3 增加 `chart_mode`、可选 `lane_layout`、`anomaly_features`；导入 500 首（前期 10..20 首）构建 song-group split；记录 mode/K/difficulty/可观测演出特征、弱监督/人工标签。
- 标注仪表盘展示各模式/K 数据缺口、置信度、训练/验证/测试分布；无对应模式时 UI 模型生成不可选或显示 baseline。

## M4 8GB 训练：条件 NoteRhythmNet
- 冻结 CPU 缓存音频特征，按窗口分块；加入难度/模式/K/演出/狂野度条件 embedding；训练真实音符时间、类型、数量与 Hold 端点。
- 按 G4 实训、记录 checkpoint/seed/profile/跨歌指标；实际试生成一首非训练歌曲。

## M5 条件 LineMotionNet 与 KLanePlacementHead
- 常规/异像的 LineMotionNet：动态判定线；纯配置跳过 line 模型并使用静态线。PlacementNet 分自由 layout head 和 K-lane head，训练 mask 和 lane index loss。
- GPU 分阶段训练/释放，不在 8GB 内同时放三个优化器。缺少 K 训练样本时注册成 `baseline_only`，不能声称 learned。
- 实现整曲拼接、局部重生成和 mode immutable constraints。

## M6 特殊异像能力验证
- 构建 `CapabilityRegistry` 与目标 Phira 版本 test fixtures；先只启用真正验证过的视觉 shader/`attachUI` 等机制。
- 对连击数变化，明确区分 UI 视觉变化与**真实连击规则**；默认拒绝 true combo mutation。
- `AnomalyEventPlanner` 模板与 AI 模型来源分离，支持导出后实际客户端验证；不强制把此阶段当作基础 K 模式发版前置条件。

## M7 页面完整联通与非 AI 检验
- 音乐上传 + Model selector + Mode switch + difficulty + performance + wildness + features + live preview + timeline + rating + local export。
- 非 AI 审核禁止 torch/LLM，谱面 RPE round-trip、BPM/Offset、节拍可疑点、固定列、动态线父子几何、异常特性兼容均可定位。
- Vue 浏览器 E2E 与 SQLite persist 审核结果；审核后评分和问题可作后续训练反馈。

## M8 联合验收与性能
- 逐模式跑 `docs/17_V3_VALIDATION_AND_MODE_MATRIX.md` 的 M01..M16；各模式最少一条生成 ZIP 真正导入 Phira。
- 对 model bundle 选择、条件控制 A/B、wildness 趋势、演出强度趋势做完整报告。未实际进行的测试不能写通过。
- 发布前只标记实际验证的能力；记录 engine version 与手工试玩证据，不能用自动录屏冒充真人。

## 每次 Codex 迭代的规定输出
```
本次阶段: <Mx>
实际变更的代码文件: ...
运行命令: ...
测试真实结果: PASS/FAIL/UNTESTED + 摘要
在 5060 8GB/16GB 上的实测: ...
模型来源: learned / hybrid / baseline_only
当前 4K/5K/6K/regular/anomaly 功能状态: ...
剩余阻塞与下一步: ...
```
**不允许仅回复架构图、TODO 列表、空页面、随机 Tap 假装 AI 或空模型 checkpoint。** 约束冲突先满足可玩性、数据真实性和 Phira 兼容，再优化演出。

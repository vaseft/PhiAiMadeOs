
# 【V4 最新约束｜2026-10-24，优先于以下 V3 描述】

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

# 14｜特殊异像谱：引擎能力探测、视觉效果与真实玩法区别

## 1. 总原则
异常演出可以激进，**绝不假装 Phira 原生支持未验证的玩法修改**。比如“局内变化的连击数”须区分：真实结算/连击计算（gameplay combo counter）和视觉上显示的数字（cosmetic combo overlay）。本项目**不承诺**谱面文件能修改游戏的真实连击数、分数或判定规则。

## 2. 特殊效果能力分类
每项功能独立记录：`feature_id, min_engine_version, carrier, capability(native_supported|visual_only|requires_client_mod|unsupported|unknown), source, probe_fixture, probe_result, fallback, accessibility_risk`。

| ID | 用户效果 | 可能技术途径（待样本+实机检验） | 必须显示的边界 |
|---|---|---|---|
| `visual_noise` | 噪声、故障画面、噪域式感觉 | `extra.json` shader/effects（需具体引擎支持） | 是视觉效果，不改变判定 |
| `combo_visual_overlay` | 连击数字视觉变化/错位/假数 | `attachUI` 绑定连击 UI 动画；`textEvents` 文字图层/纹理遮罩 | 可影响显示，**不能宣称修改真实连击** |
| `ui_dislocation` | UI 位置/旋转/透明度变化 | RPE `attachUI` 的实际支持能力 | 首先逐版本兼容测试 |
| `false_feedback` | 假提示/假 Note 演出 | RPE `isFake`、文字事件、纹理事件 | 不得诱骗成无法判定真 Note |
| `line_glitch` | 判定线故障感/高频运动 | 常规 line move/rotate/easing | 强度上限 + WARN；慎用闪烁 |
| `visual_misdirection` | 视觉错觉 | 线和 Note 的运动/alpha 事件 | 不更改核心判定时刻 |
| `true_combo_mutation` | 真正改变内部 combo 统计规则/数值 | 通常需游戏源码/客户端扩展 | 默认 `unsupported`，不在普通 RPE 中生成 |
| `scoring_rule_change` | 修改判定/分数计算规则 | 通常需引擎修改 | 默认 `unsupported` |

Phira 文档在 RPE 扩展项提供 `attachUI` 绑定 `combonumber`/`combo`/`score` 等元素并支持变换，扩展 `extra.json` 的 shader `global` 可影响 UI 视觉；这些只是可利用的**渲染能力**，不意味着获得修改逻辑计分的接口。文档：
- https://yuevuwu.github.io/phira-docs/en/chart-standard/chart-format/rpe/extend.html
- https://yuevuwu.github.io/phira-docs/en/chart-standard/chart-format/rpe/extendEvent.html
- https://yuevuwu.github.io/phira-docs/en/chart-standard/extra/effect/index.html
- https://github.com/TeamFlos/phira/releases

## 3. 特殊效果管理器 `AnomalyCapabilityRegistry`
- 与实际测试目标 Phira 版本绑定，初始所有可选特性标 `unknown`，不可选，验证后升为 `native_supported` / `visual_only` 等。
- 参数请求包含 `special_features`；若携带 `unsupported` / `unknown`，返回 `422 FEATURE_UNAVAILABLE` 及版本/原因/回退建议。UI 不许先勾选后静默丢弃。
- 只允许在 `chart_mode=anomaly` 使用；pure_keys 永远禁止使用。
- 明确区分 `basic_rpe`、`rpe_with_extra`、`client_mod_only` 导出目标，**普通 Phira ZIP 不含客户端需要自行改动才能运行的承诺**。
- 效果需“效果目录/资源白名单 + 版本探测 + 导出后回读”；无法随 ZIP 便携的 shader/纹理必须报告不可导出。
- 每个效果有 `start_beat, end_beat, priority, parameters, compatibility_target` 与异常事件 ID，任意两个效果重叠要做遮挡/资源冲突检查。

## 4. 特殊异像不依赖 500 首稀有标注从零训练
第一代：条件模型生成正常可玩的 Note + line → `AnomalyEventPlanner`（有限模板、规则、能力矩阵）→ 实际 RPE/extra 导出。标签足够再训练事件选择/参数调整 head。输出元数据标记 `model_generated`、`template_inserted`、`human_authored`，不能将模板假称模型学会。

## 5. 保护机制
- 峰值亮度、频闪风险、遮挡时长、UI 乱序、可读性、眩晕风险等通过确定性计算产生 WARN；高频闪烁默认禁止，必须能在 UI 中一键关闭效果。
- 支持“预览特殊效果开/关对照”、低动态视觉模式、局部移除/缩减演出。
- 演出检查不能通过掉帧导致真正不可打的 Note；任何实际判定规则变更都禁止在标准谱面通道隐式进行。

## 6. 验收
- 在纯配置与常规模式请求 anomaly → 拒绝。
- `combo_visual_overlay` 生成后，UI 必须标记“只改变显示”；导出后在相应 Phira 版本实机看见效果才登记 compatible。
- `true_combo_mutation` 在不更改客户端源码的标准发布通道永远不可选，并给出明确原因。
- shader 不支持/丢失 → 显示不支持或降级候选 `visual_effect_removed` 并要求用户确认，不能静默修改。

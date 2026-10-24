# 17｜V3 验收矩阵：每种模式真正可玩才算完成

## 1. 测试层次
单元测试（schema + condition normalizer）→ 解析导出互逆 → 实际窗口训练 → 全曲推理 → 非 AI 审计 → 浏览器预览/人工打分 → **Phira 本地导入与真人试玩**。未执行的标记 `UNTESTED`，不得宣称 `PASS`。

## 2. 合法请求与预期

| 用例 | 条件 | 期望 |
|---|---|---|
| M01 | regular + IN15 + performance 80 + wildness 50 | 可以动态线，key_count=null，进入独立 Audit |
| M02 | pure_keys + 4K + EZ8 + wildness 0 | 4 个固定列，线完全静止 |
| M03 | pure_keys + 5K + HD12 + wildness 60 | 5 个固定列，线完全静止 |
| M04 | pure_keys + 6K + AT17 + wildness 95 | 6 个固定列，线完全静止，wildness 不越界 |
| M05 | anomaly + IN16 + 已证实 visual_noise | 仅受支持的 shader/extra 且警示可读性 |
| M06 | anomaly + combo_visual_overlay | 视觉幻象标识；不声称修改游戏真实 combo |
| M07 | pure_keys + key_count=null | 422 缺少 K |
| M08 | regular + key_count=6 | 422 不允许 K |
| M09 | pure_keys + special_features 非空 | 422 |
| M10 | pure_keys + performance_intensity=95 | 被规范化为 0，返回 override 原因；导出静止 |
| M11 | anomaly + true_combo_mutation | 422 UNAVAILABLE，不许伪支持 |
| M12 | EZ 11 / HD10 / IN18 / AT14 | 422 难度超范围 |
| M13 | `wildness=-1/101` | 422 |
| M14 | `layout_density_mode=6k_style` 旧参数 | 422 明示迁移为 pure_keys + key_count=6，不能自动解释 |
| M15 | 同曲不同 seed | 至少可生成不同可比候选，版本与条件仍完整 |
| M16 | 同一 seed 全链路 | 同环境固定版本可尽可能复现；记录非确定性 CUDA 操作 |

## 3. 数据真实有效性
- 500 首：检查去重、同曲多难度不跨 train/val/test；计数是“歌曲”和“谱面”两列。
- 三类模式和各 K 分布在数据报告中独立列出，稀缺时明确显示 `coverage_insufficient`。
- 特殊异像标签必须有可复现引擎能力证明；没有证明只能在 sandbox 研发，不能发布。
- 4K/5K/6K 至少各一张有授权样本用于格式回读、预览比较和真实游玩测试。

## 4. 不变式 / 格式
- 生成的纯配置全曲 K 不变，note 每列落点准确。RPE 导出前后都运行 staticness check，beat-offset 映射和 note 数量一致。
- 短 Hold、跨窗口 Hold、双押与同列冲突检查；单击/拖拽/长按/滑键实际类型不混用。
- 对任意 BPMMap、偏移、弱起/切分存在理性容差；Non-AI audit 不直接用 onset mismatch 判无效。
- regular/anomaly 动态线在浏览器帧级几何轨迹与导出后回读的 RPE 轨迹误差需在测试设定容差内，无 parent cycle；发生特性丢失必须 BLOCK。
- 引擎不支持的 shader/绑定 UI 不能只靠 JSON Schema 通过就算成功。

## 5. 5060 显存测试
- 训练三阶段和 K-lane head 都应单独 profile（含最长合法窗口），记录真实 CUDA reserved/allocated/RSS，并验证关闭训练进程后显存释放。
- 目标 reserved≤6.2GiB 只作为工程软预算；超过则剖析/缩窗/activation checkpoint，仍 OOM 必须 fail 并记录配置，**不保证未测硬件一定成功**。
- 小模型真实有授权谱面至少完成 1 epoch（或者 dataset demo subset）才可称训练能力已验证；合成 100-step profile 不是模型性能验证。

## 6. 模型条件响应
- 在同一首未见歌曲控制变量比 regular/4K/5K/6K/anomaly；不应因为变模式出现 K 不匹配或者假动画。
- 训练模型与 baseline 做客观指标比较：节拍事件 F1、hold 端点、line geometry valid rate、K 键位 valid rate、密度、模式满足率。
- 人工分别比较低/中/高狂野度谱面；图表展示统计趋势并保留大量无变化的失败样例。

## 7. 浏览器 E2E / 人工验证
- 切 pure_keys，演出强度变灰、K 按钮出现、特殊开关消失，提交 API condition id 与显示一致。
- 查看 4K 及 6K 真正不同数量的列，判定线无法拖动；切常规模式恢复动态预览。
- 波形与 Note timeline 同一个 `audioSeconds` 时钟；拖进度条不改变音符绝对时间；pause/resume 不累积偏差。
- 评分保存后刷新仍存在；退回编辑产生新版本且保留历史人工分数和旧审计报告；被 Block 的候选不能人工批准。

## 8. Phira 客户端验收登记表（至少覆盖）
记录设备 OS、Phira 精确版本、导入 ZIP hash、模式、K、随机 seed、是否实际导入、是否能打、Hold 与多押是否有效、特殊特性是否真的可见、评分/录屏（自愿）、复测人、复测日期。

**必须至少实机验证**：regular 1 张、pure_keys 4K/5K/6K 各 1 张、anomaly 的每个标为 supported 的特殊功能各 1 张（缺少特性不宣称已验收）。

## 9. 发版门禁
`experimental`：有真实权重且跨歌测试但尚未实机验证；`validated`：通过所有声明支持模式的自动验收和相应 Phira 真人试玩；`unsupported`：缺训练数据/引擎不支持则 UI 隐藏或禁用，并解释原因。**优先交付可玩的 4K 静线与常规谱，不因异像 feature 缺失阻塞基础模式**。

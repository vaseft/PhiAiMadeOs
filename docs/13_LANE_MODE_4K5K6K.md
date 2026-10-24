# 13｜纯配置模式：真正的 4K / 5K / 6K 固定轨道谱面（Phira）

## 1. 需求不可误解
用户明确指出 Phira 社区存在**正常 4K、5K、6K 纯配置谱面**：列数分别为 4/5/6、判定线不会动。这里的 K 指**固定离散轨道数**，不是“4K 风格”“四指难度”或“等效手法”。常规谱面和特殊异像无需强迫使用 K 轨道。

首版采用“**一条横向静态判定线 + K 个离散 X 列**”的渲染与导出策略；如果实际 Phira 社区谱样本使用多条并排/分段静态线，新增 `lane_render_profile` 适配，可保留原始组织结构，但每条物理判定线均不得运动。**不要假设 JSON 中 `judgeLineList.length == K` 就代表 K 键。**

## 2. 独立且可验证的 IR
```json
{
  "chart_mode":"pure_keys",
  "lane_layout":{"lane_count":5,"lane_centers_normalized":[-0.8,-0.4,0.0,0.4,0.8],"fixed_judgement_y":0.75,"render_profile":"single_static_line"},
  "notes":[{"id":"n1","lane_index":2,"kind":"TAP","start_beat":{"numerator":4,"denominator":1},"line_id":"fixed0","x":0.0,"above":1,"is_fake":false}],
  "judge_lines":[{"id":"fixed0","parent_line_id":null,"events":[]}]
}
```
这是**说明字段的片段**，正式文档以 `schemas/chart_ir.schema.json` + `schemas/generation_request.schema.json` 与版本迁移为准。`lane_centers_normalized` 是内部 UI 的归一化横坐标，导出 RPE 的 `positionX` 需要通过实测支持范围映射，不可把屏幕坐标直接冒充 RPE 局部 X。

## 3. 固定列位置
- `K∈{4,5,6}`，第 `i` 条列中心内部归一化 `x_i=-1+2*(i+0.5)/K`，`i=0..K-1`；等价分别为：
  - 4K：`[-0.75,-0.25,0.25,0.75]`
  - 5K：`[-0.80,-0.40,0.00,0.40,0.80]`
  - 6K：`[-0.8333,-0.5,-0.1667,0.1667,0.5,0.8333]`
- note 训练标签同时存 `lane_index` 和经确证的 `positionX` 变换，不允许用浮点最近邻代替真轨道标签而不记录误差。
- 使用 `LaneLayoutAdapter` 管理不同社区纯配置谱的列距、屏幕比例与中心点；解析真实样本时估计/人工确认是否是固定轨道；若视觉多线仅为装饰，保持其兼容数据但不要让它参与纯配置动态演出。
- 判定线运动：默认单线或多线，所有线的 `MOVE_X/MOVE_Y/ROTATE` 动作随时间的取值必须是常量（通常无事件），`ALPHA` 不做显隐演出，图像/自定义纹理事件也不做动画，父线不能引入运动。
- 流速 `SPEED` 可以有**可读性所需常量**；如需要 SV 变速，新增明确选项 `allow_sv` 并独立验证。V3 默认纯配置 `allow_sv=false`，禁止动态变速以保证固定配置体验。

## 4. 音符与手法
- 候选事件仍由 NoteRhythmNet 预测 onset/音符类型/Hold 长度；`KLanePlacementHead` 输出 `lane_index`、每键概率、多押 mask、相邻 pattern 类别。
- 同一时刻允许 1～K 个键；不得出现 K+1 个不同列、同列无意义重复碰撞；Hold 过程中同列后续音符按明确定义的兼容规则检查。
- 单列快速重复、双押、交替、楼梯、Trill、Jack、Chordstream 等作为统计与标签；**“可玩性”不能仅由连续 note 距离判断**，用可解释的启发式再人工试玩核实。
- 不强制所有模式只能 Tap/Hold；若数据存在 Drag/Flick，需明确它们在 Phira 的实际判定行为，映射有证据后才用于正式 K 配置输出；不能为了四种类型覆盖率盲目塞音符。
- 狂野度高可以增加合法切分、短串和复杂 pattern 频率，**不会增减 K、不会动画判定线、不会让谱面不可判定**。

## 5. 训练策略
1. 导入时识别 `pure_keys` 或由人工标注；准确标注 K，不能按线条数量猜 K。
2. 每种 K 的专用实例数量统计并写数据质量报告；**500 首总体数量不代表每种 K 的数据充足**。
3. 若 K 训练样本不足：用规则基线 `FixedLaneBaseline(K)` 输出可试玩初稿，同时前端明确标记为 `hybrid_or_baseline`，不宣称是模型学会的 6K。
4. 建议与自由布局共享音乐特征提取器 + 节奏模型；K-lane 使用条件 embedding 和 `K` 掩码的布局 head，mask 不存在的列。K=4 时 index 4/5 的 logits 使用 -inf 而非事后裁列。
5. 训练时使用基于歌曲的分组划分；报告每种 K 的 note F1、键位分布、pattern n-gram、chord 分布、不可玩告警率、真人评分。
6. 条件训练避免 K 标签和实际分布互相矛盾；无 K 标签的普通谱面不参与 lane placement loss。
7. 如数据稀缺允许 4K 预训练迁移到 5K/6K，但转换的谱面标为**合成/弱标注**，不能当真人高评分金标准。

## 6. 固定模式的不变式
```python
assert chart.chart_mode == 'pure_keys'
assert chart.lane_layout.lane_count in (4, 5, 6)
assert all(0 <= n.lane_index < chart.lane_layout.lane_count for n in chart.notes)
assert all(is_static_transform(line, full_chart_range=True) for line in chart.judge_lines)
assert all(not has_dynamic_ui_animation(line) for line in chart.judge_lines)
assert not chart.anomaly_features
```
- 实际实现 `is_static_transform` 要使用与播放器相同的曲线求值器，对所有关键事件边界、曲线极值/采样点及父线递归求值；单看事件数组为空不足以证明静止。
- 运行时 `PureKeysInvariantViolation` 应 `BLOCK` 并定位违规事件，**不允许修复器偷偷删除有意义的用户事件**。模型输出可以有可追踪的修复建议/再生成。
- 在 RPE 导出前与导出后回读 **双重执行** 不变式。

## 7. UI/审核
- 纯配置展示真实 K 个竖列、长条轨迹和固定横向判定位置，列宽按分辨率自适应；可显示每键命中密度。
- 打分中“判定线演出”替换为“配置变化与音乐表现”，**保留维度键名兼容旧评分数据并记录 scoring_rubric_version**，总分依旧 100。
- 自动检验增加键数、同列冲突、非静态线、超屏等致命校验。谱面能导入游戏不代表手法可玩，真人评分是最终主观证据。
- 验收矩阵至少各 1 张 4K/5K/6K，含 Hold 和多押；Phira 真机测验需要逐类型记录版本/设备/输入方式。

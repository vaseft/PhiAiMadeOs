# 12｜V3 条件式谱面生成：产品契约与模式分流

> 本文件是 v3 的最高优先级功能规范，覆盖旧版本关于“4K/5K/6K 是风格倾向”的错误解释。V3 的 4K/5K/6K 是**真正固定 4/5/6 条轨道位置的纯配置谱面**，且判定线在游戏过程中**不发生位置、角度、可见性等演出变化**。必须可以经 Phira 实机导入与游玩检验。

## 1. 用户可见的唯一产品名称
`PhiAiMadeOs`。生成页面标题“PhiAiMadeOs · 谱面生成工作台”。中文 UI 优先。

## 2. 三种互斥的主模式（重要）

| `chart_mode` | UI 名 | 主要特征 | 是否可选 K | 判定线动态 | 特殊机制 |
|---|---|---|---|---|---|
| `regular` | 常规谱面 | 完整 Phigros 风格 Note + 判定线 | 否 | 可，强度可调 | 默认关闭，可扩展受控视觉特效 |
| `pure_keys` | 纯配置 | 真正固定 4/5/6 条轨道位置的下落式手法配置，可在 Phira 游玩 | **必须选择 4/5/6** | **绝对不允许** | 不允许 |
| `anomaly` | 特殊异像 | 在可用 Phira/RPE/扩展机制内进行非常规演出 | 否 | 可 | 按能力矩阵逐项打开 |

**优先级**：`pure_keys` 的“不动线、固定列、无特殊机制”约束高于演出强度、狂野度和任意模型输出。若前端残留其他参数，后端规范化并返回 `effective_conditions` 及 `overridden_fields`；不得偷偷忽略或让旧值生效。

## 3. 控制字段

| 名称 | 类型 | 默认 | 语义和行为 |
|---|---|---|---|
| `model_bundle_id` | string | 必填 | 已验证的条件模型组合/版本；不存在则禁用正式 AI 生成，规则演示须标明 `baseline_only` |
| `music_asset_id` | string | 必填 | 用户已上传且解析成功的音频资产 ID；API 不接受任意磁盘路径 |
| `difficulty_class` | EZ/HD/IN/AT | IN | 类别与数字**同时入模**，不单靠 UI 文本 |
| `difficulty_value` | integer | 15 | EZ=0..10; HD=11..14; IN=14..17; AT=15..18，整数初版；以后扩展小数需版本升级 |
| `chart_mode` | regular/pure_keys/anomaly | regular | 分路选择，**不是风格标签** |
| `key_count` | 4/5/6/null | null | 仅 pure_keys 必填，其余模式必须 null |
| `performance_intensity` | 0..100 | 50 | 常规/异像判定线运动和视觉演出；纯配置时强制 0 |
| `performance_style` | calm/standard/rhythm_linked/ornate/experimental | standard | 纯配置时强制 `none`（规范化后） |
| `wildness` | 0..100 | 30 | 激进程度：节奏切分、配置复杂性、演出变化；**不等于 Note 密度，也不能越过可玩性硬约束** |
| `generation_priority` | playability/balanced/performance | balanced | 质量权衡，pure_keys 禁止 performance |
| `special_features` | string[] | [] | 仅 anomaly，能力矩阵中明确支持且用户选择的功能才可生成 |
| `strict_playability` | boolean | true | 不得关闭格式、几何等核心硬约束；仅控制 WARN 容忍度 |
| `seed` | integer | 可选 | 确保按同一模型/代码/特征版本尽可能可重现 |
| `target_duration` | full_song | full_song | 正式输出覆盖整首曲；局部预览/重生成用单独 API |

默认值由 UI 初始化和服务器双向校验，后端是唯一权威。`wildness=100` 也不允许多余事件、NaN、不可判定音符或破坏 fixed-lane 结构。

## 4. 难度是“目标”不是保证
- EZ: 0..10，HD: 11..14，IN: 14..17，AT: 15..18，按用户提供范围建立**产品级约束**，不声称是官方通用分类。
- IN/HD 在 14 重叠、IN/AT 在 15..17 重叠，必须保留 `difficulty_class` 和 `difficulty_value` 两个独立条件。**不能**仅凭数值重建类别。
- 数字先整数；输入不合法返回 HTTP 422，UI 禁止提交。实际难度由真人试玩评分和分布估计评估，不会由标签自动保证。
- 难度切换不得覆盖同一歌曲其他候选；每个候选持久记录请求条件与**规范化后生效条件**。

## 5. 演出效果与狂野度
- `regular`：`performance_intensity` 影响判定线移动幅度、运动 motif 类型、事件频率；`performance_style` 控制平稳/节奏联动/华丽等趋势。
- `pure_keys`：演出控件禁用且始终为 0，**线静止**；狂野度仅改变可游玩键位配置和节奏策略，不能偷偷旋转/位移判定线。
- `anomaly`：先通过 `CapabilityRegistry` 验证特殊特性，再在已支持范围内生成。UI 必须解释 `simulated_visual`、`native_supported`、`unsupported` 的区别。
- 参数训练需要观测标签证据；没有标注的维度不得假称已学会“按狂野度精准控制”。

## 6. 完整生成管线
```
上传音频 → 探测并确认 BPM/offset → 选择模型 bundle 与生成条件
       ↓                          ↓
ConditionNormalizer ───────→ ConditionEncoder
       ↓                          ↓
ModeRouter            DSP + NoteRhythmNet (条件训练)
       ├─ regular ──→ LineMotionNet → PlacementNet ─┐
       ├─ pure_keys ─────── 固定键位 LanePlacementNet / fallback ─┤
       └─ anomaly ─→ LineMotionNet → PlacementNet → CapabilityEngine ─┘
                                      ↓
                             统一 Chart IR v3
                                      ↓
                      模式不可变约束 / RPE exporter
                                      ↓
                          独立传统 DSP + 几何审计
                                      ↓
                            人工预览、标注、评分
                                      ↓
                           本地 ZIP → Phira 试玩
```
- Note 模型通用，但 placement 的 **K-lane head** 与自由布局 head 不同，LineMotionNet 在 pure_keys 时完全绕过。
- 仅按时间/beat 有意义的局部重生成，维护前后窗口 continuity 与版本号；pure_keys 局部重生成不得改变 K、lane centers、线状态。
- 推理与生成任务单 GPU 串行执行；全曲能由流式分块完成，绝不要求整首音乐装入显存。

## 7. UI 交互硬规则
- 左侧：上传与音频基本信息；模式单选；大类与难度数值；纯配置时出现 `4K / 5K / 6K` 三按钮；演出强度/风格（pure_keys 灰掉）；狂野度；生成优先级；特殊功能（仅 anomaly 展示可选能力）与 Seed。
- 中间：两个可切换预览器 `PhigrosRenderer`、`LaneRenderer`。pure_keys 始终用实际**固定列**预览；可叠加波形、节奏点和键位轨道图，不得把动态线预览当成 4K。
- 右侧：非 AI 审计 WARN/BLOCK、分项打分、问题定位、版本对比和导出。
- 无训练权重时禁用“AI 生成”，单独提供“规则基线（仅测试）”，不能用模板冒充模型。主模式切换时反馈会禁用哪些控制。

## 8. 目标机限制
RTX 5060 8GB / RAM 16GB。共享冻结音频特征，采用条件 token/MLP、小模型单阶段训练。纯配置的模型只训练/加载固定列 head；常规和异像路径按旧文档的动态线阶段模型顺序，所有 GPU 占用遵循 `docs/10_LOW_VRAM_TRAINING_BLUEPRINT.md`。

## 9. 本文档必须对应的测试
- `pure_keys` 提交不含 K / K=7 / 携带 anomaly 机制 → 422（或明确可记录的规范化拒绝策略，不可吞掉）。
- `pure_keys K=4/5/6` 所有 note `lane_index∈[0,K-1]` 且经投影到指定固定列中心；全曲 line position/rotation 固定。
- `regular/anomaly` 的 `key_count` 必须 null；旧 API 传 `layout_density_mode` → 显式迁移错误，不能静默当成真实 K。
- `performance_intensity=100` + `pure_keys` → 后端强制 0 并返回覆盖通知或 422，两端行为一致；本方案推荐规范化并返回覆盖通知。
- `wildness` 0/50/100 的 UI→API→数据库→模型条件→导出/审计中全部保持一致，单调趋势需通过数据统计而不是声称逐谱保证。

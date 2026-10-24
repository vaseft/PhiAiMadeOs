> **V3 优先级提示（2026-10-24）**：本文件是 v2 通用基础说明。**纯配置模式是固定判定线的真实 4K/5K/6K，不是风格倾向**；新增的条件训练、模式分流、异常演出能力限制与按模式评分请以 `docs/12..18` 为准。若本文与 V3 冲突，以 V3 为准。

# 02｜数据、谱面格式与时间坐标

## 1. 首期数据目标

预期约 500 **不同歌曲**，每首可有 1~N 张谱面。数据划分示例：400 首训练、50 首验证、50 首锁定测试。划分单位必须是 `song_group_id`，包括同音频的转码、裁切、加速版本、各种难度谱面；禁止把相同歌曲的一张谱面放 train、另一张放 test。应使用 SHA-256 + 音频指纹/人工复核检索高度近似音频。

优先顺序：授权明确、能正常游玩、音乐与谱面能准确对齐、格式特性可解析、覆盖不同难度与编配。官方谱面与 Phira 用户谱面的许可状态需逐条登记；用户自行下载不等于 AI 训练/分发得到授权。

## 2. Manifest 字段
每一个谱面存一条记录：`chart_id`、`song_group_id`、`audio_sha256`、`chart_sha256`、`source_type`（phira/official/user_created）、`source_reference`、`license_status`（explicit_permitted/restricted/unknown）、`allowed_actions`（local_research/training/distribution）、`difficulty`、`format`、`chart_offset_ms`、`music_duration_s`、`parser_warnings`、`ir_version`、`split`、`quality_tags`、`human_verified_alignment`。未经核实的数字评分只作参考字段，不等于谱面质量真值。

导入时单包限额、总展开体积限额、路径白名单、压缩比/数量限制，拒绝符号链接与目录穿越；遇到无法识别的文件或密码 ZIP 必须报告而非尝试破解。

## 3. 三层数据表示
1. **Raw**：原始 ZIP/json/音频，SHA-256，永久只读。
2. **IR v1**：`beat_map`、`notes`、`judge_lines`、`events`、`metadata`；每个事件有稳定 `id`、`original_fields` / `raw_payload` 和 `source_path`。存 beat rational（如 7+1/3），秒数可作为派生值缓存；不要直接把所有拍数变成 2 位小数。
3. **Model tokens**：小节/片段边界、audio embeddings 索引、note 时间/类型/位置/所属线、line 运动与父子层级；**tokens 不是导出格式**。

转换须保留未知 RPE 字段；若某特性不能被解释/渲染，应 `unsupported_features` 记录并保持 raw 用于 round-trip；不允许假装模型已支持。

## 4. RPE 已知核心事实（实施前重新核对当前版本）
- 根目录典型包含 `BPMList`、`META`、`judgeLineList`。
- RPE `note.type`: **1 Tap、2 Hold、3 Flick、4 Drag**，并不是 Tap/Drag/Hold/Flick 顺序。
- `startTime/endTime` 是三元数组的拍子表示；`positionX` 相对判定线。
- 判定线有 `father`、`eventLayers`、`extended`、`notes` 等，常见事件 `moveXEvents`、`moveYEvents`、`rotateEvents`、`alphaEvents`、`speedEvents`，且支持多层、缓动。
- `META.offset` 单位毫秒；Phira `info.yml.offset` 单位秒。**两者不可无条件相加，必须研究客户端使用哪一个并在 golden fixtures 和实际导入中核对正负方向**。
- Phira 本地谱面包为 ZIP，根目录 `info.yml` 与 `chart`、`music`、`illustration` 所引用的文件，应按当前文档填 `name`、`difficulty`、`level`、`charter`、`composer`、`illustrator`、`previewStart` 等。

## 5. 时间坐标，最重要的单元测试

IR 的 `beat` 采用全局有理数拍；若 BPM 段按升序边界 `(b_i, bpm_i)` 定义，则：

`base_time(b) = Σ_{完整段} (Δbeat * 60/bpm) + 当前段内 (b-b_k)*60/bpm_k`。

这个公式明确是 **60/BPM**，不是 BPM/60。对 `120 BPM`，1 拍为 `0.5 s`；对 `180 BPM`，1 拍为 `0.333...s`。多 BPM 必须分段积分。`bpmfactor`、局部判定线时标等必须先调查真实输入语义，避免重复缩放。

IR 使用明确两种时间：`chart_time_s`（谱面逻辑时间）与 `audio_time_s`（实际听到音乐的秒），由单独定义且经实机验证的 `time_mapping` 转换，所有页面共享。同一谱面在训练、审计、播放、导出使用同一个变换。查明 `info.yml.offset` 与 RPE META 的优先级/组合行为前，不得同时写非零值。

至少测试：单 BPM、多 BPM、非整数小节、拍分母、负拍（如有）、正负 offset、Hold 跨 BPM、父子线动画、实测音画同拍点击，以及不同格式转换的音符类型。

## 6. 谱面切片训练策略

先按音乐分组划分，再在各 split 内独立切片。建议以 **8 小节**为主片段、两侧附加上下文（例如各 2 小节），允许滑窗重叠，但评测应合并回整首后计算，避免重叠片段被当成独立样本刷高分。

不得把强行量化所有事件到 16 分音当作无损标准化；使用候选节拍网格 + 允许网格外事件（时间残差）以处理切分、不规则节奏、变 BPM 和复杂演出。

## 7. 导出契约

IR -> RPE 的 exporter 单元测试需比较：所有 Note 的类型/时间/持续/所属线/局部坐标，所有受支持 line 事件的时间/起终值/easing，父子拓扑，音乐对齐。然后打包 ZIP，再解包并重新解析为 IR，确认可重建。同样的测试还应在 **Phira 客户端**手动导入与试听通过后记录实机验证状态。

仅将已获得分发权限的音频/曲绘打包发布。仅供本人本地试听时也应遵守作品的许可条款，发布行为和本地研究是不同权限。

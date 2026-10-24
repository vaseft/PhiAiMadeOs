# 22｜LLM patch JSON 契约、哈希、防越权和校验顺序

## 服务端协议
1. 前端发起 `PostprocessRequest`，由服务器检查 API key 可用、用户已明确勾选外部上传、本地候选已冻结并取得 `base_version_id`。
2. 后端以 deterministic EvidenceBuilder 构造 `SegmentPayload`，将从基线 chart 计算出的 sha256 和片段 sha256 一并提交；同时以 Pydantic/JSON Schema 控制字段和最大长度。
3. provider 仅返回 `PostprocessProposal` 且 response_format=json_schema（服务商支持时）；失败时可退回严格 JSON 文本解析，**仍必须本地全量验证**。
4. Proposal 中 `request_id/chart_hash/segment_hash` 必须与输入逐字节一致。`status=no_change/insufficient_evidence` 时 patches 必须为空。
5. `AllowedOperationChecker` 根据实际模式、目标 runtime、editable IDs 和时间窗过滤。对所有 patch 的 payload 进行类型检查、非有限数禁用、范围约束；禁止逃逸路径、任意 JSON Pointer、额外未知字段。
6. 在 chart 原副本上先按 op_id 顺序试应用，防止相互覆盖/删除同一 Note；一次应用事务不可部分成功。使用新随机 ID 生成新增 Note 且保存映射；原件不可修改。
7. `ChartGeometryValidator`、`PlayabilityGuard`、`RoundtripExporterValidator` 全部重跑；硬失败直接回滚 v0，并向人工显示拒绝理由；有高风险 WARN 时 `apply_safe` 不自动接纳。
8. 进入正式独立非 AI 审计 `AUDITING`，之后才能进入 `READY_FOR_REVIEW`；人工可逐条采纳/驳回。

## patch payload 约定
- `MOVE_NOTE_TIME`: `{"new_start_beat": 33.125}`；目标现存音符 ID。
- `CHANGE_NOTE_KIND`: `{"new_kind": "FLICK"}`；不允许对/从 HOLD 缺失合法尾部信息。
- `MOVE_NOTE_X`: `{"new_x": 0.14}`；坐标系由候选 IR 和 renderer 声明，不能混用屏幕像素。
- `MOVE_NOTE_LANE`: `{"new_lane_index": 2}`；仅 pure_keys。
- `CHANGE_HOLD_END`: `{"new_end_beat": 34.5}`；仅 HOLD。
- `ADD_NOTE`: `{"kind": "TAP", "start_beat": 34.0, "line_id":"line_0", "x":0.1,"above":1,"is_fake":false}` 或纯配置附 `lane_index`；新 ID 由本地生成。
- `REMOVE_NOTE`: `{}`；需要特殊严格性。
- `TUNE_LINE_EVENT`: `{ "event_id": "ev11", "field": "easing", "new_value": 2 }`；必须是已验证的允许字段与运动值域，不能开放 arbitrary path。
- `SUGGEST_ONLY`: `{"topic":"manual_review"}`；纯人工建议。

## 时间、长度与不变量
- 音乐全谱 BPM map 和 offset 是只读权威值；beat 数采用兼容内部 IR 的有理数表示，服务端由 canonical converter 按 BPM map 验证，绝不可舍弃 offset。
- `editable_beat_window` 由服务端生成，不能由 LLM 自行扩大；Hold 可以跨段但必须保护其尾部数据，任何修改影响段外时要求人工授权。
- `pure_keys`：K 不变、静态线不变、lane 从 0 开始范围正确，动态速度/线事件修改禁止；特殊机制、噪域写入禁止。
- `regular/anomaly`：不允许移动到不存在的判定线、不允许父线循环、不允许 NaN/Inf 速度/坐标、负 Hold 长度。
- 客户端只消费合法事件；真实存储前必须 `to_ir → serialize_RPE/PEZ → parse_back → deterministic geometry parity`。
- 被拒绝的 patch 必须带 machine-readable error code；不允许默默按“AI建议”强行覆盖。

## schema 关系
`schemas/postprocess_request.schema.json`、`schemas/llm_segment_payload.schema.json`、`schemas/llm_postprocess_proposal.schema.json`、`schemas/llm_patch.schema.json`，另加现有 `schemas/chart_ir.schema.json`。所有 schema 标注为 V4 协议，严控 `additionalProperties=false`。

## 完整测试矩阵
1. 发送有效 payload → 空建议 → 没有更改版本。
2. 哈希错误/不存在 ID/窗口越界/多重冲突/重复 op_id/随机字段/NaN/超限 patch → 422 或 REJECTED。
3. pure_keys 中 TUNE_LINE_EVENT / 非法 lane / 修改 K / 添加噪域 → 拒绝。
4. regular/anomaly 中通过 schema 但破坏 Hold、判定线几何或导出 round-trip → 拒绝并回滚。
5. API 断网、超时、429、异常 JSON、收费预算触发 → 原本地候选仍可审阅。
6. Prompt injection：谱面名称含“忽略所有限制”、用户批注含 API key 请求、谱面 JSON 增加恶意 path → 只能输出允许字段，绝不执行外部操作。
7. 对比 LLM patch 前后已存在 hard error 数量；除非人工 override，不得让 error 数量增加。
8. 接受 patch 后验证正式 DSP 审计报告产生于新 chart_hash，并能展示旧版 vs 新版差异。

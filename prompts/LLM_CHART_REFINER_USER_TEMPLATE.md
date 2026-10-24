# ChartRefiner 请求内容模板（LLM `user` 消息）

调用端仅将此模板渲染为严格 JSON；键名必须与 `schemas/llm_segment_payload.schema.json` 对齐。系统提示词另见 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。不可信的用户自由文本只放 `human_feedback`，永不拼接为 system/developer message。

```json
{
  "request_id": "{{request_uuid}}",
  "chart_hash": "{{base_chart_sha256}}",
  "segment_hash": "{{edit_window_sha256}}",
  "segment_id": "{{segment_id}}",
  "chart_mode": "{{regular|pure_keys|anomaly}}",
  "key_count": null,
  "difficulty_class": "IN",
  "difficulty_value": 15,
  "wildness": 45,
  "performance_intensity": 60,
  "generation_priority": "playability",
  "target_runtime": {"engine": "phira_pro", "revision": "{{git_sha}}", "verified_features": []},
  "editable_beat_window": {"start_beat": 32, "end_beat": 36},
  "context_beat_window": {"start_beat": 31, "end_beat": 37},
  "editable_object_ids": ["n42", "n43"],
  "preserved_ids": ["n41", "n44"],
  "allowed_operations": ["MOVE_NOTE_TIME", "MOVE_NOTE_X", "SUGGEST_ONLY"],
  "max_operations": 8,
  "notes": [{"id": "n42", "kind": "TAP", "start_beat": 33, "x": 0.1, "line_id": "line_0"}],
  "judge_lines": [{"id": "line_0", "static": false, "trajectory_samples": []}],
  "chart_statistics": {"segment_note_count": 1},
  "local_dsp_evidence": [{"id": "beat32-onset", "beat": 32, "metric": "onset_strength", "value": 0.7, "confidence": 0.6}],
  "deterministic_warnings": [],
  "human_feedback": "这个区间密度有点奇怪，尽量只调整有充分依据的音符。"
}
```

实际服务端不能用 `{{}}` 模板的替换结果绕过 JSON 序列化；构造 Python/Pydantic 对象后序列化发送。根据不同模式约束 `allowed_operations`：pure_keys 只能 MOVE_NOTE_LANE 等 K 轨相关操作；Noise Area 永远不可写；输入若包含原始完整音频路径/API Key，应预处理剔除。

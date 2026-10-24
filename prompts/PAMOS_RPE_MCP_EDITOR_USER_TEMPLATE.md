# PAMOs RPE MCP Editor — User message template

以下为在用户明确使用 PAMOs RPE 编辑 MCP 时，由 PAMOs 客户端组装的输入模板。模板中的所有 `${...}` 必须由本地后端填充与验证；用户自由文本不具有高于 system 的权限。

```json
{
  "task_id": "${task_id}",
  "user_goal": "${human_request}",
  "project_id": "${project_id}",
  "session_id": "${session_id}",
  "chart_mode": "${regular_or_pure_keys_or_anomaly}",
  "key_count": "${integer_or_null}",
  "format_adapter": "${rpe_original_or_rpe_next}",
  "target_runtime": {"engine": "phira_pro", "pinned_revision": "${runtime_sha}"},
  "editable_beat_window": ["${startBeat}", "${endBeat}"],
  "desired_difficulty": "${difficulty}",
  "allowed_operations": ["${ops_by_server}"],
  "max_operations": "${policy_limit}",
  "do_not_modify": ["noise_areas", "blockAreaList", "BPMList", "META.offset", "score", "real_combo"],
  "audit_evidence_refs": ["${actual_evidence_ids}"],
  "external_audio_upload_authorized": false,
  "live_editor_expected": "${boolean}",
  "approval_authority": "PAMOs_UI_ONLY"
}
```

如果用户说“通过 RPE 直接把第 X 小节的谱面修改一下”，执行 read→propose→validate→preview→approval→commit，而不是直接使用 `editor.raw.chart` 或文件系统 write。

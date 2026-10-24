"""Training gates preserve human claims separately from source-bound evidence."""
ALIGNMENT_METHOD = "game_export_binding_v1"
GROUP_METHOD = "export_identity_audio_union_v1"


def alignment_ready(record, asset=None):
    if record.get("human_verified_alignment") is True:
        return True
    proof = record.get("alignment_evidence") or {}
    audio_sha = (asset or {}).get("sha256") or record.get("audio_sha256")
    chart_sha = record.get("chart_file_sha256") or record.get("sha256")
    original_sha = record.get("original_sha256") or record.get("source_chart_sha256")
    return bool(proof.get("method") == ALIGNMENT_METHOD and proof.get("status") == "source_metadata_consistent"
        and proof.get("source_export_user_confirmed") is True and chart_sha and original_sha and audio_sha
        and proof.get("chart_file_sha256") == chart_sha and proof.get("source_chart_sha256") == original_sha
        and proof.get("audio_sha256") == audio_sha and proof.get("music_asset_id") == record.get("music_asset_id"))


def training_group(record, asset=None):
    manual = record.get("group_id")
    if record.get("group_method") in (None, "human_song_cluster", "manual") and isinstance(manual, str) and manual.strip():
        return manual.strip()
    proof = record.get("group_evidence") or {}
    audio_sha = (asset or {}).get("sha256") or record.get("audio_sha256")
    group = record.get("training_group_id")
    if (isinstance(group, str) and group and proof.get("method") == GROUP_METHOD and proof.get("status") == "verified"
            and proof.get("group_id") == group and proof.get("audio_sha256") == audio_sha
            and proof.get("music_asset_id") == record.get("music_asset_id") and audio_sha):
        return group
    return None


def sample_for_chart(chart, asset, analysis, settings):
    if not alignment_ready(chart, asset):
        raise ValueError("训练需人工确认对齐，或与当前谱面/音频哈希绑定的游戏导出元数据核对记录")
    group = training_group(chart, asset)
    if not group:
        raise ValueError("训练需要人工歌曲簇或已核对的导出歌曲/音频联合分组，精确字节去重不足以代替")
    conditions = {key: chart.get(key) for key in ("chart_mode", "key_count", "difficulty_class", "difficulty_value")}
    pure = chart["chart_mode"] == "pure_keys"
    conditions.update({"performance_intensity": 0 if pure else chart.get("performance_intensity"),
        "performance_style": "none" if pure else chart.get("performance_style"), "wildness": chart.get("wildness"),
        "generation_priority": chart.get("generation_priority"), "special_features": [], "strict_playability": chart.get("strict_playability"),
        "source_level": {key: chart.get(key) for key in ("source_level", "source_difficulty_class", "source_difficulty_value")}})
    from .models import encode_conditions
    encode_conditions(conditions, training=True)
    return {"chart_id": chart["id"], "music_asset_id": asset["id"], "chart_path": chart["path"],
        "feature_path": settings.relative(analysis["feature_path"]), "audio_sha256": asset["sha256"], "music_sha256": asset["sha256"],
        "chart_sha256": chart["sha256"], "chart_file_sha256": chart["sha256"], "source_chart_sha256": chart.get("original_sha256"),
        "group_id": group, "training_group_id": chart.get("training_group_id"),
        "group_method": chart.get("group_method") if chart.get("group_method") in (None, "human_song_cluster", "manual") else GROUP_METHOD,
        "group_evidence": chart.get("group_evidence"), "alignment_evidence": chart.get("alignment_evidence"),
        "conditions": conditions, "license_status": chart["license_status"], "allowed_actions": list(chart["allowed_actions"]),
        "rights_evidence": chart.get("rights_evidence"), "feature_version": analysis["feature_version"], "analysis": analysis,
        "human_verified_alignment": chart.get("human_verified_alignment") is True, "source_type": chart.get("source_type"),
        "duration_s": analysis.get("duration_s")}

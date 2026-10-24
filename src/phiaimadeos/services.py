from __future__ import annotations
import json
import math
from pathlib import Path
from .settings import get_settings, atomic_json, file_hash, new_id, now
from .store import Store
from .formats import chart_hash, chart_to_ir, read_chart

LICENSES = {"explicit_permitted", "restricted", "unknown"}
ACTIONS = {"local_research", "training", "distribution"}
SCORE_LIMITS = {"rhythm": 25, "playability": 25, "readability": 20, "expression": 15, "difficulty": 10, "completeness": 5}


def rights(status, actions):
    if status not in LICENSES or not isinstance(actions, list) or not all(isinstance(a, str) for a in actions) or set(actions) - ACTIONS:
        raise ValueError("许可状态或用途无效")
    if "training" in actions and status != "explicit_permitted":
        raise ValueError("训练用途必须明确授权")
    if "distribution" in actions and status != "explicit_permitted":
        raise ValueError("分发用途必须明确授权")
    return {"license_status": status, "allowed_actions": sorted(set(actions))}


def load_candidate(candidate_id, store=None):
    store = store or Store()
    record = store.get("candidates", candidate_id)
    path = store.settings.path(record["chart_path"])
    if record.get("file_sha256") and file_hash(path) != record["file_sha256"]:
        raise ValueError("候选文件字节发生变化，已停止写操作")
    chart = json.loads(path.read_text(encoding="utf-8"))
    if chart_hash(chart) != record["chart_sha256"]:
        raise ValueError("候选文件与登记哈希不符，已停止写操作")
    return record, chart


def create_candidate(chart, conditions, music_asset_id=None, parent_id=None, source="baseline_only", manifest=None, store=None):
    store = store or Store()
    chart_to_ir(chart, conditions.get("chart_mode", "regular"), conditions.get("key_count"))
    identifier = new_id()
    path = store.settings.data_dir / "candidates" / identifier / "chart.json"
    atomic_json(path, chart)
    record = store.put("candidates", {
        "id": identifier, "music_asset_id": music_asset_id, "chart_mode": conditions.get("chart_mode", "regular"),
        "key_count": conditions.get("key_count"), "conditions": conditions, "parent_id": parent_id,
        "chart_path": store.settings.relative(path), "chart_sha256": chart_hash(chart), "file_sha256": file_hash(path), "status": "draft",
        "audit_id": None, "source": source, "manifest": {"source": source, "verification": "NOT RUN", **(manifest or {})},
    })
    store.event("candidate.created", identifier, parent_id=parent_id, chart_sha256=record["chart_sha256"], source=source)
    return record


def analysis_for(asset, progress=None, store=None):
    from .audio import analyze_audio
    store = store or Store()
    path = store.settings.path(asset["path"])
    if file_hash(path) != asset["sha256"]:
        raise ValueError("音乐源文件哈希不符")
    result = analyze_audio(path, store.settings.data_dir / "features", progress=progress)
    analysis_path = store.settings.data_dir / "features" / (asset["id"] + ".analysis.json")
    atomic_json(analysis_path, result)
    store.update("assets", asset["id"], {"analysis_path": store.settings.relative(analysis_path)})
    return result


def cached_analysis(asset, settings=None):
    settings = settings or get_settings()
    if asset.get("analysis_path"):
        path = settings.path(asset["analysis_path"])
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def export_audio(asset, store):
    """Normalize AAC containers for export, keeping the uploaded original read-only."""
    path = store.settings.path(asset["path"])
    if path.suffix.lower() not in {".aac", ".m4a"}:
        return path
    import shutil
    import subprocess
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("AAC/M4A 打包需要本机 FFmpeg 转为 FLAC")
    target = store.settings.data_dir / "exports" / (new_id() + ".flac")
    try:
        result = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:a:0", "-vn", "-c:a", "flac", "-n", str(target)], capture_output=True, timeout=300)
        if result.returncode or not target.is_file():
            raise ValueError("AAC/M4A 转换失败，原始音乐未修改")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def run_audit(candidate_id, analysis=None, store=None):
    from .audit import audit_chart
    store = store or Store()
    candidate, chart = load_candidate(candidate_id, store)
    if analysis is None and candidate.get("music_asset_id"):
        analysis = cached_analysis(store.get("assets", candidate["music_asset_id"]), store.settings)
    report = audit_chart(chart, analysis, candidate["conditions"])
    report.update({"id": new_id(), "candidate_id": candidate_id, "chart_sha256": candidate["chart_sha256"], "created_at": now()})
    store.put("audits", report, immutable=True)
    store.update("candidates", candidate_id, {"audit_id": report["id"], "status": "blocked" if report["status"] == "BLOCK" else "awaiting_review", "review_id": None})
    return report


def reviewed(candidate_id, store=None):
    store = store or Store()
    candidate, chart = load_candidate(candidate_id, store)
    if not candidate.get("audit_id") or not candidate.get("review_id"):
        raise ValueError("需要当前版本的独立审计与人工通过记录")
    audit = store.get("audits", candidate["audit_id"])
    review = store.get("reviews", candidate["review_id"])
    if audit["chart_sha256"] != candidate["chart_sha256"] or audit["status"] == "BLOCK":
        raise ValueError("审计版本不匹配或存在阻断问题")
    if review["chart_sha256"] != candidate["chart_sha256"] or review["decision"] != "approved" or candidate["status"] != "approved":
        raise ValueError("当前谱面尚未人工通过")
    return candidate, chart


def record_review(candidate_id, payload, store=None):
    store = store or Store()
    candidate, _ = load_candidate(candidate_id, store)
    reviewer = str(payload.get("reviewer", "")).strip()
    if not reviewer or len(reviewer) > 120:
        raise ValueError("请填写审核人")
    scores = payload.get("scores", {})
    if set(scores) != set(SCORE_LIMITS):
        raise ValueError("请由审核人填写全部六项评分")
    for key, maximum in SCORE_LIMITS.items():
        v = scores[key]
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 <= v <= maximum:
            raise ValueError(f"{key} 必须在 0..{maximum} 之间")
    decision = payload.get("decision")
    if decision not in {"approved", "revision_requested", "rejected"}:
        raise ValueError("审核决定无效")
    annotations = payload.get("annotations", [])
    if len(annotations) > 300:
        raise ValueError("标注过多")
    for annotation in annotations:
        if not isinstance(annotation.get("time_s"), (float, int)) or not math.isfinite(annotation["time_s"]) or annotation["time_s"] < 0 or not str(annotation.get("text", "")).strip():
            raise ValueError("标注需要有效时间与文字")
    if decision == "approved":
        if not candidate.get("audit_id"):
            raise ValueError("请先执行独立审计")
        audit = store.get("audits", candidate["audit_id"])
        if audit["status"] == "BLOCK" or audit["chart_sha256"] != candidate["chart_sha256"]:
            raise ValueError("当前审计阻断通过")
    review = store.put("reviews", {"candidate_id": candidate_id, "chart_sha256": candidate["chart_sha256"], "reviewer": reviewer,
        "scores": scores, "total": sum(scores.values()), "decision": decision, "comment": str(payload.get("comment", ""))[:10000], "annotations": annotations}, immutable=True)
    store.update("candidates", candidate_id, {"review_id": review["id"], "status": decision})
    store.event("review.recorded", candidate_id, review_id=review["id"], decision=decision)
    return review


def family_history(candidate_id, store=None):
    store = store or Store()
    all_versions = store.list("candidates")
    by_id = {v["id"]: v for v in all_versions}
    root = candidate_id
    seen = set()
    while by_id.get(root, {}).get("parent_id") and root not in seen:
        seen.add(root)
        root = by_id[root]["parent_id"]
    family = {root}
    while True:
        next_ids = {v["id"] for v in all_versions if v.get("parent_id") in family}
        if next_ids <= family:
            break
        family |= next_ids
    return {"versions": [v for v in all_versions if v["id"] in family], **{
        kind: [r for r in store.list(kind) if r.get("candidate_id") in family] for kind in ("reviews", "playtests", "proposals")}}

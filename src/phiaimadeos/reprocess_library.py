"""Versioned repair of explicitly imported resource/timing-limited charts."""
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zipfile

from .formats import _json, _archive_members, _preflight_zip, canonical_bytes, chart_hash, chart_to_ir, MAX_JSON_BYTES
from .library_import import _metadata, _write_new
from .official import convert_official, MAPPING_VERSION
from .settings import atomic_json, file_hash, new_id, now
from .store import Store

REPAIR_REASONS = ("JSON 嵌套", "原始 JSON 超过", "原生音符/事件数量", "转换后事件超过", "反向事件", "非单调关键帧", "流速起点未递增")


def _eligible(record):
    return record.get("source_archive_sha256") and record.get("import_status") == "archived_only" and any(
        marker in warning for warning in record.get("warnings", []) for marker in REPAIR_REASONS)


def _reprocess_one(previous, run_id, store):
    settings = store.settings
    original = settings.path(previous["original_path"])
    raw = original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != previous["original_sha256"]:
        raise ValueError("只读原谱哈希发生变化，拒绝补处理")
    native = _json(raw)
    del raw
    archive_path = Path(previous["source_archive_path"])
    before = archive_path.stat()
    if file_hash(archive_path) != previous["source_archive_sha256"]:
        raise ValueError("原始压缩包哈希变化，拒绝读取新配置覆盖旧版本")
    _preflight_zip(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        members = _archive_members(archive)
        _, info = _metadata(archive, members)
        csv_config = "line.csv" in members or info.get("_pamos_metadata_format") == "csv"
    source_format = previous.get("source_format", "unknown")
    converted = None
    error = None
    ir = None
    try:
        if "formatVersion" in native:
            source_format = "phigros_v" + str(native["formatVersion"])
        elif all(key in native for key in ("META", "BPMList", "judgeLineList")):
            source_format = "rpe"
        else:
            raise ValueError("未识别 JSON 谱面方言")
        if csv_config:
            raise ValueError("外置 CSV 全局/判定线图片配置尚未映射；原件只读保留")
        if source_format == "rpe":
            converted = native
            converted["_pamos_import"] = {"container": "zip", "info_format": "yaml", "info": info, "warnings": []}
        else:
            converted = convert_official(native, info)
        ir = chart_to_ir(converted, previous["chart_mode"], previous.get("key_count"), copy_raw=False)
        if previous.get("music_asset_id"):
            converted.setdefault("pamos", {})["duration_s"] = store.get("assets", previous["music_asset_id"])["duration_s"]
        data = canonical_bytes(converted)
        if len(data) > MAX_JSON_BYTES:
            raise ValueError(f"完整转换结果超过{MAX_JSON_BYTES // 1024**2} MiB有界处理上限；未截断")
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        converted, error = None, str(exc)
    after = archive_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("读取期间原包发生变化，未登记结果")
    history = list(previous.get("import_history", []))
    history.append({"at": now(), "path": previous["path"], "sha256": previous["sha256"], "candidate_id": previous.get("candidate_id"),
        "status": previous["import_status"], "warnings": previous.get("warnings", []), "run_id": previous.get("import_run_id")})
    changes = {"source_format": source_format, "reprocess_run_id": run_id, "mapping_version": MAPPING_VERSION,
        "import_history": history, "conversion_error": error}
    expected = {key: previous.get(key) for key in ("sha256", "candidate_id", "updated_at", "import_status")}
    path = None
    try:
        if converted is None:
            changes["warnings"] = [error, "原谱与媒体保持只读存档；未授权训练/分发，未确认对齐或试玩"]
            store.revise_import(previous["id"], expected, changes)
            return {"chart_id": previous["id"], "status": "archived_only", "reason": error}
        identifier = new_id()
        path = settings.data_dir / "charts" / previous["id"] / "revisions" / identifier / "chart.json"
        _write_new(path, data)
        digest = file_hash(path)
        conditions = {key: previous.get(key) for key in ("chart_mode", "key_count", "difficulty_class", "difficulty_value")}
        candidate = {"id": identifier, "music_asset_id": previous.get("music_asset_id"), "chart_mode": previous["chart_mode"],
            "key_count": previous.get("key_count"), "conditions": conditions, "chart_path": settings.relative(path), "chart_sha256": chart_hash(converted),
            "file_sha256": digest, "status": "draft", "parent_id": previous.get("candidate_id"), "audit_id": None, "source": "official_import_reprocess",
            "manifest": {"source": "official_import_reprocess", "chart_asset_id": previous["id"], "source_chart_sha256": previous["original_sha256"],
                "source_archive_sha256": previous["source_archive_sha256"], "reprocess_run_id": run_id, "mapping_version": MAPPING_VERSION,
                "verification": "NOT RUN", "conversion_limits": converted.get("pamos", {}).get("compatibility_limits", [])}}
        changes.update({"path": settings.relative(path), "sha256": digest, "import_status": "ready", "candidate_id": identifier,
            "warnings": list(dict.fromkeys(ir["warnings"] + converted.get("pamos", {}).get("compatibility_limits", []) +
                ["只读原谱未改；训练/分发许可和人工对齐不因补处理改变"]))})
        store.revise_import(previous["id"], expected, changes, candidate)
        return {"chart_id": previous["id"], "status": "ready", "candidate_id": identifier, "bytes": len(data),
            "source_events": converted.get("pamos", {}).get("source_event_count"), "converted_events": converted.get("pamos", {}).get("converted_event_count")}
    except BaseException:
        if path is not None and path.is_file() and path.resolve().is_relative_to(settings.data_dir.resolve()):
            # Registration is the last fallible operation; this only removes a
            # new file when its transaction did not commit.
            path.unlink(missing_ok=True)
        raise


def reprocess_library(progress=None):
    store = Store()
    if any(job["status"] in {"queued", "running", "cancelling"} for job in store.list("jobs")):
        raise ValueError("请先等待当前任务结束，再补处理本地谱面")
    selected = [record for record in store.list("charts") if _eligible(record)]
    run_id = "reprocess-" + new_id()
    folder = store.settings.data_dir / "imports" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(store.settings.db_path) as source, sqlite3.connect(folder / "database-before.sqlite3") as target:
        source.backup(target)
    store.put("jobs", {"id": run_id, "kind": "library_reprocess", "request": {"scope": "registered_resource_timing_limits"},
        "status": "running", "progress": 0, "started_at": now(), "message": f"准备补处理{len(selected)}份容量/时序受限谱面"})
    report = {"id": run_id, "created_at": now(), "total": len(selected), "items": [], "source_files_modified": False,
        "tests": "NOT RUN", "training": "NOT RUN", "client_playtest": "NOT RUN", "mapping_version": MAPPING_VERSION}
    counts = Counter()
    start = time.monotonic()
    try:
        for index, previous in enumerate(selected):
            if store.get("jobs", run_id)["status"] != "running":
                break
            try:
                result = _reprocess_one(previous, run_id, store)
            except Exception as exc:
                result = {"chart_id": previous["id"], "status": "failed", "reason": str(exc)[:2000]}
            report["items"].append(result)
            counts[result["status"]] += 1
            summary = {"total": len(selected), "processed": index + 1, **dict(counts)}
            store.update("jobs", run_id, {"progress": (index + 1) / max(1, len(selected)), "result": summary,
                "message": f"补处理{index + 1}/{len(selected)}；新预览{counts['ready']}，仍存档{counts['archived_only']}，失败{counts['failed']}"})
            atomic_json(folder / "report.json", report)
            gc.collect()
            if progress:
                progress(summary)
        state = store.get("jobs", run_id)["status"]
        state = ("succeeded" if not counts["failed"] else "partial") if state == "running" else "cancelled"
        report.update(status=state, counts=dict(counts), elapsed_s=round(time.monotonic() - start, 2), finished_at=now())
        atomic_json(folder / "report.json", report)
        store.update("jobs", run_id, {"status": state, "finished_at": now(), "progress": len(report["items"]) / max(1, len(selected)),
            "result": {"reprocess_run_id": run_id, **dict(counts), "report_path": store.settings.relative(folder / "report.json")}, "message": "补处理结束；原件/权限/历史保留，试玩仍待确认"})
        return report
    except BaseException as exc:
        report.update(status="interrupted", error=str(exc)[:2000], counts=dict(counts), finished_at=now())
        atomic_json(folder / "report.json", report)
        store.update("jobs", run_id, {"status": "interrupted", "error": str(exc)[:1000], "finished_at": now()})
        raise

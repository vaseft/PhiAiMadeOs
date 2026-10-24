"""Explicit local, resumable CPU DSP preparation for registered audio assets."""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import time

from .audio import FEATURE_VERSION
from .services import analysis_for
from .settings import atomic_json, new_id, now
from .store import Store


class PreparationCancelled(Exception):
    """Stop between bounded decoding blocks, retaining all completed caches."""


def prepare_audio_features(*, asset_ids=None, progress=None, store=None):
    """Prepare registered local assets only; never change charts or permissions.

    The callback receives anonymous summaries. Detailed per-asset information is
    saved only in the ignored local report. Reruns validate and reuse the current
    extractor's audio/feature/waveform hashes before registering analysis paths.
    """
    store = store or Store()
    settings = store.settings
    assets = sorted(store.list("assets"), key=lambda item: item["id"])
    if asset_ids is not None:
        wanted = set(asset_ids)
        assets = [item for item in assets if item["id"] in wanted]
        if {item["id"] for item in assets} != wanted:
            raise ValueError("指定的音频素材不存在")
    if not assets:
        raise ValueError("本地素材库没有待提取的音频")
    identifier = new_id()
    # Claim the external CLI job atomically so two preparation CLIs cannot race.
    timestamp = now()
    job = {"id": identifier, "kind": "audio_prepare", "status": "running", "progress": 0,
           "request": {"asset_count": len(assets), "feature_version": FEATURE_VERSION},
           "message": f"准备逐曲提取 {len(assets)} 份本地音频的 CPU DSP 特征",
           "started_at": timestamp, "created_at": timestamp, "updated_at": timestamp,
           "pid": os.getpid(), "result": None, "error": None}
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        active = db.execute("SELECT payload FROM records WHERE kind='jobs'").fetchall()
        if any((value := json.loads(row[0])).get("kind") == "audio_prepare"
               and value.get("status") in {"queued", "running", "cancelling"} for row in active):
            raise ValueError("已有批量音频特征任务，请等待完成或取消后重跑")
        db.execute("INSERT INTO records VALUES (?,?,?,?,?,?)",
                   ("jobs", identifier, store.encode(job), 0, timestamp, timestamp))
    directory = settings.data_dir / "audio_preparation" / identifier
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        store.update("jobs", identifier, {"status": "failed", "error": str(exc)[:1000], "finished_at": now()})
        raise
    report_path = directory / "report.json"
    report = {"id": identifier, "started_at": timestamp, "total": len(assets), "items": [],
              "feature_version": FEATURE_VERSION, "device": "cpu", "source_files_modified": False,
              "permissions_changed": False, "alignment_confirmed": False, "tests": "NOT RUN"}
    counts = Counter()
    started = time.monotonic()
    last_heartbeat = 0.0
    processed = 0

    def emit(value):
        if progress:
            progress(value)

    def check_cancel():
        if store.get("jobs", identifier)["status"] != "running":
            raise PreparationCancelled("任务已取消或中断；已完成曲目的缓存保留，可重跑续作")

    def checkpoint():
        report.update(processed=processed, counts=dict(counts), elapsed_s=round(time.monotonic() - started, 2))
        atomic_json(report_path, report, compact=True)

    try:
        emit({"job_id": identifier, "total": len(assets), "processed": 0, "message": job["message"]})
        # The database backup is local and consistent with concurrent WAL writers.
        with store.connection() as source, sqlite3.connect(directory / "database-before.sqlite3") as destination:
            source.backup(destination)
        checkpoint()
        for index, asset in enumerate(assets):
            check_cancel()
            item_started = time.monotonic()
            cached = False

            def song_progress(fraction, message):
                nonlocal last_heartbeat, cached
                current = time.monotonic()
                if fraction >= 1 and "缓存" in message:
                    cached = True
                if current - last_heartbeat >= 2 or fraction >= 1:
                    check_cancel()
                    store.update("jobs", identifier, {"progress": (index + min(1., max(0., fraction))) / len(assets),
                        "message": f"音频 {index + 1}/{len(assets)}：{message}",
                        "result": {"total": len(assets), "processed": processed, **dict(counts)}})
                    last_heartbeat = current
                if current - getattr(song_progress, "last_output", 0) >= 10:
                    emit({"job_id": identifier, "total": len(assets), "processed": processed,
                          "current": index + 1, "current_progress": round(fraction, 3), "message": message})
                    song_progress.last_output = current

            try:
                if "local_research" not in asset.get("allowed_actions", []):
                    raise ValueError("此音频尚未获准本机研究分析")
                analysis = analysis_for(asset, song_progress, store)
                state = "cached" if cached else "prepared"
                item = {"asset_id": asset["id"], "audio_sha256": analysis["audio_sha256"], "status": state,
                        "duration_s": analysis["duration_s"], "feature_sha256": analysis["feature_sha256"],
                        "analysis_path": settings.relative(settings.data_dir / "features" / (asset["id"] + ".analysis.json")),
                        "feature_bytes": Path(analysis["feature_path"]).stat().st_size,
                        "feature_frames": analysis["feature_frames"],
                        "tempo_status": analysis["tempo"]["status"], "elapsed_s": round(time.monotonic() - item_started, 3)}
                counts[state] += 1
            except PreparationCancelled:
                raise
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                item = {"asset_id": asset["id"], "status": "failed", "error": str(exc)[:2000],
                        "elapsed_s": round(time.monotonic() - item_started, 3)}
                counts["failed"] += 1
            report["items"].append(item)
            processed += 1
            summary = {"job_id": identifier, "total": len(assets), "processed": processed, **dict(counts),
                       "last_status": item["status"], "last_elapsed_s": item["elapsed_s"],
                       "elapsed_s": round(time.monotonic() - started, 2)}
            store.update("jobs", identifier, {"progress": processed / len(assets), "result": summary,
                "message": f"CPU 特征已处理 {processed}/{len(assets)}，失败 {counts['failed']}"})
            checkpoint()
            emit(summary)
        report.update(status="partial" if counts["failed"] else "succeeded", finished_at=now())
    except (PreparationCancelled, KeyboardInterrupt) as exc:
        report.update(status="cancelled", finished_at=now(), error=str(exc))
    except BaseException as exc:
        report.update(status="failed", finished_at=now(), error=str(exc)[:2000])
        raise
    finally:
        checkpoint()
        result = {"preparation_id": identifier, "total": len(assets), "processed": processed, **dict(counts),
                  "report_path": settings.relative(report_path), "elapsed_s": report["elapsed_s"]}
        store.update("jobs", identifier, {"status": report.get("status", "failed"), "finished_at": now(),
            "result": result, "error": report.get("error"),
            "message": "CPU 音频特征处理结束；未修改原件、许可或人工对齐状态"})
        store.event("audio.features_prepared", identifier, **dict(counts), source_files_modified=False)
    return report

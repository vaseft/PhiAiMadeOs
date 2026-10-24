"""Prepare source-attested local data, with explicit machine/human provenance."""
from collections import Counter, defaultdict
import copy
import gc
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import unicodedata
from types import SimpleNamespace

from .formats import read_chart, chart_to_ir
from .settings import atomic_json, file_hash, new_id, now
from .store import Store
from .training_readiness import ALIGNMENT_METHOD, GROUP_METHOD, sample_for_chart

PROFILE = "game-export-training-v2-64lines"


def _analysis(asset, settings):
    if not asset.get("analysis_path"):
        raise ValueError("音频特征尚未准备")
    value = json.loads(settings.path(asset["analysis_path"]).read_text(encoding="utf-8"))
    if value.get("audio_sha256") != asset["sha256"]:
        raise ValueError("音频特征与素材哈希不符")
    for field, digest in (("feature_path", "feature_sha256"), ("waveform_path", "waveform_sha256")):
        if file_hash(settings.path(value[field])) != value.get(digest):
            raise ValueError("音频缓存内容发生变化")
    return value


def _group_assets(assets, charts, settings):
    import numpy as np
    from scipy import signal
    ids = sorted(assets)
    parents = {identifier: identifier for identifier in ids}
    links = []
    def find(identifier):
        while parents[identifier] != identifier:
            parents[identifier] = parents[parents[identifier]]
            identifier = parents[identifier]
        return identifier
    def union(a, b, reason, score=None):
        first, second = find(a), find(b)
        if first != second:
            parents[max(first, second)] = min(first, second)
            links.append({"first": a, "second": b, "reason": reason, "similarity": score})
    by_title = {}
    by_hash = {}
    for identifier, asset in assets.items():
        if asset["sha256"] in by_hash:
            union(identifier, by_hash[asset["sha256"]], "exact_audio_sha256")
        by_hash[asset["sha256"]] = identifier
    for chart in charts:
        identifier = chart.get("music_asset_id")
        if identifier not in assets:
            continue
        title = " ".join(unicodedata.normalize("NFKC", chart.get("name", "")).casefold().split())
        if len(title) < 3 or title in {"unknown", "untitled", "phigros"}:
            continue
        key = hashlib.sha256(title.encode("utf-8")).hexdigest()
        if key in by_title:
            union(identifier, by_title[key], "same_game_export_title")
        by_title[key] = identifier
    fingerprints = {}
    for identifier in ids:
        analysis = _analysis(assets[identifier], settings)
        values = np.load(settings.path(analysis["feature_path"]), mmap_mode="r", allow_pickle=False)
        # Two-second ordered chroma cells allow strict full/cropped matching.
        chunks = [np.asarray(values[start:start + 50, 80:92]).mean(axis=0) for start in range(0, len(values), 50)]
        cells = np.asarray(chunks, dtype=np.float64)
        norms = np.linalg.norm(cells, axis=1, keepdims=True)
        cells = cells / np.maximum(norms, 1e-12)
        mean = cells.mean(axis=0)
        fingerprints[identifier] = (cells, mean / max(float(np.linalg.norm(mean)), 1e-12))
        del values
    for index, first in enumerate(ids):
        a, ma = fingerprints[first]
        for second in ids[index + 1:]:
            if find(first) == find(second):
                continue
            b, mb = fingerprints[second]
            if min(len(a), len(b)) < 20 or float(ma @ mb) < 0.96:
                continue
            long, short = (a, b) if len(a) >= len(b) else (b, a)
            # This is similarity evidence, never a confidence/quality score.
            scores = signal.correlate(long, short, mode="valid", method="fft")[:, 0] / len(short)
            score = float(np.max(scores))
            if score >= 0.992:
                union(first, second, "ordered_chroma_crop_match", score)
    groups = {identifier: "song-export:" + hashlib.sha256(find(identifier).encode()).hexdigest()[:32] for identifier in ids}
    return groups, links


def _register_dataset(store, manifest):
    path = store.settings.path(manifest["manifest_path"])
    summary = {key: manifest.get(key) for key in ("version", "group_count", "split_counts", "feature_version", "split_version")}
    return store.put("datasets", {"id": manifest["id"], "manifest_path": manifest["manifest_path"], "sha256": file_hash(path),
        "sample_count": len(manifest["samples"]), "manifest": summary, "version": manifest["version"],
        "group_count": manifest["group_count"], "split_counts": manifest["split_counts"], "feature_version": manifest["feature_version"]}, immutable=True)


def _initial_subset(full, store, inventory, maximum=24):
    from ._model_data import canonical_hash
    selected = []
    seen = set()
    # Hold-out assignments come from the full corpus and never change here.
    for split, quota in (("train", maximum - 6), ("val", 4), ("test", 2)):
        rows = sorted((row for row in full["samples"] if row["split"] == split),
            key=lambda row: (inventory[row["chart_id"]]["windows"], inventory[row["chart_id"]]["events"], inventory[row["chart_id"]]["notes"]))
        for row in rows:
            if row["group_id"] in seen:
                continue
            selected.append(copy.deepcopy(row)); seen.add(row["group_id"])
            if sum(item["split"] == split for item in selected) >= quota:
                break
    if not all(any(row["split"] == split for row in selected) for split in ("train", "val")):
        raise ValueError("初训缺少独立训练/验证歌曲簇")
    identifier = new_id()
    subset = {key: copy.deepcopy(value) for key, value in full.items() if key not in {"id", "samples", "sha256", "manifest_path"}}
    subset.update(id=identifier, created_at=now(), samples=selected, group_count=len(seen),
        split_counts={split: sum(row["split"] == split for row in selected) for split in ("train", "val", "test")},
        parent_manifest_sha256=full["sha256"], selection_policy="low-complexity-complete-songs-preserve-global-splits")
    subset["sha256"] = canonical_hash(subset)
    path = store.settings.data_dir / "datasets" / identifier / ("manifest-" + identifier + ".json")
    subset["manifest_path"] = store.settings.relative(path)
    atomic_json(path, subset, compact=True)
    return subset


def prepare_training(*, user_training_permission=False, game_export_declared=False, progress=None):
    if user_training_permission is not True or game_export_declared is not True:
        raise ValueError("准备入口需用户明确训练授权及游戏导出来源声明，不能从下载动作推断")
    store = Store(); settings = store.settings
    if any(job.get("status") in {"running", "queued", "cancelling"} for job in store.list("jobs")):
        raise ValueError("请先等待当前任务完成")
    run_id = new_id(); folder = settings.data_dir / "training_preparation" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(settings.db_path) as source, sqlite3.connect(folder / "database-before.sqlite3") as target:
        source.backup(target)
    attestation = {"id": run_id, "method": "user_attested", "at": now(), "scope": "current_local_game_export_music_and_charts_local_model_training",
        "user_permission_statement": "已有明确授权，可说明来源与范围", "user_origin_statement": "官方谱面均为游戏里导出",
        "independent_license_verification": False, "distribution_permission": False}
    atomic_json(folder / "user-attestation.json", attestation)
    store.put("jobs", {"id": run_id, "kind": "dataset_prepare", "request": {"profile": PROFILE}, "status": "running", "progress": 0,
        "started_at": now(), "message": "登记用户授权并核对游戏导出来源"})
    all_charts = store.list("charts"); assets = {row["id"]: row for row in store.list("assets")}
    report = {"id": run_id, "profile": PROFILE, "created_at": now(), "human_listening_claimed": False, "items": [], "tests": "NOT RUN"}
    counts = Counter(); samples = []; inventory = {}; start = time.monotonic()
    try:
        # The explicit user statement applies to this already imported batch.
        for kind, rows in (("assets", list(assets.values())), ("charts", all_charts)):
            for row in rows:
                changes = {"license_status": "explicit_permitted", "allowed_actions": sorted(set(row.get("allowed_actions", [])) | {"local_research", "training"}),
                    "rights_evidence": attestation}
                store.update(kind, row["id"], changes, expected={"updated_at": row["updated_at"]})
                row.update(changes)
        store.event("training.rights_attested", run_id, asset_count=len(assets), chart_count=len(all_charts), allowed_action="local_training", human_alignment_claimed=False)
        groups, links = _group_assets(assets, all_charts, settings)
        atomic_json(folder / "song-groups.json", {"method": GROUP_METHOD, "links": links, "asset_groups": groups,
            "limitations": "Ordered chroma is conservative near-duplicate evidence, not an independent source or perceptual alignment certificate."})
        charts = [row for row in all_charts if row.get("import_status") == "ready"]
        from ._model_data import load_song, build_windows
        for index, chart in enumerate(charts):
            if store.get("jobs", run_id)["status"] != "running":
                raise KeyboardInterrupt("用户取消数据准备")
            changes = {}
            try:
                asset = assets[chart["music_asset_id"]]
                analysis = _analysis(asset, settings)
                if file_hash(settings.path(chart["path"])) != chart["sha256"] or file_hash(settings.path(chart["original_path"])) != chart["original_sha256"]:
                    raise ValueError("原谱或转换候选哈希变化")
                parsed = read_chart(settings.path(chart["path"]))
                ir = chart_to_ir(parsed, chart["chart_mode"], chart.get("key_count"), copy_raw=False)
                native = json.loads(settings.path(chart["original_path"]).read_bytes())
                source_offset = float(chart.get("source_info", {}).get("offset", 0))
                expected_offset = (float(native.get("offset", 0)) if "formatVersion" in native else float(native["META"].get("offset", 0)) / 1000) + source_offset
                actual_offset = ir["offset_ms"] / 1000 + ir.get("info_offset_s", 0)
                if not math.isfinite(expected_offset) or abs(expected_offset - actual_offset) > 1e-6:
                    raise ValueError("游戏导出offset与转换时钟不一致，需单独核对")
                duration = analysis["duration_s"]
                if any(note["time_s"] < -1e-6 or note["end_time_s"] > duration + 0.04 for note in ir["notes"]):
                    raise ValueError("音符时间超出绑定音频，不能自动宣布对齐")
                proof = {"method": ALIGNMENT_METHOD, "status": "source_metadata_consistent", "source_export_user_confirmed": True,
                    "at": now(), "chart_file_sha256": chart["sha256"], "source_chart_sha256": chart["original_sha256"],
                    "audio_sha256": asset["sha256"], "music_asset_id": asset["id"], "offset_s": actual_offset,
                    "duration_s": duration, "note_range_checked": True, "human_listening": False,
                    "limitation": "Source binding and clock consistency only; not human/perceptual sync confirmation."}
                grouping = {"method": GROUP_METHOD, "status": "verified", "group_id": groups[asset["id"]], "audio_sha256": asset["sha256"],
                    "music_asset_id": asset["id"], "report_id": run_id}
                changes.update(alignment_evidence=proof, training_group_id=groups[asset["id"]], group_evidence=grouping)
                value = {**chart, **changes}
                sample = sample_for_chart(value, asset, analysis, settings)
                events = sum(len(track) for line in parsed["judgeLineList"] for layer in line.get("eventLayers", []) if isinstance(layer, dict) for track in layer.values() if isinstance(track, list))
                inventory[chart["id"]] = {"events": events, "notes": len(ir["notes"]), "lines": len(ir["judge_lines"])}
                del native, ir, parsed
                song = load_song(settings.root, sample, max_lines=64)
                atomic_json(folder / "projections" / (chart["id"] + ".json"), song["training_projection"], compact=True)
                # Inspect every complete song before allocating it to a split.
                # This only prepares real targets; it never trains on hold-outs.
                windows, window_report = build_windows(SimpleNamespace(samples=[{**sample, "split": "preparation"}],
                    get=lambda _: song, max_lines=64))
                inventory[chart["id"]].update(windows=len(windows), additional_splits=window_report[0]["additional_splits"])
                del windows, window_report
                del song
                samples.append(sample)
                changes["training_readiness"] = {"status": "ready", "reasons": [], "profile_version": PROFILE, "run_id": run_id, **inventory[chart["id"]]}
                result = {"chart_id": chart["id"], "status": "ready", **inventory[chart["id"]]}
            except Exception as exc:
                reason = str(exc)[:2000]
                changes["training_readiness"] = {"status": "blocked", "reasons": [reason], "profile_version": PROFILE, "run_id": run_id}
                result = {"chart_id": chart["id"], "status": "blocked", "reason": reason}
            store.update("charts", chart["id"], changes, expected={key: chart.get(key) for key in
                ("sha256", "music_asset_id", "chart_mode", "key_count", "difficulty_class", "difficulty_value", "group_id", "group_method")})
            report["items"].append(result); counts[result["status"]] += 1
            summary = {"total": len(charts), "processed": index + 1, **dict(counts)}
            store.update("jobs", run_id, {"progress": (index + 1) / len(charts) * 0.9, "message": f"逐谱训练适配{index + 1}/{len(charts)}", "result": summary})
            atomic_json(folder / "report.json", report)
            gc.collect()
            if progress:
                progress(summary)
        from .dataset import build_manifest
        corpus_id = new_id()
        corpus = build_manifest(samples, settings.data_dir / "datasets" / corpus_id, seed=42)
        corpus_record = _register_dataset(store, corpus)
        initial = _initial_subset(corpus, store, inventory)
        initial_record = _register_dataset(store, initial)
        report.update(status="succeeded", counts=dict(counts), finished_at=now(), elapsed_s=round(time.monotonic() - start, 2),
            corpus_dataset_id=corpus_record["id"], initial_dataset_id=initial_record["id"],
            corpus_samples=len(corpus["samples"]), corpus_groups=corpus["group_count"], initial_samples=len(initial["samples"]), initial_splits=initial["split_counts"])
        atomic_json(folder / "report.json", report)
        store.update("jobs", run_id, {"status": "succeeded", "progress": 1, "finished_at": now(), "result": {key: value for key, value in report.items() if key != "items"}, "message": "训练数据准备完成；原件与人工听音字段未改"})
        return report
    except BaseException as exc:
        state = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
        report.update(status=state, error=str(exc)[:2000], counts=dict(counts), finished_at=now())
        atomic_json(folder / "report.json", report)
        store.update("jobs", run_id, {"status": state, "error": str(exc)[:2000], "finished_at": now(), "message": "准备中断，已完成缓存和资料保留"})
        raise

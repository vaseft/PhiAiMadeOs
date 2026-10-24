from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import traceback
from .settings import get_settings, atomic_json, new_id, now, file_hash
from .store import Store
from .services import analysis_for, create_candidate, run_audit, load_candidate
from .training import TrainingPaused


@contextmanager
def gpu_lock(settings):
    path = settings.root / ".local/gpu.lock"
    with path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("GPU 已被另一 PAMOs 任务占用") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def perform(kind, request, progress, store, secret):
    settings = store.settings
    if kind in {"generation", "learned_generation"}:
        from .conditions import normalize
        conditions = normalize(request)["effective_conditions"]
        asset = store.get("assets", conditions["music_asset_id"])
        if "local_research" not in asset["allowed_actions"]:
            raise ValueError("音乐尚未允许本机创作用途")
        analysis = analysis_for(asset, progress, store)
        progress({"progress": .65, "message": "音频分析完成，正在生成候选"})
        if kind == "generation":
            from .baseline import generate_baseline
            chart = generate_baseline(analysis, conditions)
            source = "baseline_only"
        else:
            from .inference import generate_learned
            bundle = store.get("models", conditions["model_bundle_id"])
            with gpu_lock(settings):
                chart = generate_learned(analysis, conditions, bundle.get("bundle", bundle), settings.root, progress)
            source = "learned_experimental"
        candidate = create_candidate(chart, conditions, asset["id"], source=source, manifest={"music_sha256": asset["sha256"], "model_bundle_id": conditions["model_bundle_id"], "feature_version": analysis.get("feature_version")}, store=store)
        audit = run_audit(candidate["id"], analysis, store)
        return {"candidate_id": candidate["id"], "audit": audit}
    if kind == "audit":
        candidate, _ = load_candidate(request["candidate_id"], store)
        analysis = None
        if candidate.get("music_asset_id"):
            analysis = analysis_for(store.get("assets", candidate["music_asset_id"]), progress, store)
        return run_audit(candidate["id"], analysis, store)
    if kind == "analysis":
        return analysis_for(store.get("assets", request["music_asset_id"]), progress, store)
    if kind == "dataset":
        from .dataset import build_manifest
        from .formats import read_chart, chart_to_ir
        samples = []
        charts = [store.get("charts", cid) for cid in request["chart_ids"]]
        for index, chart in enumerate(charts):
            asset = store.get("assets", chart["music_asset_id"])
            for record in (chart, asset):
                if record.get("license_status") != "explicit_permitted" or "training" not in record.get("allowed_actions", []):
                    raise ValueError("所有音乐与谱面都需要独立、明确的训练授权")
            from .training_readiness import sample_for_chart
            analysis = analysis_for(asset, progress, store)
            parsed = read_chart(settings.path(chart["path"]))
            ir = chart_to_ir(parsed, chart["chart_mode"], chart.get("key_count"), copy_raw=False)
            if ir.get("unsupported_features"):
                raise ValueError("数据包含未支持或噪域机制，不能静默转入训练")
            samples.append(sample_for_chart(chart, asset, analysis, settings))
            progress({"progress": (index + 1) / max(1, len(charts)), "message": f"已处理 {index + 1}/{len(charts)} 个授权样本"})
        identifier = new_id()
        output = settings.data_dir / "datasets" / identifier
        manifest = build_manifest(samples, output, seed=request.get("seed", 42))
        manifest_path = settings.path(manifest["manifest_path"])
        record = store.put("datasets", {"id": identifier, "manifest_path": settings.relative(manifest_path), "sha256": file_hash(manifest_path), "sample_count": len(samples), "manifest": manifest,
            "version": manifest.get("version"), "group_count": manifest.get("group_count"), "split_counts": manifest.get("split_counts"), "feature_version": manifest.get("feature_version")}, immutable=True)
        return {"dataset_id": record["id"]}
    if kind == "training":
        from .training import run_training
        dataset = store.get("datasets", request["dataset_id"])
        manifest = settings.path(dataset["manifest_path"])
        if file_hash(manifest) != dataset["sha256"]:
            raise ValueError("训练集 manifest 内容发生变化")
        effective = {**request, "manifest_path": dataset["manifest_path"]}
        with gpu_lock(settings):
            result = run_training(effective, settings.root, progress,
                pause_requested=lambda: bool(store.get("jobs", request["job_id"]).get("pause_requested")) if request.get("job_id") else False)
        run = store.put("training_runs", {**result, "id": new_id()}, immutable=True)
        if result.get("bundle", {}).get("stages"):
            bundle = result["bundle"]
            model = store.put("models", {"id": new_id(), "name": f"实验模型 {result.get('run_id', run['id'])[:12]}", "status": "experimental", "available": bool(bundle.get("supported_modes")), "bundle": bundle,
                "run_id": result.get("run_id", run["id"]), "stages": bundle["stages"], "verification": "训练输出，尚未人工验收"})
            result["model_bundle_id"] = model["id"]
        return result
    if kind == "postprocess":
        from .llm import request_suggestion
        return request_suggestion(request["candidate_id"], request, secret, store)
    raise ValueError("未知任务类型")


def main():
    store = Store()
    job_id = sys.argv[1]
    job = store.get("jobs", job_id)
    secret = json.loads(sys.stdin.buffer.read(16384) or b"{}")
    def progress(value, message=None):
        update = value if isinstance(value, dict) else {"progress": value, "message": message or "执行中"}
        allowed = {k: v for k, v in update.items() if k in {"progress", "message", "phase", "epoch", "step", "metrics", "run_id"}}
        if "progress" in allowed:
            allowed["progress"] = min(1., max(0., float(allowed["progress"])))
        store.update("jobs", job_id, allowed)
    try:
        request = dict(job["request"])
        if job["kind"] == "training":
            request["job_id"] = job_id
        result = perform(job["kind"], request, progress, store, secret)
        if store.get("jobs", job_id)["status"] == "running":
            store.update("jobs", job_id, {"status": "succeeded", "result": result, "progress": 1, "finished_at": now(), "message": "处理完成，验收状态见产物记录"})
    except TrainingPaused as exc:
        if store.get("jobs", job_id)["status"] not in {"cancelled", "cancelling"}:
            store.update("jobs", job_id, {"status": "paused", "finished_at": now(), "message": str(exc), "error": None})
    except Exception as exc:
        traceback.print_exc()
        if store.get("jobs", job_id)["status"] not in {"cancelled", "cancelling"}:
            store.update("jobs", job_id, {"status": "failed", "error": str(exc)[:1000], "error_details": exc.as_dict() if hasattr(exc, "as_dict") else None, "message": "任务失败；原始素材未修改", "finished_at": now()})
        sys.exit(1)


if __name__ == "__main__":
    main()

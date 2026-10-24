"""Bounded load calibration on authorized train windows; never replace a model."""
import argparse
from collections import defaultdict
import gc
import json
import math
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--windows", type=int, default=64)
    args = parser.parse_args()
    if len(args.run_id) != 32 or any(c not in "0123456789abcdef" for c in args.run_id):
        raise ValueError("训练记录ID无效")
    if args.windows not in (32, 64, 96, 128):
        raise ValueError("校准窗口数须为32/64/96/128")
    os.environ.setdefault("PAMOS_ROOT", str(Path(__file__).resolve().parents[1]))
    from phiaimadeos.store import Store
    from phiaimadeos.settings import atomic_json, file_hash, new_id, now
    from phiaimadeos.worker import gpu_lock
    from phiaimadeos._model_data import read_manifest, safe_path, SongCache, build_windows
    from phiaimadeos._training_batch import (EXECUTION_VERSION, batch_executor, prepare_batch,
        window_chunks, prepared_chunks, transfer_batch, loss_rows)
    from phiaimadeos.models import build_model, ModelError
    from phiaimadeos.training import _loss, _resources, _enforce_budget, _environment

    store = Store(); settings = store.settings
    if any(job.get("kind") in {"training", "learned_generation", "training_calibration"}
           and job["status"] in {"running", "queued", "cancelling"} for job in store.list("jobs")):
        raise ValueError("已有GPU任务，请等待完成")
    source_path = settings.data_dir / "training" / args.run_id / "run_manifest.json"
    parent_sha = file_hash(source_path)
    parent = json.loads(source_path.read_text(encoding="utf-8"))
    if parent["training_state"] != "complete":
        raise ValueError("校准需已完成训练的本机模型")
    dataset_path = safe_path(settings.root, parent["manifest_path"])
    if file_hash(dataset_path) != parent["dataset_manifest_sha256"]:
        raise ValueError("数据集manifest发生变化")
    _, samples = read_manifest(dataset_path, settings.root)
    samples = [sample for sample in samples if sample["split"] == "train"]
    identifier = new_id(); folder = settings.data_dir / "training_calibration" / identifier
    folder.mkdir(parents=True, exist_ok=False)
    store.put("jobs", {"id": identifier, "kind": "training_calibration", "status": "running", "progress": 0,
        "started_at": now(), "pid": os.getpid(), "request": {"parent_run_id": args.run_id, "windows_per_profile": args.windows},
        "message": "读取真实训练窗口，保留既有模型与断点"})
    report = {"id": identifier, "started_at": now(), "parent_run_id": args.run_id,
        "parent_manifest_sha256": parent_sha, "dataset_manifest_sha256": parent["dataset_manifest_sha256"],
        "execution_version": EXECUTION_VERSION, "train_split_only": True, "profiles": [], "new_training_epoch": False,
        "registered_or_published_model": False, "source_model_changed": False}
    try:
        cache = SongCache(settings.root, samples, max_lines=parent["config"]["max_lines"])
        windows, _ = build_windows(cache)
        # Prefer long real windows, retain each song's chunks, and use identical
        # selected input order for every candidate. No synthetic labels or test set.
        chosen = sorted(range(len(windows)), key=lambda i: (-(windows[i].end - windows[i].start), windows[i].sample_index, windows[i].start))[:args.windows]
        if len(chosen) < 32:
            raise ValueError("真实训练窗口不足32个")
        import torch
        if not torch.cuda.is_available():
            raise ValueError("校准需本机CUDA可用")
        device = torch.device("cuda:0")
        with gpu_lock(settings):
            torch.cuda.set_device(device)
            report["environment"] = _environment(torch, device, settings.root)
            report["source_sha256"] = {name: file_hash(settings.root / "src/phiaimadeos" / name)
                for name in ("models.py", "_training_batch.py", "training.py", "training_runtime.py")}
            amp_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            cases = [(1, 0), (8, 1), (16, 1)]
            for stage_index, (stage, metadata) in enumerate(parent["stages"].items()):
                weight = safe_path(settings.root, metadata["checkpoint_path"])
                if file_hash(weight) != metadata["checkpoint_sha256"]:
                    raise ValueError("模型权重哈希不符")
                for case_index, (batch_size, prefetch) in enumerate(cases):
                    if store.get("jobs", identifier)["status"] != "running":
                        raise KeyboardInterrupt("校准已取消")
                    profile = {"stage": stage, "microbatch": batch_size, "grad_accum": 16 // batch_size,
                               "prefetch_batches": prefetch, "effective_batch_windows": 16}
                    model = optimizer = scaler = None
                    try:
                        torch.manual_seed(parent["seed"])
                        torch.cuda.manual_seed_all(parent["seed"])
                        model = build_model(stage, metadata["config"]).to(device)
                        payload = torch.load(weight, map_location="cpu", weights_only=True)
                        model.load_state_dict(payload["model"], strict=True)
                        del payload
                        model.train()
                        optimizer = torch.optim.AdamW(model.parameters(), lr=parent["config"]["learning_rate"], foreach=False)
                        scaler = torch.amp.GradScaler("cuda", enabled=amp_dtype == torch.float16)
                        motion_dictionary = metadata.get("motion_dictionary")

                        def prepare(indices):
                            song = cache.get(windows[indices[0]].sample_index)
                            if motion_dictionary is not None:
                                song["motion_dictionary"] = motion_dictionary
                            return prepare_batch(stage, song, [windows[i] for i in indices], pin=bool(prefetch))

                        def update(indices):
                            if store.get("jobs", identifier)["status"] != "running":
                                raise KeyboardInterrupt("校准已取消")
                            optimizer.zero_grad(set_to_none=True)
                            total_value = torch.zeros((), device=device)
                            with batch_executor(bool(prefetch)) as executor:
                                for chunk, prepared in prepared_chunks(window_chunks(indices, windows, batch_size), prepare, executor):
                                    batch = transfer_batch(prepared, device)
                                    with torch.autocast(device_type="cuda", dtype=amp_dtype):
                                        prediction = model(**batch["common"])
                                    losses, _parts = loss_rows(stage, prediction, batch, _loss, torch)
                                    total = losses.sum()
                                    if not bool(torch.isfinite(total)):
                                        raise ValueError("实际窗口校准出现非有限损失")
                                    scaler.scale(total / len(indices)).backward()
                                    total_value += total.detach()
                                    del prediction, losses, _parts, total, batch, prepared
                            scaler.unscale_(optimizer)
                            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
                            scaler.step(optimizer); scaler.update()
                            _enforce_budget(_resources(torch, device))
                            return float(total_value) / len(indices)

                        torch.cuda.reset_peak_memory_stats(device)
                        update(chosen[:16])
                        torch.cuda.synchronize(device)
                        start = time.perf_counter()
                        losses = [update(chosen[first:first + 16]) for first in range(0, len(chosen), 16)]
                        torch.cuda.synchronize(device)
                        elapsed = time.perf_counter() - start
                        profile.update(status="succeeded", windows=len(chosen), warmup_windows=16,
                            seconds=elapsed, windows_per_second=len(chosen) / elapsed,
                            mean_loss=sum(losses) / len(losses), resources=_resources(torch, device))
                    except (RuntimeError, ModelError, ValueError) as exc:
                        profile.update(status="failed", error=str(exc)[:1000], resources=_resources(torch, device))
                    finally:
                        model = optimizer = scaler = None
                        cache.song, cache.index = None, None
                        gc.collect(); torch.cuda.empty_cache()
                    report["profiles"].append(profile)
                    atomic_json(folder / "report.json", report)
                    store.update("jobs", identifier, {"progress": (stage_index * len(cases) + case_index + 1) / (len(parent["stages"]) * len(cases)),
                        "message": f"{stage}：并行{batch_size}个窗口的实际负载校准已记录", "result": {"completed_profiles": len(report["profiles"])}})
                    print(json.dumps({key: value for key, value in profile.items() if key != "resources"}, ensure_ascii=True), flush=True)
        candidates = []
        for batch_size, prefetch in cases:
            profiles = [row for row in report["profiles"] if row["microbatch"] == batch_size]
            if len(profiles) == len(parent["stages"]) and all(row["status"] == "succeeded" for row in profiles):
                candidates.append((sum(row["seconds"] for row in profiles), batch_size, prefetch))
        if not candidates:
            raise ValueError("没有覆盖全部阶段且在预算内完成的档位")
        _, batch_size, prefetch = min(candidates)
        if file_hash(source_path) != parent_sha:
            raise ValueError("原训练记录在校准期间变化，未登记推荐档位")
        for metadata in parent["stages"].values():
            for kind in ("checkpoint", "resume_checkpoint"):
                if file_hash(safe_path(settings.root, metadata[kind + "_path"])) != metadata[kind + "_sha256"]:
                    raise ValueError("原权重或恢复点发生变化，未登记推荐档位")
        recommendation = {"microbatch": batch_size, "grad_accum": 16 // batch_size, "prefetch_batches": prefetch,
                          "effective_batch_windows": 16, "calibration_id": identifier, "created_at": now()}
        atomic_json(settings.root / ".local/training-runtime.json", recommendation)
        report.update(status="succeeded", finished_at=now(), recommendation=recommendation)
        atomic_json(folder / "report.json", report)
        store.update("jobs", identifier, {"status": "succeeded", "progress": 1, "finished_at": now(),
            "message": "训练负载档位已按实测吞吐选定；已有模型和断点未改", "result": {"report_path": settings.relative(folder / "report.json"), **recommendation}})
        print(json.dumps({"calibration_id": identifier, "recommendation": recommendation}, ensure_ascii=True), flush=True)
    except BaseException as exc:
        status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
        report.update(status=status, error=str(exc)[:1000], finished_at=now())
        atomic_json(folder / "report.json", report)
        store.update("jobs", identifier, {"status": status, "error": str(exc)[:1000], "finished_at": now()})
        raise


if __name__ == "__main__":
    main()

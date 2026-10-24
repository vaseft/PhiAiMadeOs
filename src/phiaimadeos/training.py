"""Real, sequential small-model training for the local exclusive worker.

No torch import, CUDA initialization, model download or training occurs on
module import. This module does not depend on API/store modules.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import gc
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
import uuid

from .models import ARCH_VERSION, MAX_LINES, MOTION_DICTIONARY_VERSION, POSITION_X_SCALE, ModelError, build_model, model_config, set_motion_dictionary
from ._model_data import (SongCache, batch_for, build_windows, canonical_hash, fit_motion_dictionary,
                          file_hash, read_manifest, relative_path, safe_path)

STAGES = ("note_rhythm", "line_motion", "placement")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _append_log(path: Path, event):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"created_at": _now(), **event}, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()


def _emit(callback, **event):
    if callback is not None:
        callback(event)


def _git_info(root):
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    sha, status = git("rev-parse", "HEAD"), git("status", "--porcelain")
    return {"project_git_sha": sha, "project_git_dirty": bool(status) if status is not None else None}


def _resources(torch, device):
    result = {"process_rss_bytes": None, "process_peak_rss_bytes": None,
              "cuda_allocated_bytes": None, "cuda_reserved_bytes": None,
              "cuda_peak_allocated_bytes": None, "cuda_peak_reserved_bytes": None}
    try:
        import psutil
        info = psutil.Process().memory_info()
        result.update(process_rss_bytes=info.rss, process_peak_rss_bytes=getattr(info, "peak_wset", None))
    except ImportError:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                                                       "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            ctypes.windll.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                result.update(process_rss_bytes=int(counters.WorkingSetSize), process_peak_rss_bytes=int(counters.PeakWorkingSetSize))
        else:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            result["process_peak_rss_bytes"] = int(peak if sys.platform == "darwin" else peak * 1024)
    if device.type == "cuda":
        result.update(cuda_allocated_bytes=torch.cuda.memory_allocated(device), cuda_reserved_bytes=torch.cuda.memory_reserved(device),
                      cuda_peak_allocated_bytes=torch.cuda.max_memory_allocated(device), cuda_peak_reserved_bytes=torch.cuda.max_memory_reserved(device))
    return result


def _enforce_budget(resources):
    if (resources.get("cuda_peak_reserved_bytes") or 0) > 6.2 * 1024 ** 3:
        raise ModelError("GPU_BUDGET_EXCEEDED", "实测峰值 reserved 显存超过 6.2 GiB 工程预算，停止本轮以保留诊断。", resources=resources)
    if (resources.get("process_rss_bytes") or 0) > 6 * 1024 ** 3:
        raise ModelError("RAM_BUDGET_EXCEEDED", "训练工作进程实测 RSS 超过 6 GiB 工程预算。", resources=resources)


def _environment(torch, device, root):
    result = {**_git_info(root), "python_version": platform.python_version(), "platform": platform.platform(),
              "torch_version": str(torch.__version__), "cuda_version": torch.version.cuda,
              "device": str(device), "gpu": None, "gpu_total_bytes": None,
              "cuda_arch_list": None, "driver_version": None, "resources_at_start": _resources(torch, device)}
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(device)
        free, total = torch.cuda.mem_get_info(device)
        result.update(gpu=props.name, gpu_total_bytes=total, gpu_free_bytes_at_start=free,
                      cuda_arch_list=torch.cuda.get_arch_list(), compute_capability=list(torch.cuda.get_device_capability(device)))
        try:
            query = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=10, check=False)
            result["driver_version"] = query.stdout.strip() if query.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            pass
    return result


def _cpu_state(value, torch):
    if isinstance(value, torch.Tensor):
        return value.detach().to("cpu", copy=True)
    if isinstance(value, dict):
        return {key: _cpu_state(child, torch) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return type(value)(_cpu_state(child, torch) for child in value)
    return value


def _rng_state(torch, np, device):
    n = np.random.get_state()
    return {"python": random.getstate(), "numpy": {"algorithm": n[0], "keys": torch.tensor(n[1].astype("int64")),
            "position": n[2], "has_gauss": n[3], "cached_gaussian": n[4]},
            "torch": torch.get_rng_state(), "cuda": torch.cuda.get_rng_state_all() if device.type == "cuda" else []}


def _restore_rng(state, torch, np):
    random.setstate(state["python"])
    n = state["numpy"]
    np.random.set_state((n["algorithm"], n["keys"].numpy().astype("uint32"), n["position"], n["has_gauss"], n["cached_gaussian"]))
    torch.set_rng_state(state["torch"])
    if state["cuda"]:
        if not torch.cuda.is_available() or len(state["cuda"]) != torch.cuda.device_count():
            raise ModelError("RESUME_DEVICE_MISMATCH", "断点CUDA随机状态与当前设备不匹配。")
        torch.cuda.set_rng_state_all(state["cuda"])


def _save_torch(path, payload, torch):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            torch.save(_cpu_state(payload, torch), handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return file_hash(path)


def _masked_mean(value, mask):
    while mask.ndim < value.ndim:
        mask = mask.unsqueeze(-1)
    return (value * mask).sum() / mask.expand_as(value).sum().clamp_min(1)


def _loss(stage, prediction, target, common, song, torch):
    import torch.nn.functional as F
    # Losses are evaluated in fp32 even under autocast.
    prediction = {k: v.float() for k, v in prediction.items()}
    parts = {}
    if stage in ("note_rhythm", "line_motion"):
        truth, logits = target["presence"], prediction["presence"]
        positive = truth.bool()
        prob = torch.sigmoid(logits)
        pt = torch.where(positive, prob, 1 - prob)
        parts["presence"] = (F.binary_cross_entropy_with_logits(logits, truth, reduction="none", pos_weight=logits.new_tensor(4.0)) * (1 - pt).square()).mean()
        categories = ("kind",) if stage == "note_rhythm" else ("line", "property", "easing", "prototype")
        for field in categories:
            parts[field] = _masked_mean(F.cross_entropy(prediction[field].transpose(1, 2), target[field], reduction="none"), positive)
        if stage == "note_rhythm":
            parts["residual"] = _masked_mean(F.smooth_l1_loss(prediction["residual"], target["residual"], reduction="none"), positive)
            parts["hold"] = _masked_mean(F.smooth_l1_loss(prediction["hold"], target["hold"], reduction="none"), positive & (target["kind"] == 1))
            if song["conditions"]["chart_mode"] == "pure_keys":
                parts["lane"] = _masked_mean(F.cross_entropy(prediction["lane"].transpose(1, 2), target["lane"], reduction="none"), positive)
            parts["density"] = F.smooth_l1_loss(prob.sum(1) / 192, truth.sum(1) / 192)
        else:
            for field in ("start", "duration", "values", "easing_bounds"):
                parts[field] = _masked_mean(F.smooth_l1_loss(prediction[field], target[field], reduction="none"), positive)
            parts["line_count"] = F.cross_entropy(prediction["line_count"], target["line_count"])
            count = len(song["parents"])
            parent_logits = prediction["parents"][:, :count]
            parts["parents"] = F.cross_entropy(parent_logits.transpose(1, 2), target["parents"])
            invalid = torch.arange(parent_logits.shape[-1], device=parent_logits.device)[None, :] > torch.arange(count, device=parent_logits.device)[:, None]
            parts["parent_dag"] = (parent_logits.softmax(-1) * invalid[None]).sum(-1).mean()
    else:
        valid = target["valid"]
        pure = song["conditions"]["chart_mode"] == "pure_keys"
        fields = ("lane",) if pure else ("line", "above")
        for field in fields:
            logits = prediction[field]
            if field == "line":
                logits = logits[..., :target["line_count"]]
            parts[field] = _masked_mean(F.cross_entropy(logits.transpose(1, 2), target[field], reduction="none"), valid)
        if not pure:
            for field in ("x", "y_offset"):
                parts[field] = _masked_mean(F.smooth_l1_loss(prediction[field], target[field], reduction="none"), valid)
            parts["speed"] = _masked_mean(F.smooth_l1_loss(torch.log1p(prediction["speed"]), torch.log1p(target["speed"]), reduction="none"), valid)
        if valid.any() and common["queries"].shape[1] > 1:
            times = common["queries"][0, :, 0]
            simultaneous = (times[:, None] - times[None, :]).abs() < (0.03 / (math.expm1(float(common["queries"][0, 0, 14])) or 1))
            simultaneous = simultaneous.triu(1)
            if pure:
                probability = prediction["lane"].softmax(-1)[0]
                collision = probability @ probability.T
            else:
                x = prediction["x"][0]
                probability = prediction["line"].softmax(-1)[0]
                collision = F.relu(24.0 / POSITION_X_SCALE - (x[:, None] - x[None, :]).abs()) * (probability @ probability.T)
            parts["overlap"] = _masked_mean(collision, simultaneous) * 0.1
    total = sum(parts.values())
    if not bool(torch.isfinite(total)):
        raise ModelError("NONFINITE_LOSS", "训练损失出现 NaN/Inf，拒绝更新参数。")
    return total, {k: float(v.detach()) for k, v in parts.items()}


def _training_dir(root):
    # Settings is optional for standalone, non-API use.
    try:
        from .settings import get_settings
        settings = get_settings()
        data_dir = Path(settings.data_dir).resolve() if Path(settings.root).resolve() == root else root / "data"
    except ImportError:
        data_dir = root / "data"
    if not data_dir.is_relative_to(root):
        raise ModelError("UNSAFE_PATH", "训练数据目录必须在项目根目录内。")
    destination = (data_dir / "training").resolve()
    if not destination.is_relative_to(root):
        raise ModelError("UNSAFE_PATH", "训练目录经符号链接指向项目根以外。")
    return destination


def run_training(request: dict, project_root, progress=None) -> dict:
    """Run real training or raise a structured ModelError; never manufacture success.

    Resume is limited to files produced in this controlled local run directory.
    Both weights and full state load with ``weights_only=True``.
    """
    root = Path(project_root).resolve()
    from .formats import PARSER_VERSION
    stage = request.get("stage", "all")
    if stage not in (*STAGES, "all"):
        raise ModelError("INVALID_STAGE", "训练阶段必须为 note_rhythm、line_motion、placement 或 all。")
    epochs, accumulation, seed = int(request.get("epochs", 10)), int(request.get("grad_accum", 16)), int(request.get("seed", 42))
    if not 1 <= epochs <= 10000 or not 1 <= accumulation <= 256 or not 0 <= seed < 2 ** 32:
        raise ModelError("INVALID_TRAIN_CONFIG", "epoch、梯度累积或随机种子超出允许范围。")
    manifest_path = safe_path(root, request.get("manifest_path"))
    manifest, samples = read_manifest(manifest_path, root)
    max_lines = request.get("max_lines", MAX_LINES)
    model_config("line_motion", max_lines)
    cache = SongCache(root, samples, max_lines=max_lines)
    _emit(progress, phase="indexing", progress=0.01, message="核对完整标签与窗口容量。")
    windows, window_report = build_windows(cache)
    if stage in ("all", "note_rhythm", "placement"):
        for split in ("train", "val"):
            if sum(item["notes"] for item in window_report if item["split"] == split) == 0:
                raise ModelError("NOTE_TARGETS_MISSING", f"{split} 没有非零真实音符标签，不能登记为有效音符模型训练。")
    manifest_sha = file_hash(manifest_path)
    config = {"epochs": epochs, "seed": seed, "grad_accum": accumulation, "microbatch": 1, "stage": stage,
              "learning_rate": 0.0002, "weight_decay": 0.01, "gradient_clip": 1.0, "warmup_ratio": 0.05,
              "scheduler": "warmup_cosine", "checkpoint_optimizer_steps": 50,
              "loss_version": "masked-focal-ce-huber-easing-geometry-v2", "window_index_version": "adaptive-audio-domain-384-192-lines-v2",
              "max_lines": max_lines, "models": {s: model_config(s, max_lines) for s in STAGES}}
    fingerprints = [{k: s.get(k) for k in ("chart_id", "music_asset_id", "group_id", "split", "chart_file_sha256", "chart_sha256", "feature_sha256")} for s in samples]
    split_sha = canonical_hash(fingerprints)
    stages = list(STAGES if stage == "all" else (stage,))
    pure_only = all(s["conditions"]["chart_mode"] == "pure_keys" for s in samples)
    if pure_only and "line_motion" in stages:
        if stage == "line_motion":
            raise ModelError("STAGE_NOT_APPLICABLE", "纯配置不训练 LineMotionNet。")
        stages.remove("line_motion")
    stage_windows = {}
    for name in stages:
        selected = [i for i, w in enumerate(windows) if name != "line_motion" or samples[w.sample_index]["conditions"]["chart_mode"] != "pure_keys"]
        stage_windows[name] = {split: [i for i in selected if samples[windows[i].sample_index]["split"] == split] for split in ("train", "val")}
        if not all(stage_windows[name].values()):
            raise ModelError("DATASET_INSUFFICIENT", f"{name} 缺少独立歌曲簇的 train 或 val 标签。")
    # No torch before authorization, label validation, and bounded indexing.
    import numpy as np
    import torch
    requested_device = request.get("device", "cuda")
    if requested_device not in ("cpu", "cuda", "cuda:0"):
        raise ModelError("INVALID_DEVICE", "当前单模型 worker 仅支持 cpu 或 cuda:0。")
    if requested_device != "cpu" and not torch.cuda.is_available():
        raise ModelError("CUDA_UNAVAILABLE", "请求了 CUDA，但当前运行环境没有可用 CUDA；未自动改成假训练。")
    device = torch.device("cuda:0" if requested_device == "cuda" else requested_device)
    if device.type == "cuda":
        torch.cuda.set_device(device)
        torch.cuda.reset_peak_memory_stats(device)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    amp_dtype = torch.bfloat16 if device.type == "cuda" and torch.cuda.is_bf16_supported() else torch.float16
    amp_enabled = device.type == "cuda"
    environment = _environment(torch, device, root)
    environment["source_sha256"] = {name: file_hash(Path(__file__).with_name(name))
                                     for name in ("models.py", "_model_data.py", "training.py", "inference.py", "formats.py", "audio.py")}
    config["device"] = str(device)
    config["precision"] = "bf16" if amp_enabled and amp_dtype == torch.bfloat16 else "fp16" if amp_enabled else "fp32"
    config_sha = canonical_hash(config)
    base = _training_dir(root)
    resume_id = request.get("resume_run_id")
    if resume_id and (not isinstance(resume_id, str) or not all(c.isalnum() or c in "-_" for c in resume_id) or len(resume_id) > 100):
        raise ModelError("INVALID_RUN_ID", "恢复任务 ID 无效。")
    run_id = resume_id or uuid.uuid4().hex
    run_dir = (base / run_id).resolve()
    if not run_dir.is_relative_to(base):
        raise ModelError("UNSAFE_PATH", "训练运行目录越出受管理路径。")
    run_path, log_path = run_dir / "run_manifest.json", run_dir / "metrics.jsonl"
    accepted_config_hashes, extend_completed = {config_sha}, False
    if resume_id:
        if not run_path.is_file():
            raise ModelError("RESUME_UNAVAILABLE", "该训练运行没有可恢复的元数据。")
        record = json.loads(run_path.read_text(encoding="utf-8"))
        old_config = record.get("config", {})
        if ({k: v for k, v in old_config.items() if k != "epochs"} != {k: v for k, v in config.items() if k != "epochs"}
                or epochs < old_config.get("epochs", epochs)):
            raise ModelError("RESUME_CONTRACT_MISMATCH", "恢复仅允许增加 epochs，其他训练配置必须保持一致。")
        extend_completed = epochs > old_config["epochs"]
        accepted_config_hashes.add(record["train_config_sha256"])
        for item in record.get("resume_history", []):
            if item.get("previous_train_config_sha256"):
                accepted_config_hashes.add(item["previous_train_config_sha256"])
        for key, expected in (("dataset_manifest_sha256", manifest_sha), ("split_manifest_sha256", split_sha)):
            if record.get(key) != expected:
                raise ModelError("RESUME_CONTRACT_MISMATCH", "恢复配置、数据或拆分与断点不一致。", field=key)
        record.setdefault("resume_history", []).append({"created_at": _now(), "environment": environment,
                     "previous_config": old_config, "previous_train_config_sha256": record["train_config_sha256"]})
        record.update(config=config, train_config_sha256=config_sha)
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        record = {"id": run_id, "run_id": run_id, "created_at": _now(), "status": "experimental", "training_state": "running",
                  "dataset_id": request.get("dataset_id", manifest.get("id")), "dataset_manifest_id": manifest.get("id"),
                  "manifest_path": relative_path(root, manifest_path), "dataset_manifest_sha256": manifest_sha, "split_manifest_sha256": split_sha,
                  "train_config_sha256": config_sha, "feature_extractor_version": samples[0]["feature_version"],
                  "model_arch_version": ARCH_VERSION, "motion_dictionary_version": MOTION_DICTIONARY_VERSION,
                  "audio_encoder": "traditional-dsp-only", "audio_encoder_sha256": None,
                  "parser_version": PARSER_VERSION,
                  "seed": seed, "config": config, "environment": environment, **{k: environment[k] for k in ("project_git_sha", "project_git_dirty")},
                  "window_report": window_report, "source_fingerprints": fingerprints, "stages": {}, "metrics_path": relative_path(root, log_path),
                  "validation": "song_grouped", "test_evaluation": "NOT RUN", "playtest": "NOT RUN",
                  "audit_report_id": None, "human_review_id": None, "max_vram_gib_observed": None}
    record["training_state"] = "running"
    record["job_id"] = request.get("job_id")
    _atomic_json(run_path, record)
    _emit(progress, run_id=run_id, phase="training_ready", progress=0.03,
          message="真实训练运行已登记；断点与日志保存到本机受管理目录。")
    try:
        for stage_index, name in enumerate(stages):
            previous = record["stages"].get(name, {})
            if previous.get("training_state") == "complete" and not extend_completed:
                weight = safe_path(root, previous["checkpoint_path"])
                if file_hash(weight) != previous["checkpoint_sha256"]:
                    raise ModelError("CHECKPOINT_HASH_MISMATCH", "已完成阶段的权重已发生变化。")
                continue
            stage_dir = run_dir / name
            stage_dir.mkdir(exist_ok=True)
            stage_seed = (seed + STAGES.index(name)) % 2 ** 32
            random.seed(stage_seed)
            np.random.seed(stage_seed)
            torch.manual_seed(stage_seed)
            if device.type == "cuda":
                torch.cuda.manual_seed_all(stage_seed)
            motion_dictionary = None
            if name == "line_motion":
                motion_dictionary = previous.get("motion_dictionary") or fit_motion_dictionary(cache, stage_seed)
            model = build_model(name, config["models"][name]).to(device)
            if motion_dictionary is not None:
                set_motion_dictionary(model, motion_dictionary)
            optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"], foreach=False)
            train_indices, val_indices = stage_windows[name]["train"], stage_windows[name]["val"]
            steps_per_epoch = math.ceil(len(train_indices) / accumulation)
            total_steps, warmup = steps_per_epoch * epochs, max(1, math.ceil(steps_per_epoch * epochs * 0.05))
            def schedule(step):
                if step < warmup:
                    return (step + 1) / warmup
                fraction = (step - warmup) / max(1, total_steps - warmup)
                return 0.5 * (1 + math.cos(math.pi * min(1, fraction)))
            scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, schedule)
            scaler = torch.amp.GradScaler("cuda", enabled=amp_enabled and amp_dtype == torch.float16)
            start_epoch, cursor, optimizer_step, order = 0, 0, 0, None
            best_val, stale = None, 0
            stage_info = {"id": uuid.uuid4().hex, "run_id": run_id, "stage": name, "created_at": _now(), "status": "experimental",
                          "training_state": "running", "config": config["models"][name], "feature_version": samples[0]["feature_version"],
                          "weight_format": "torch_tensor_state_dict", "stage_seed": stage_seed,
                          "motion_dictionary": motion_dictionary,
                          "train_groups": sorted({samples[windows[i].sample_index]["group_id"] for i in train_indices}),
                          "validation_groups": sorted({samples[windows[i].sample_index]["group_id"] for i in val_indices})}
            if previous.get("resume_checkpoint_path"):
                resume_path = safe_path(root, previous["resume_checkpoint_path"])
                if not resume_path.is_relative_to(run_dir.resolve()) or file_hash(resume_path) != previous["resume_checkpoint_sha256"]:
                    raise ModelError("RESUME_HASH_MISMATCH", "本地恢复断点路径或校验值不符。")
                state = torch.load(resume_path, map_location="cpu", weights_only=True)
                if state["config_sha256"] not in accepted_config_hashes or state["split_sha256"] != split_sha or state["stage"] != name:
                    raise ModelError("RESUME_CONTRACT_MISMATCH", "checkpoint 元数据不匹配。")
                model.load_state_dict(state["model"], strict=True)
                optimizer.load_state_dict(state["optimizer"])
                scheduler.load_state_dict(state["scheduler"])
                scaler.load_state_dict(state["scaler"])
                start_epoch, cursor, optimizer_step, order = state["epoch"], state["cursor"], state["optimizer_step"], state["order"]
                best_val, stale = state["best_val"], state["stale"]
                if extend_completed:
                    for group, base_lr in zip(optimizer.param_groups, scheduler.base_lrs):
                        group["lr"] = base_lr * schedule(optimizer_step)
                    scheduler._last_lr = [group["lr"] for group in optimizer.param_groups]
                _restore_rng(state["rng"], torch, np)
                stage_info = {**previous, "training_state": "running"}
                del state
            record["stages"][name] = stage_info
            _atomic_json(run_path, record)

            def save_resume(epoch, position, sample_order):
                payload = {"stage": name, "config_sha256": config_sha, "split_sha256": split_sha, "model": model.state_dict(),
                           "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(), "scaler": scaler.state_dict(),
                           "rng": _rng_state(torch, np, device), "epoch": epoch, "cursor": position, "order": sample_order,
                           "optimizer_step": optimizer_step, "best_val": best_val, "stale": stale}
                # Immutable names keep metadata and checkpoint consistent across a
                # crash between the two separate atomic file replacements.
                checkpoint = stage_dir / f"resume-{optimizer_step:09d}-{uuid.uuid4().hex[:8]}.pt"
                digest = _save_torch(checkpoint, payload, torch)
                old_path = stage_info.get("resume_checkpoint_path")
                stage_info.update(resume_checkpoint_path=relative_path(root, checkpoint), resume_checkpoint_sha256=digest,
                                  optimizer_steps=optimizer_step, next_epoch=epoch, next_window=position)
                _atomic_json(run_path, record)
                if old_path:
                    old_checkpoint = safe_path(root, old_path, exists=False)
                    if not old_checkpoint.is_relative_to(stage_dir.resolve()) or not old_checkpoint.name.startswith("resume-"):
                        raise ModelError("UNSAFE_PATH", "旧断点清理路径不属于当前模型阶段。")
                    old_checkpoint.unlink(missing_ok=True)

            if not previous.get("resume_checkpoint_path"):
                save_resume(0, 0, None)

            for epoch in range(start_epoch, epochs):
                started = time.monotonic()
                if order is None:
                    songs = defaultdict(list)
                    for window_index in train_indices:
                        songs[windows[window_index].sample_index].append(window_index)
                    song_order = list(songs)
                    random.shuffle(song_order)
                    order = []
                    for sample_index in song_order:
                        random.shuffle(songs[sample_index])
                        order.extend(songs[sample_index])
                    cursor = 0
                model.train()
                epoch_loss, epoch_windows = 0.0, 0
                while cursor < len(order):
                    optimizer.zero_grad(set_to_none=True)
                    group_size = min(accumulation, len(order) - cursor)
                    group_loss, components = 0.0, defaultdict(float)
                    for offset in range(group_size):
                        window = windows[order[cursor + offset]]
                        song = cache.get(window.sample_index)
                        if motion_dictionary is not None:
                            song["motion_dictionary"] = motion_dictionary
                        common, target = batch_for(name, song, window, device)
                        with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=amp_enabled):
                            prediction = model(**common)
                        loss, parts = _loss(name, prediction, target, common, song, torch)
                        scaler.scale(loss / group_size).backward()
                        group_loss += float(loss.detach())
                        for key, value in parts.items():
                            components[key] += value
                        del loss, prediction, common, target
                    scaler.unscale_(optimizer)
                    grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), config["gradient_clip"], error_if_nonfinite=True)
                    if not torch.isfinite(grad_norm):
                        raise ModelError("NONFINITE_GRADIENT", "梯度含 NaN/Inf，拒绝优化器更新。")
                    scaler.step(optimizer)
                    scaler.update()
                    scheduler.step()
                    optimizer_step += 1
                    cursor += group_size
                    epoch_loss += group_loss
                    epoch_windows += group_size
                    resources = _resources(torch, device)
                    _append_log(log_path, {"phase": "train", "stage": name, "epoch": epoch + 1, "optimizer_step": optimizer_step,
                                "microbatch": 1, "accumulated_windows": group_size, "loss": group_loss / group_size,
                                "loss_components": {k: v / group_size for k, v in components.items()}, "lr": optimizer.param_groups[0]["lr"],
                                "grad_norm_before_clip": float(grad_norm), "resources": resources})
                    _enforce_budget(resources)
                    if optimizer_step % config["checkpoint_optimizer_steps"] == 0:
                        save_resume(epoch, cursor, order)
                    _emit(progress, phase="training", stage=name,
                          progress=0.03 + 0.94 * (stage_index + (epoch + cursor / len(order)) / epochs) / len(stages),
                          message=f"{name} 第 {epoch + 1} 轮，真实优化器步 {optimizer_step}。", loss=group_loss / group_size)
                model.eval()
                val_groups = defaultdict(list)
                val_parts = defaultdict(list)
                with torch.inference_mode():
                    for index in val_indices:
                        window = windows[index]
                        song = cache.get(window.sample_index)
                        if motion_dictionary is not None:
                            song["motion_dictionary"] = motion_dictionary
                        common, target = batch_for(name, song, window, device)
                        with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=amp_enabled):
                            prediction = model(**common)
                        loss, parts = _loss(name, prediction, target, common, song, torch)
                        group = samples[window.sample_index]["group_id"]
                        val_groups[group].append(float(loss))
                        for key, value in parts.items():
                            val_parts[key].append(value)
                        del prediction, loss, common, target
                by_group = {group: sum(values) / len(values) for group, values in val_groups.items()}
                val_loss = sum(by_group.values()) / len(by_group)
                metrics = {"phase": "validation", "stage": name, "epoch": epoch + 1, "optimizer_step": optimizer_step,
                           "train_loss_current_segment": epoch_loss / max(1, epoch_windows), "train_windows_current_segment": epoch_windows,
                           "validation_loss_song_macro": val_loss, "validation_loss_by_song_group": by_group,
                           "validation_components_window_mean": {k: sum(v) / len(v) for k, v in val_parts.items()},
                           "epoch_seconds_current_segment": time.monotonic() - started, "resources": _resources(torch, device)}
                _append_log(log_path, metrics)
                _enforce_budget(metrics["resources"])
                improved = best_val is None or val_loss < best_val
                if improved:
                    best_val, stale = val_loss, 0
                    weights = stage_dir / f"weights-{optimizer_step:09d}-{uuid.uuid4().hex[:8]}.pt"
                    weight_sha = _save_torch(weights, {"model": model.state_dict(), "config": config["models"][name],
                                "feature_version": samples[0]["feature_version"], "run_id": run_id,
                                "train_config_sha256": config_sha, "dataset_manifest_sha256": manifest_sha}, torch)
                    stage_info.update(checkpoint_path=relative_path(root, weights), checkpoint_sha256=weight_sha,
                                      weight_train_config_sha256=config_sha, best_validation_loss=best_val, best_epoch=epoch + 1)
                else:
                    stale += 1
                stage_info.update(last_metrics=metrics, epochs_completed=epoch + 1)
                order, cursor = None, 0
                save_resume(epoch + 1, 0, None)
                if stale >= 8:
                    stage_info["early_stopped"] = True
                    break
            if not stage_info.get("checkpoint_path"):
                raise ModelError("CHECKPOINT_UNAVAILABLE", "训练没有产生有限验证损失和有效权重。")
            coverage_train = {(samples[windows[i].sample_index]["conditions"]["chart_mode"], samples[windows[i].sample_index]["conditions"].get("key_count")) for i in train_indices}
            coverage_val = {(samples[windows[i].sample_index]["conditions"]["chart_mode"], samples[windows[i].sample_index]["conditions"].get("key_count")) for i in val_indices}
            coverage = coverage_train & coverage_val
            stage_info.update(training_state="complete", completed_at=_now(), supported_modes=sorted({mode for mode, _ in coverage}),
                              key_counts=sorted(k for mode, k in coverage if mode == "pure_keys"),
                              coverage=[{"chart_mode": mode, "key_count": k} for mode, k in sorted(coverage, key=str)])
            _atomic_json(run_path, record)
            del optimizer, scheduler, scaler, model
            cache.song, cache.index = None, None
            gc.collect()
            if device.type == "cuda":
                torch.cuda.empty_cache()
        bundle_stages = record["stages"]
        note, placement = bundle_stages.get("note_rhythm", {}), bundle_stages.get("placement", {})
        modes = set(note.get("supported_modes", [])) & set(placement.get("supported_modes", []))
        if "regular" in modes and "line_motion" not in bundle_stages:
            modes.remove("regular")
        key_counts = sorted(set(note.get("key_counts", [])) & set(placement.get("key_counts", [])))
        record.update(training_state="complete", completed_at=_now(), models=list(bundle_stages.values()),
                      bundle={"id": run_id, "run_id": run_id, "status": "experimental", "arch_version": ARCH_VERSION,
                              "max_lines": max_lines,
                              "stages": bundle_stages, "feature_version": samples[0]["feature_version"],
                              "supported_modes": sorted(modes), "key_counts": key_counts,
                              "coverage_warning": "仅表示有分组训练和验证数据；生成质量、客户端试玩及模型能力尚未验收。"})
        resources = _resources(torch, device)
        record["final_resources"] = resources
        if resources["cuda_peak_reserved_bytes"] is not None:
            record["max_vram_gib_observed"] = resources["cuda_peak_reserved_bytes"] / 1024 ** 3
        _atomic_json(run_path, record)
        _emit(progress, phase="complete", progress=1.0, message="真实训练运行已结束；模型保持 experimental，等待独立验收。")
        return record
    except Exception as exc:
        error = exc.as_dict() if isinstance(exc, ModelError) else {"code": "TRAINING_FAILED", "message": str(exc), "type": type(exc).__name__}
        if isinstance(exc, torch.OutOfMemoryError):
            error.update(code="CUDA_OOM" if device.type == "cuda" else "RAM_OOM", message="真实训练内存不足，已停止；请调整容量并重新进行资源验收。")
            if "window" in locals():
                error["window"] = {"sample_index": window.sample_index, "start_s": window.start, "end_s": window.end}
        record.update(training_state="failed", failed_at=_now(), error=error, final_resources=_resources(torch, device))
        _atomic_json(run_path, record)
        _append_log(log_path, {"phase": "failed", "error": error, "resources": record["final_resources"]})
        raise

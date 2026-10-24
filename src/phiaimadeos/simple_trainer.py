"""Two-button controller for an existing local run; never starts on page load."""
from __future__ import annotations

import asyncio
import json
import os
import shutil

from .jobs import GPU_KINDS
from .settings import atomic_json, file_hash, new_id, now
from .training_runtime import recommended_runtime

ACTIVE = {"queued", "running", "cancelling"}


class SimpleTrainer:
    def __init__(self, store, jobs):
        self.store, self.jobs = store, jobs
        self.settings = store.settings
        self.state_path = self.settings.root / ".local/simple-trainer.json"
        self.lock = asyncio.Lock()

    @staticmethod
    def _read(path, limit=8 * 1024 * 1024):
        if not path.is_file():
            return {}
        if path.stat().st_size > limit:
            raise ValueError("训练元数据超过大小上限")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("训练元数据格式无效")
        return value

    def _run(self):
        state = self._read(self.state_path, 16384)
        hold = self._read(self.settings.root / ".local/training-user-hold.json", 16384)
        run_id = state.get("run_id") or hold.get("resume_run_id")
        if not run_id:
            models = [m for m in self.store.list("models") if m.get("run_id") and m.get("available")]
            run_id = models[0]["run_id"] if models else None
        if not isinstance(run_id, str) or not 1 <= len(run_id) <= 100 or not all(c.isalnum() or c in "-_" for c in run_id):
            raise ValueError("尚无可续训的模型，请先在完整工作台登记数据并完成初训")
        base = (self.settings.data_dir / "training").resolve()
        path = (base / run_id / "run_manifest.json").resolve()
        if not path.is_relative_to(base):
            raise ValueError("训练目录不在本机受管理范围内")
        record = self._read(path)
        if record.get("run_id") != run_id or not record.get("stages"):
            raise ValueError("本机训练记录或断点尚未准备好")
        return state, record, path

    def _related(self, run_id):
        return [j for j in self.store.list("jobs") if j["kind"] == "training"
                and (j.get("run_id") == run_id or j.get("request", {}).get("resume_run_id") == run_id)]

    def _busy(self):
        return [j for j in self.store.list("jobs") if j["status"] in ACTIVE
                and j["kind"] in GPU_KINDS | {"training_calibration"}]

    def status(self):
        try:
            state, run, _ = self._run()
        except (ValueError, OSError) as exc:
            return {"state": "unavailable", "progress": 0, "message": str(exc), "can_start": False, "can_pause": False}
        related = self._related(run["run_id"])
        busy = self._busy()
        active = next((j for j in related if j["status"] in ACTIVE), None)
        job = active or next((j for j in related if j["id"] == state.get("job_id")), None)
        if not job and related:
            job = related[0]
        progress = float(job.get("progress", 0)) if job else (1. if run.get("training_state") == "complete" else 0.)
        status = job["status"] if job else run.get("training_state", "ready")
        message = "准备就绪，点击训练继续一轮"
        if active:
            status = "pausing" if active.get("pause_requested") else active["status"]
            message = "正在保存断点，请稍候…" if status == "pausing" else active.get("message", "正在训练")
            progress = max(progress, float(active.get("request", {}).get("progress_floor", 0)))
        elif busy:
            status, message = "busy", "其他任务正在使用GPU，请稍候"
        elif status == "paused":
            message = "已暂停，点击训练从断点继续"
        elif status in {"failed", "interrupted", "cancelled"}:
            message = (job.get("error") or job.get("message")) if job else "训练已中断，可从断点继续"
        elif status in {"succeeded", "complete"}:
            status, progress = "complete", 1.
            message = "本轮已完成，点击训练继续下一轮"
        return {"state": status, "progress": min(1., max(0., progress)), "message": message or "可从断点继续",
                "can_start": not busy, "can_pause": bool(active and active["status"] in {"queued", "running"}
                                                           and not active.get("pause_requested"))}

    def _prepare(self):
        state, record, run_path = self._run()
        config = record["config"]
        dataset = self.store.get("datasets", record["dataset_id"])
        manifest = self.settings.path(dataset["manifest_path"])
        if file_hash(manifest) != dataset["sha256"] or dataset["sha256"] != record["dataset_manifest_sha256"]:
            raise ValueError("训练集与已有断点不一致，未启动训练")
        target = int(config["epochs"])
        # A pause before indexing may precede any manifest update; keep that
        # click's target rather than accidentally requesting another epoch.
        if state.get("target_epochs", 0) > target:
            target = int(state["target_epochs"])
            start_epoch = int(state["progress_epoch_start"])
        elif record.get("training_state") == "complete":
            start_epoch, target = target, target + 1
        else:
            start_epoch = int(state.get("progress_epoch_start", max(0, target - 1)))
        if target > 1000:
            raise ValueError("已达到简洁窗口轮数上限，请在完整工作台检查训练计划")
        runtime = recommended_runtime(self.settings.root)
        old_effective = config.get("microbatch", 1) * config.get("grad_accum", 16)
        if runtime["effective_batch_windows"] != old_effective:
            runtime = {key: config.get(key, default) for key, default in (("microbatch", 1), ("grad_accum", 16), ("prefetch_batches", 0))}
        request = {"dataset_id": record["dataset_id"], "resume_run_id": record["run_id"], "stage": config["stage"],
                   "epochs": target, "seed": config["seed"], "max_lines": config["max_lines"],
                   "device": "cuda" if config["device"].startswith("cuda") else "cpu",
                   **{key: runtime[key] for key in ("microbatch", "grad_accum", "prefetch_batches")},
                   "allow_runtime_batch_change": True, "simple_trainer": True, "progress_epoch_start": start_epoch,
                   "progress_floor": self.status()["progress"] if target == state.get("target_epochs") else 0.}
        # Checkpoint files have unique immutable names. Hard links keep a
        # pre-click rollback snapshot without duplicating large tensors on NTFS.
        backup = self.settings.data_dir / "training_backups" / record["run_id"] / new_id()
        backup.mkdir(parents=True, exist_ok=False)
        for stage in record["stages"].values():
            for key in ("checkpoint", "resume_checkpoint"):
                if not stage.get(key + "_path"):
                    continue
                source = self.settings.path(stage[key + "_path"])
                if not source.is_relative_to(run_path.parent) or file_hash(source) != stage[key + "_sha256"]:
                    raise ValueError("训练断点路径或SHA校验不符，未启动训练")
                destination = backup / source.relative_to(run_path.parent)
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copy2(source, destination)
        shutil.copy2(run_path, backup / "run_manifest.json")
        atomic_json(backup / "snapshot.json", {"created_at": now(), "run_id": record["run_id"],
                    "original_run_directory": self.settings.relative(run_path.parent), "reason": "simple-trainer-button"})
        return request, self.settings.relative(backup)

    async def start(self):
        async with self.lock:
            if self._busy():
                return self.status()  # Repeated clicks cannot queue extra rounds.
            request, backup = await asyncio.to_thread(self._prepare)
            if self._busy():
                return self.status()
            previous = self._read(self.state_path, 16384)
            pending = {"run_id": request["resume_run_id"], "target_epochs": request["epochs"],
                       "progress_epoch_start": request["progress_epoch_start"], "backup_path": backup, "updated_at": now()}
            atomic_json(self.state_path, pending)
            try:
                submitted = self.jobs.submit("training", request)
            except Exception:
                atomic_json(self.state_path, previous)
                raise
            atomic_json(self.state_path, {**pending, **submitted})
            self.store.event("training.simple_start", submitted["job_id"], target_epochs=request["epochs"], backup_path=backup)
            return self.status()

    async def pause(self):
        async with self.lock:
            _, record, _ = self._run()
            for job in self._related(record["run_id"]):
                if job["status"] in {"queued", "running"}:
                    self.jobs.pause_training(job["id"])
                    self.store.event("training.pause_requested", job["id"])
            return self.status()

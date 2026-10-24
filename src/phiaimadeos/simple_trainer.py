"""Two-button controller for an existing local run; never starts on page load."""
from __future__ import annotations

import asyncio
import json
import os
import shutil

from .jobs import GPU_KINDS
from .settings import file_hash, new_id, now
from .training import _atomic_json as atomic_json
from .training_runtime import recommended_runtime
from .training_analysis import TrainingAnalysis
from .training_sources import SourcePlanner, plateau_stages, read_run, PATIENCE

ACTIVE = {"queued", "running", "cancelling"}
STATE_BYTES = 256 * 1024


class SimpleTrainer:
    def __init__(self, store, jobs):
        self.store, self.jobs = store, jobs
        self.settings = store.settings
        self.state_path = self.settings.root / ".local/simple-trainer.json"
        self.lock = asyncio.Lock()
        self.curves = TrainingAnalysis()
        self.sources = SourcePlanner(store)

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
        state = self._read(self.state_path, STATE_BYTES)
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
        pending = state.get("pending_request", {})
        if not path.is_file() and pending.get("new_run_id") == run_id:
            parent, _ = read_run(self.settings, pending["warm_start_run_id"])
            return state, {**parent, "run_id": run_id, "dataset_id": pending["dataset_id"], "stages": {},
                "config": {**parent["config"], "epochs": 1}, "training_state": "pending", "_source_pending": True,
                "metrics_path": self.settings.relative(path.parent / "metrics.jsonl")}, path
        record = self._read(path)
        if record.get("run_id") != run_id or (not record.get("stages") and pending.get("new_run_id") != run_id):
            raise ValueError("本机训练记录或断点尚未准备好")
        return state, record, path

    def _related(self, run_id):
        return [j for j in self.store.list("jobs") if j["kind"] == "training"
                and (j.get("run_id") == run_id or j.get("request", {}).get("resume_run_id") == run_id
                     or j.get("request", {}).get("new_run_id") == run_id)]

    def _busy(self):
        return [j for j in self.store.list("jobs") if j["status"] in ACTIVE
                and j["kind"] in GPU_KINDS | {"training_calibration"}]

    def status(self):
        try:
            state, run, _ = self._run()
        except (ValueError, OSError) as exc:
            return {"state": "unavailable", "progress": 0, "message": str(exc), "can_start": False, "can_pause": False,
                    "auto_continue": False, "auto_replace_source": False, "source_history": []}
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
        if not active and state.get("auto_error"):
            message = "自动继续已停止：" + state["auto_error"]
        return {"state": status, "progress": min(1., max(0., progress)), "message": message or "可从断点继续",
                "auto_continue": bool(state.get("auto_continue")),
                "auto_replace_source": bool(state.get("auto_replace_source")),
                "source": {"run_id": run["run_id"], "sample_count": self.store.get("datasets", run["dataset_id"])["sample_count"],
                    "phase": len(state.get("source_history", [])) + 1, "patience": PATIENCE, "plateau_stages": plateau_stages(run)},
                "source_history": state.get("source_history", []),
                "can_start": not busy, "can_pause": bool(active and active["status"] in {"queued", "running"}
                                                           and not active.get("pause_requested"))}

    def analysis(self, run_id=None):
        state, record, path = self._run()
        if run_id and run_id != record["run_id"]:
            if run_id not in {p["run_id"] for p in state.get("source_history", [])}:
                raise ValueError("只能读取当前训练链的历史曲线")
            record, path = read_run(self.settings, run_id)
        metrics = self.settings.path(record.get("metrics_path", str(path.parent / "metrics.jsonl")))
        if not metrics.is_relative_to(path.parent):
            raise ValueError("训练日志不属于当前运行")
        return {**self.curves.read(metrics, record["run_id"]), "run_id": record["run_id"], "dataset_id": record["dataset_id"]}

    def _prepare(self):
        state, record, run_path = self._run()
        if record.get("_source_pending"):
            return dict(state["pending_request"]), state["backup_path"]
        config = record["config"]
        dataset = self.store.get("datasets", record["dataset_id"])
        manifest = self.settings.path(dataset["manifest_path"])
        if file_hash(manifest) != dataset["sha256"] or dataset["sha256"] != record["dataset_manifest_sha256"]:
            raise ValueError("训练集与已有断点不一致，未启动训练")
        runtime = recommended_runtime(self.settings.root)
        old_effective = config.get("microbatch", 1) * config.get("grad_accum", 16)
        if runtime["effective_batch_windows"] != old_effective:
            runtime = {key: config.get(key, default) for key, default in (("microbatch", 1), ("grad_accum", 16), ("prefetch_batches", 0))}
        if record["training_state"] == "complete" and state.get("auto_replace_source") and plateau_stages(record):
            request = self.sources.request(record, runtime)
            return request, self._snapshot(record, run_path)
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
        request = {"dataset_id": record["dataset_id"], "resume_run_id": record["run_id"], "stage": config["stage"],
                   "epochs": target, "seed": config["seed"], "max_lines": config["max_lines"],
                   "device": "cuda" if config["device"].startswith("cuda") else "cpu",
                   **{key: runtime[key] for key in ("microbatch", "grad_accum", "prefetch_batches")},
                   "allow_runtime_batch_change": True, "simple_trainer": True, "progress_epoch_start": start_epoch,
                   "progress_floor": self.status()["progress"] if target == state.get("target_epochs") else 0.}
        return request, self._snapshot(record, run_path)

    def _snapshot(self, record, run_path):
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
        return self.settings.relative(backup)

    async def start(self, automatic=False):
        async with self.lock:
            state = self._read(self.state_path, STATE_BYTES)
            if automatic:
                if not state.get("auto_continue") or not state.get("auto_armed") or not state.get("job_id"):
                    return self.status()
                if self.store.get("jobs", state["job_id"])["status"] != "succeeded":
                    return self.status()
            if self._busy():
                return self.status()  # Repeated clicks cannot queue extra rounds.
            request, backup = await asyncio.to_thread(self._prepare)
            if self._busy():
                return self.status()
            previous = self._read(self.state_path, STATE_BYTES)
            pending = {**previous, "run_id": request.get("resume_run_id") or request["new_run_id"], "target_epochs": request["epochs"],
                       "progress_epoch_start": request["progress_epoch_start"], "backup_path": backup, "updated_at": now()}
            pending.update(auto_armed=bool(previous.get("auto_continue")), auto_error=None)
            if request.get("warm_start_run_id"):
                history = list(previous.get("source_history", []))
                if request["warm_start_run_id"] not in {p["run_id"] for p in history}:
                    parent, _ = read_run(self.settings, request["warm_start_run_id"])
                    history.append({"run_id": parent["run_id"], "dataset_id": parent["dataset_id"],
                        "sample_count": self.store.get("datasets", parent["dataset_id"])["sample_count"], "epochs": parent["config"]["epochs"]})
                pending.update(pending_request=request, source_history=history)
            else:
                pending.pop("pending_request", None)
            atomic_json(self.state_path, pending)
            try:
                submitted = self.jobs.submit("training", request)
            except Exception:
                atomic_json(self.state_path, previous)
                raise
            atomic_json(self.state_path, {**pending, **submitted})
            self.store.event("training.simple_start", submitted["job_id"], target_epochs=request["epochs"], backup_path=backup, automatic=automatic)
            return self.status()

    async def pause(self):
        async with self.lock:
            state, record, _ = self._run()
            atomic_json(self.state_path, {**state, "auto_continue": False, "auto_armed": False, "auto_error": None})
            for job in self._related(record["run_id"]):
                if job["status"] in {"queued", "running"}:
                    self.jobs.pause_training(job["id"])
                    self.store.event("training.pause_requested", job["id"])
            return self.status()

    async def set_auto(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("自动继续须为开启或关闭")
        async with self.lock:
            state, record, _ = self._run()
            related = self._related(record["run_id"])
            active = next((j for j in related if j["status"] in {"queued", "running"} and not j.get("pause_requested")), None)
            atomic_json(self.state_path, {**state, "run_id": record["run_id"], "auto_continue": enabled,
                "auto_armed": bool(enabled and active), "auto_error": None, "updated_at": now(),
                **({"job_id": active["id"]} if active else {})})
            self.store.event("training.auto_continue", record["run_id"], enabled=enabled)
            return self.status()

    async def _stop_auto(self, reason):
        async with self.lock:
            state = self._read(self.state_path, STATE_BYTES)
            if state.get("auto_continue"):
                atomic_json(self.state_path, {**state, "auto_continue": False, "auto_armed": False, "auto_error": reason[:1000]})
                self.store.event("training.auto_stopped", state.get("run_id"), reason=reason[:1000])

    async def watch(self):
        while True:
            await asyncio.sleep(2)
            try:
                state = self._read(self.state_path, STATE_BYTES)
                if not (state.get("auto_continue") and state.get("auto_armed") and state.get("job_id")):
                    continue
                job = self.store.get("jobs", state["job_id"])
                if job["status"] in {"failed", "paused", "cancelled", "interrupted"}:
                    await self._stop_auto("训练已暂停、中断或失败，请检查后手动继续")
                elif job["status"] == "succeeded" and not self._busy():
                    _, record, _ = self._run()
                    if plateau_stages(record) and not state.get("auto_replace_source"):
                        await self._stop_auto("验证指标已触发早停")
                    else:
                        await self.start(automatic=True)
            except (ValueError, KeyError, OSError) as exc:
                await self._stop_auto(str(exc))

    async def set_source_auto(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("自动换源须为开启或关闭")
        async with self.lock:
            state, record, _ = self._run()
            atomic_json(self.state_path, {**state, "auto_replace_source": enabled, "auto_error": None, "updated_at": now()})
            self.store.event("training.auto_source", record["run_id"], enabled=enabled, patience=PATIENCE)
            return self.status()

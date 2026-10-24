"""Bounded subprocess jobs. Cancellation never turns partial output into success."""
from __future__ import annotations
import asyncio
import json
import os
import sys
from .settings import atomic_json, now
from .store import Store

GPU_KINDS = {"training", "learned_generation"}


class Jobs:
    def __init__(self, store=None):
        self.store = store or Store()
        self.active = {}
        self.tasks = set()
        self.cpu = asyncio.Semaphore(1)
        self.gpu = asyncio.Semaphore(1)
        self.closing = False

    def recover(self):
        for job in self.store.list("jobs"):
            if job["status"] in {"queued", "running", "cancelling"}:
                self.store.update("jobs", job["id"], {"status": "interrupted", "message": "工作台上次退出；未自动重启任务，可显式续训", "finished_at": now()})

    def submit(self, kind, request, secret=None):
        if self.closing:
            raise ValueError("工作台正在退出")
        if sum(j["status"] in {"queued", "running", "cancelling"} for j in self.store.list("jobs")) >= 20:
            raise ValueError("任务队列已满，请等待或取消任务")
        job = self.store.put("jobs", {"kind": kind, "request": request, "status": "queued", "progress": 0, "message": "等待执行", "result": None, "error": None})
        task = asyncio.create_task(self._run(job["id"], kind, secret))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return {"job_id": job["id"]}

    async def _run(self, job_id, kind, secret):
        semaphore = self.gpu if kind in GPU_KINDS else self.cpu
        async with semaphore:
            if self.closing or self.store.get("jobs", job_id)["status"] != "queued":
                return
            settings = self.store.settings
            env = dict(os.environ, PAMOS_ROOT=str(settings.root), PYTHONUTF8="1", PYTHONUNBUFFERED="1")
            # src layout is also available when launched without an editable install.
            env["PYTHONPATH"] = str(settings.root / "src") + os.pathsep + str(settings.root)
            log_path = settings.data_dir / "jobs" / (job_id + ".log")
            process = None
            try:
                self.store.update("jobs", job_id, {"status": "running", "started_at": now(), "log_path": settings.relative(log_path)})
                with log_path.open("wb") as log:
                    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "phiaimadeos.worker", job_id,
                        cwd=settings.root, env=env, stdin=asyncio.subprocess.PIPE, stdout=log, stderr=log,
                        creationflags=0x08000000 if os.name == "nt" else 0)
                    self.active[job_id] = process
                    self.store.update("jobs", job_id, {"pid": process.pid})
                    if self.store.get("jobs", job_id)["status"] in {"cancelling", "cancelled"}:
                        process.terminate()
                    await process.communicate(json.dumps(secret or {}).encode("utf-8"))
                current = self.store.get("jobs", job_id)
                if current["status"] in {"cancelling", "cancelled"}:
                    self.store.update("jobs", job_id, {"status": "cancelled", "finished_at": now(), "message": "已取消；部分输出不视为成功"})
                elif current["status"] == "running":
                    self.store.update("jobs", job_id, {"status": "failed", "finished_at": now(), "message": "执行进程提前退出", "error": f"进程退出码 {process.returncode}"})
            except Exception as exc:
                self.store.update("jobs", job_id, {"status": "failed", "finished_at": now(), "error": str(exc)[:1000]})
            finally:
                self.active.pop(job_id, None)
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()

    async def cancel(self, job_id):
        current = self.store.get("jobs", job_id)
        if current["status"] not in {"queued", "running", "cancelling"}:
            return current
        self.store.update("jobs", job_id, {"status": "cancelling"})
        process = self.active.get(job_id)
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 8)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        return self.store.update("jobs", job_id, {"status": "cancelled", "finished_at": now(), "message": "已取消，已有 checkpoint 保留"})

    async def close(self):
        self.closing = True
        for identifier in list(self.active):
            await self.cancel(identifier)
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

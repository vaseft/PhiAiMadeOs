"""One-use pairing to an independently authored RPE Next API-1 extension."""
from __future__ import annotations
import asyncio
import hashlib
import json
import secrets
import time
import zipfile
from pathlib import Path
from .formats import chart_to_ir, read_chart
from .services import create_candidate, reviewed, load_candidate
from .settings import new_id, now

EDITOR_ORIGINS = {"http://127.0.0.1:4173", "http://localhost:4173"}


class Bridge:
    def __init__(self, store):
        self.store = store
        self.pairs = {}
        self.websocket = None
        self.session_id = None
        self.snapshot_candidate_id = None
        self.editor_sha256 = None
        self.last_seen = None
        self.save_state = "NOT_CONNECTED"
        self.pending = {}

    def status(self):
        connected = self.websocket is not None and self.last_seen is not None and time.time() - self.last_seen < 45
        return {"connected": connected, "session_id": self.session_id, "candidate_id": self.snapshot_candidate_id,
            "last_seen": self.last_seen, "save_state": self.save_state, "pending_commands": len(self.pending),
            "detail": "编辑器模组实际连接" if connected else "尚未连接；API-1 桥接代码未经过编辑器实机验收", "verification": "NOT RUN"}

    def pair(self, candidate_id=None):
        if candidate_id:
            self.store.get("candidates", candidate_id)
        self.pairs = {k: v for k, v in self.pairs.items() if v["expires"] > time.time()}
        code = secrets.token_urlsafe(24)
        self.pairs[code] = {"expires": time.time() + 300, "candidate_id": candidate_id}
        return {"pairing_code": code, "expires_at": time.time() + 300, "ws_url": "ws://127.0.0.1:8765/api/v1/bridge/ws", "mod_download_url": "/api/v1/bridge/mod"}

    async def disconnect(self):
        ws = self.websocket
        self.websocket = None
        if ws:
            await ws.close(code=1000)
        for command in self.pending.values():
            self.store.update("bridge_commands", command["id"], {"status": "DISCONNECTED", "message": "连接已断开，未确认保存"})
        self.pending.clear()
        self.save_state = "DISCONNECTED"
        self.snapshot_candidate_id = None
        self.editor_sha256 = None
        self.last_seen = None

    async def connect(self, ws):
        if ws.headers.get("origin") not in EDITOR_ORIGINS:
            await ws.close(code=1008)
            return
        await ws.accept()
        session_id = None
        try:
            hello = await asyncio.wait_for(ws.receive_json(), 15)
            if hello.get("type") != "authenticate":
                raise ValueError("先输入一次性配对码")
            pair = self.pairs.pop(hello.get("pairing_code", ""), None)
            if not pair or pair["expires"] <= time.time():
                raise ValueError("配对码无效或已过期")
            await self.disconnect()
            session_id = new_id()
            self.websocket, self.session_id = ws, session_id
            self.last_seen, self.save_state = time.time(), "AWAITING_SNAPSHOT"
            await ws.send_json({"type": "authenticated", "session_id": session_id})
            while self.websocket is ws:
                message = await asyncio.wait_for(ws.receive_json(), 45)
                self.last_seen = time.time()
                if message.get("type") == "heartbeat":
                    if isinstance(message.get("editor_sha256"), str):
                        self.editor_sha256 = message["editor_sha256"]
                    await ws.send_json({"type": "heartbeat_ack"})
                elif message.get("type") == "snapshot":
                    if self.snapshot_candidate_id and self.save_state != "AWAITING_SNAPSHOT":
                        raise ValueError("一个配对会话只接收一次基线快照，请重新配对")
                    serialized = message.get("serialized_chart")
                    if not isinstance(serialized, str) or len(serialized.encode()) > 32 * 1024 * 1024:
                        raise ValueError("编辑器快照超过大小限额")
                    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                    if digest != message.get("editor_sha256"):
                        raise ValueError("编辑器快照哈希不匹配")
                    source = self.store.get("candidates", pair["candidate_id"]) if pair.get("candidate_id") else None
                    conditions = source["conditions"] if source else {"chart_mode": "regular", "key_count": None}
                    temp_path = self.store.settings.data_dir / "charts" / (new_id() + ".json")
                    temp_path.write_text(serialized, encoding="utf-8")
                    try:
                        chart = read_chart(temp_path)
                    finally:
                        temp_path.unlink(missing_ok=True)
                    chart_to_ir(chart, conditions.get("chart_mode", "regular"), conditions.get("key_count"))
                    candidate = create_candidate(chart, conditions, source.get("music_asset_id") if source else None, source="editor_snapshot",
                        manifest={"editor_session_id": session_id, "editor_raw_sha256": digest, "upstream_commit": "740fe7ebaa04506f26fdec4e37794f97da1fcf4d"}, store=self.store)
                    self.snapshot_candidate_id, self.editor_sha256 = candidate["id"], digest
                    self.save_state = "SNAPSHOT_RECEIVED"
                    await ws.send_json({"type": "snapshot_received", "candidate_id": candidate["id"], "message": "请在工作台审阅此快照的修订"})
                elif message.get("type") == "ack":
                    command_id = message.get("command_id")
                    command = self.pending.pop(command_id, None)
                    if not command:
                        continue
                    status = message.get("status")
                    if status not in {"SAVED", "CONFLICT", "NEEDS_SAVE", "FAILED"}:
                        raise ValueError("未知编辑器确认状态")
                    self.save_state = status
                    self.editor_sha256 = message.get("editor_sha256", self.editor_sha256)
                    self.store.update("bridge_commands", command_id, {"status": status, "message": str(message.get("message", ""))[:1000], "finished_at": now()})
                    self.store.event("bridge.editor_ack", command_id, status=status, session_id=session_id)
        except Exception as exc:
            try:
                await ws.send_json({"type": "error", "message": str(exc)[:500]})
            except Exception:
                pass
        finally:
            if self.websocket is ws:
                self.websocket = None
                self.save_state = "DISCONNECTED"
                for command in self.pending.values():
                    self.store.update("bridge_commands", command["id"], {"status": "DISCONNECTED", "message": "连接中断，未确认保存"})
                self.pending.clear()
            try:
                await ws.close()
            except Exception:
                pass

    async def send(self, candidate_id, expected_sha256):
        candidate, chart = reviewed(candidate_id, self.store)
        if candidate["chart_sha256"] != expected_sha256:
            raise ValueError("候选版本冲突")
        if not self.status()["connected"] or not self.snapshot_candidate_id:
            raise ValueError("请先在 RPE Next 模组中完成配对并读取快照")
        if self.pending:
            raise ValueError("上一保存命令尚未确认")
        if candidate.get("manifest", {}).get("editor_session_id") != self.session_id:
            raise ValueError("只允许回写同一编辑器快照的修订；请先手动将草稿导入编辑器并重新配对")
        cursor = candidate
        while cursor["id"] != self.snapshot_candidate_id and cursor.get("parent_id"):
            cursor = self.store.get("candidates", cursor["parent_id"])
        if cursor["id"] != self.snapshot_candidate_id:
            raise ValueError("候选不属于当前编辑器快照的修订链")
        # Compare to the source snapshot, not a moving heartbeat, to protect unsent human edits.
        base = self.store.get("candidates", self.snapshot_candidate_id)
        expected_editor = base["manifest"]["editor_raw_sha256"]
        if self.editor_sha256 != expected_editor:
            raise ValueError("编辑器内容已改变；请重新配对，不能覆盖手工编辑")
        record = self.store.put("bridge_commands", {"candidate_id": candidate_id, "session_id": self.session_id, "status": "QUEUED", "expected_editor_sha256": expected_editor})
        self.pending[record["id"]] = record
        await self.websocket.send_json({"type": "apply", "command_id": record["id"], "expected_editor_sha256": expected_editor, "chart": {k: v for k, v in chart.items() if k != "_pamos_import"}, "candidate_sha256": candidate["chart_sha256"]})
        self.save_state = "QUEUED"
        return {"command_id": record["id"], "status": "QUEUED"}

    def package(self):
        directory = self.store.settings.root / "extensions/rpe-next-bridge"
        names = ("mod.json", "index.mjs", "README.md")
        digest = hashlib.sha256(b"".join((directory / name).read_bytes() for name in names)).hexdigest()
        target = self.store.settings.root / ".local" / ("pamos-bridge-" + digest[:16] + ".rpenmod")
        if target.exists():
            return target
        with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.write(directory / name, name)
        return target

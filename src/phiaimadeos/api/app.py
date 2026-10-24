from __future__ import annotations
from contextlib import asynccontextmanager
import json
import math
import mimetypes
from pathlib import Path
import secrets
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .. import __version__
from ..settings import get_settings, atomic_json, file_hash, new_id, now
from ..store import Store
from ..jobs import Jobs
from ..bridge import Bridge
from ..llm import LLMSettings
from ..conditions import normalize
from ..services import rights, load_candidate, create_candidate, cached_analysis, record_review, reviewed, family_history
from ..formats import read_chart, chart_to_ir, chart_hash, export_package
from .. import patches
from ..preview import TimelineCache

BASELINE = {"id": "baseline-v1", "name": "规则基线（未训练）", "status": "baseline_only", "available": True, "supported_modes": ["regular", "pure_keys"], "key_counts": [4, 5, 6], "verification": "NOT RUN", "stages": {}}
ORIGINS = {"http://127.0.0.1:8765", "http://localhost:8765", "http://127.0.0.1:5173", "http://localhost:5173"}


def create_app():
    settings = get_settings()
    store = Store(settings)
    jobs = Jobs(store)
    bridge = Bridge(store)
    llm = LLMSettings()
    timeline_cache = TimelineCache(store)
    session = secrets.token_urlsafe(36)
    mcp_token_path = settings.root / ".local/mcp-client-token"
    mcp_token = secrets.token_urlsafe(36)
    mcp_token_path.write_text(mcp_token, encoding="utf-8")

    @asynccontextmanager
    async def lifespan(app):
        jobs.recover()
        yield
        await bridge.disconnect()
        await jobs.close()
        mcp_token_path.unlink(missing_ok=True)

    app = FastAPI(title="PhiAiMadeOs 本地工作台", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.store, app.state.jobs = store, jobs

    @app.middleware("http")
    async def protect(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/v1/"):
            origin = request.headers.get("origin")
            if origin and origin not in ORIGINS:
                return JSONResponse({"detail": {"code": "ORIGIN_DENIED", "message": "仅允许工作台同源访问"}}, 403)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": {"code": "INVALID_LENGTH", "message": "无效请求长度"}}, 400)
            maximum_body = (270 if path in {"/api/v1/assets/music", "/api/v1/imports/chart"} else 2) * 1024 * 1024
            if length > maximum_body:
                return JSONResponse({"detail": {"code": "TOO_LARGE", "message": "上传超过大小限额"}}, 413)
            original_receive = request._receive
            bytes_received = 0
            async def bounded_receive():
                nonlocal bytes_received
                message = await original_receive()
                bytes_received += len(message.get("body", b""))
                if bytes_received > maximum_body:
                    raise ValueError("请求正文超过本机大小限额")
                return message
            request._receive = bounded_receive
            is_mcp = secrets.compare_digest(request.headers.get("x-pamos-mcp-token", ""), mcp_token)
            is_session = secrets.compare_digest(request.cookies.get("pamos_session", ""), session)
            if path != "/api/v1/session" and not (is_session or is_mcp):
                return JSONResponse({"detail": {"code": "SESSION_REQUIRED", "message": "请先打开本机工作台建立会话"}}, 401)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                if is_mcp:
                    # MCP can propose and commit a separately human-approved diff, never approve, review, pair, configure credentials or train.
                    permitted = (path.endswith("/proposals") or (path.startswith("/api/v1/proposals/") and path.endswith("/commit")))
                    if not permitted:
                        return JSONResponse({"detail": {"code": "HUMAN_ACTION_REQUIRED", "message": "该动作需要工作台人工操作"}}, 403)
                elif not secrets.compare_digest(request.headers.get("x-pamos-token", ""), session):
                    return JSONResponse({"detail": {"code": "TOKEN_REQUIRED", "message": "会话令牌无效，请刷新"}}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": {"code": "INVALID_OPERATION", "message": str(exc)}}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": {"code": "NOT_FOUND", "message": str(exc)}}, status_code=404)

    @app.get("/api/v1/session")
    async def establish_session(request: Request):
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, {"code": "ORIGIN_DENIED", "message": "跨站会话请求被拒绝"})
        response = JSONResponse({"csrf_token": session})
        response.set_cookie("pamos_session", session, httponly=True, samesite="strict", secure=False)
        return response

    @app.get("/api/v1/status")
    async def status():
        hardware_path = settings.root / "runs/environment.json"
        hardware = json.loads(hardware_path.read_text(encoding="utf-8")) if hardware_path.exists() else {"status": "NOT MEASURED"}
        return {"version": __version__, "counts": {k: len(store.list(k)) for k in ("assets", "charts", "candidates", "datasets", "models")}, "hardware": hardware, "jobs": store.list("jobs"),
            "capabilities": capabilities(), "verification": "本轮未运行测试；功能代码待验收", "root": str(settings.root)}

    @app.get("/api/v1/capabilities")
    def capabilities():
        return {"modes": [{"id": "regular", "available": True}, {"id": "pure_keys", "available": True, "key_counts": [4, 5, 6]}, {"id": "anomaly", "available": False, "reason": "缺少目标客户端特性探针证据"}],
            "special_features": [], "live_bridge": {"implemented": True, "verified": False, "status": bridge.status()}, "noise_write": False, "verification": "NOT RUN"}

    @app.get("/api/v1/assets")
    def assets():
        return {"items": store.list("assets")}

    async def save_upload(upload, directory, allowed, maximum):
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in allowed:
            raise ValueError("文件类型不受支持")
        identifier = new_id()
        path = settings.data_dir / directory / (identifier + suffix)
        size = 0
        try:
            with path.open("xb") as handle:
                while block := await upload.read(1024 * 1024):
                    size += len(block)
                    if size > maximum:
                        raise ValueError("文件超过大小限额")
                    handle.write(block)
            if not size:
                raise ValueError("不能导入空文件")
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        return identifier, path, size

    @app.post("/api/v1/assets/music")
    async def upload_music(file: UploadFile = File(...), license_status: str = Form("unknown"), allowed_actions: str = Form('["local_research"]')):
        from ..audio import probe_audio
        permission = rights(license_status, json.loads(allowed_actions))
        name = Path(file.filename or "音乐").name[:160]
        identifier, path, size = await save_upload(file, "assets", {".mp3", ".flac", ".ogg", ".wav", ".m4a", ".aac"}, 200 * 1024 * 1024)
        try:
            import asyncio
            info = await asyncio.to_thread(probe_audio, path)
            asset = store.put("assets", {"id": identifier, "name": name, "path": settings.relative(path), "sha256": file_hash(path), "size": size,
                "duration_s": info.get("duration_s", info.get("duration")), "sample_rate": info.get("sample_rate"), "channels": info.get("channels"), "analysis_path": None, **permission})
        except Exception:
            path.unlink(missing_ok=True)
            raise
        store.event("asset.imported", identifier, sha256=asset["sha256"], **permission)
        return asset

    @app.patch("/api/v1/assets/{asset_id}/license")
    def asset_license(asset_id: str, payload: dict):
        permission = rights(payload.get("license_status"), payload.get("allowed_actions", []))
        record = store.update("assets", asset_id, {**permission, "source_reference": str(payload.get("source_reference", ""))[:2000]})
        store.event("asset.license_changed", asset_id, **permission)
        return record

    @app.post("/api/v1/assets/{asset_id}/analyze")
    async def analyze(asset_id: str):
        store.get("assets", asset_id)
        return jobs.submit("analysis", {"music_asset_id": asset_id})

    @app.get("/api/v1/assets/{asset_id}/audio")
    def audio(asset_id: str):
        asset = store.get("assets", asset_id)
        path = settings.path(asset["path"])
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    @app.get("/api/v1/assets/{asset_id}/waveform")
    def waveform(asset_id: str):
        asset = store.get("assets", asset_id)
        analysis = cached_analysis(asset, settings)
        if not analysis or not analysis.get("waveform_path"):
            return {"peaks": [], "duration_s": asset.get("duration_s"), "status": "NOT_ANALYZED"}
        result = json.loads(settings.path(analysis["waveform_path"]).read_text(encoding="utf-8"))
        result["onsets_s"] = analysis.get("onsets_s", [])
        result["beat_times_s"] = analysis.get("beat_times_s", [])
        result["bpm"] = analysis.get("bpm")
        result["tempo"] = analysis.get("tempo")
        result["warnings"] = analysis.get("warnings", [])
        return result

    @app.post("/api/v1/imports/chart")
    async def import_chart(file: UploadFile = File(...), music_asset_id: str | None = Form(None), chart_mode: str = Form("regular"), key_count: str | None = Form(None),
        difficulty_class: str = Form("IN"), difficulty_value: int = Form(14), license_status: str = Form("unknown"), allowed_actions: str = Form('["local_research"]')):
        permission = rights(license_status, json.loads(allowed_actions))
        if music_asset_id:
            store.get("assets", music_asset_id)
        k = int(key_count) if key_count not in (None, "", "null") else None
        name = Path(file.filename or "谱面").name[:160]
        identifier, original, size = await save_upload(file, "charts", {".json", ".pez", ".zip"}, 256 * 1024 * 1024)
        try:
            import asyncio
            chart = await asyncio.to_thread(read_chart, original)
            ir = chart_to_ir(chart, chart_mode, k)
            normalized = settings.data_dir / "charts" / identifier / "chart.json"
            atomic_json(normalized, chart)
            record = store.put("charts", {"id": identifier, "name": name, "path": settings.relative(normalized), "original_path": settings.relative(original), "original_sha256": file_hash(original), "sha256": file_hash(normalized),
                "music_asset_id": music_asset_id, "chart_mode": chart_mode, "key_count": k, "difficulty_class": difficulty_class, "difficulty_value": difficulty_value, "source_type": original.suffix,
                "warnings": ir.get("warnings", []), "human_verified_alignment": False, **permission})
            candidate = create_candidate(chart, {"chart_mode": chart_mode, "key_count": k, "difficulty_class": difficulty_class, "difficulty_value": difficulty_value}, music_asset_id, source="import", manifest={"chart_asset_id": identifier, "source_sha256": record["original_sha256"]}, store=store)
            return {**record, "candidate_id": candidate["id"]}
        except Exception:
            original.unlink(missing_ok=True)
            raise

    @app.get("/api/v1/charts")
    def charts():
        return {"items": store.list("charts")}

    @app.patch("/api/v1/charts/{chart_id}/labels")
    def chart_labels(chart_id: str, payload: dict):
        previous = store.get("charts", chart_id)
        allowed = {"chart_mode", "key_count", "difficulty_class", "difficulty_value", "license_status", "allowed_actions", "human_verified_alignment", "group_id", "performance_intensity", "performance_style", "wildness", "music_asset_id"}
        if set(payload) - allowed:
            raise ValueError("不支持的标签字段")
        value = {**previous, **payload}
        permission = rights(value["license_status"], value["allowed_actions"])
        if value.get("music_asset_id"):
            store.get("assets", value["music_asset_id"])
        if previous.get("import_status") == "archived_only":
            if value["chart_mode"] != previous["chart_mode"] or value.get("key_count") != previous.get("key_count"):
                raise ValueError("仅存档的未支持格式不能更改解析模式；原件与来源标签保留")
        else:
            chart_to_ir(read_chart(settings.path(value["path"])), value["chart_mode"], value.get("key_count"))
        ranges = {"EZ": (0, 10), "HD": (11, 14), "IN": (14, 17), "AT": (15, 18)}
        bounds = ranges.get(value["difficulty_class"])
        unlabelled = value["difficulty_class"] is None and value["difficulty_value"] is None
        if not unlabelled and (not bounds or type(value["difficulty_value"]) is not int or not bounds[0] <= value["difficulty_value"] <= bounds[1]):
            raise ValueError("难度标签不符合 EZ/HD/IN/AT 范围")
        for field in ("performance_intensity", "wildness"):
            v = value.get(field)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100):
                raise ValueError(f"{field} 需要为空或 0..100 数值")
        if value.get("performance_style") not in {None, "none", "calm", "standard", "rhythm_linked", "ornate", "experimental"}:
            raise ValueError("演出风格标签无效")
        if value.get("chart_mode") == "pure_keys" and (value.get("performance_intensity") not in {None, 0} or value.get("performance_style") not in {None, "none"}):
            raise ValueError("固定 K 的已知演出标签必须为 0 / none")
        if "group_id" in payload and isinstance(payload["group_id"], str):
            payload["group_id"] = payload["group_id"].strip() or None
            value["group_id"] = payload["group_id"]
        if value.get("group_id") is not None and (not isinstance(value["group_id"], str) or not 1 <= len(value["group_id"].strip()) <= 256):
            raise ValueError("歌曲簇 ID 需要 1..256 个字符")
        if "group_id" in payload and payload["group_id"] != previous.get("group_id"):
            payload["group_method"] = "human_song_cluster" if payload["group_id"] else None
        record = store.update("charts", chart_id, {**payload, **permission})
        store.event("chart.labels_changed", chart_id, changed_fields=sorted(payload))
        return record

    @app.get("/api/v1/models")
    def models():
        return {"items": [BASELINE, *store.list("models")]}

    @app.post("/api/v1/generation-conditions/normalize")
    def normalize_request(payload: dict):
        return normalize(payload)

    @app.post("/api/v1/generations")
    async def generation(payload: dict):
        conditions = normalize(payload)["effective_conditions"]
        store.get("assets", conditions["music_asset_id"])
        model_id = conditions["model_bundle_id"]
        if model_id == "baseline-v1":
            return jobs.submit("generation", conditions)
        model = store.get("models", model_id)
        if not model.get("available"):
            raise ValueError("模型权重不可用")
        return jobs.submit("learned_generation", conditions)

    @app.get("/api/v1/jobs")
    def job_list():
        return {"items": store.list("jobs")}

    @app.get("/api/v1/jobs/{job_id}")
    def job(job_id: str):
        record = store.get("jobs", job_id)
        if record.get("log_path"):
            path = settings.path(record["log_path"])
            if path.exists():
                with path.open("rb") as handle:
                    handle.seek(max(0, path.stat().st_size - 12000))
                    record["logs"] = handle.read().decode("utf-8", errors="replace")
        return record

    @app.post("/api/v1/jobs/{job_id}/cancel")
    async def cancel(job_id: str):
        return await jobs.cancel(job_id)

    @app.get("/api/v1/candidates")
    def candidates():
        return {"items": store.list("candidates")}

    @app.get("/api/v1/candidates/{candidate_id}")
    def candidate(candidate_id: str):
        return store.get("candidates", candidate_id)

    @app.get("/api/v1/candidates/{candidate_id}/timeline")
    def timeline(candidate_id: str, start_s: float = 0, end_s: float = 30):
        if not math.isfinite(start_s) or not math.isfinite(end_s) or start_s < 0 or not start_s < end_s <= start_s + 300:
            raise ValueError("预览窗口须为有限 0..300 秒范围")
        return timeline_cache.window(candidate_id, start_s, end_s)

    @app.get("/api/v1/candidates/{candidate_id}/chart")
    def chart_download(candidate_id: str):
        record, _ = load_candidate(candidate_id, store)
        return FileResponse(settings.path(record["chart_path"]), media_type="application/json", filename=f"PAMOs-{candidate_id[:8]}-{record['status']}.json")

    @app.post("/api/v1/candidates/{candidate_id}/audit")
    async def audit(candidate_id: str):
        store.get("candidates", candidate_id)
        return jobs.submit("audit", {"candidate_id": candidate_id})

    @app.get("/api/v1/candidates/{candidate_id}/audit")
    def get_audit(candidate_id: str):
        record = store.get("candidates", candidate_id)
        if not record.get("audit_id"):
            return {"status": "NOT_RUN", "issues": [], "metrics": {}, "engine_version": None}
        return store.get("audits", record["audit_id"])

    @app.post("/api/v1/candidates/{candidate_id}/reviews")
    def review(candidate_id: str, payload: dict):
        return record_review(candidate_id, payload, store)

    @app.get("/api/v1/candidates/{candidate_id}/history")
    def history(candidate_id: str):
        store.get("candidates", candidate_id)
        return family_history(candidate_id, store)

    @app.post("/api/v1/candidates/{candidate_id}/revert")
    def revert(candidate_id: str, payload: dict):
        target_id = payload.get("target_candidate_id", payload.get("version_id", candidate_id))
        family = {v["id"] for v in family_history(candidate_id, store)["versions"]}
        if target_id not in family:
            raise ValueError("只能回滚同一版本链的候选")
        target, chart = load_candidate(target_id, store)
        revision = create_candidate(chart, target["conditions"], target.get("music_asset_id"), candidate_id, "revert", {**target["manifest"], "reverted_from": target_id}, store)
        return {"candidate_id": revision["id"], "candidate": revision}

    @app.post("/api/v1/candidates/{candidate_id}/proposals")
    def propose(candidate_id: str, payload: dict):
        return patches.propose(candidate_id, payload, store=store)

    @app.get("/api/v1/proposals/{proposal_id}")
    def proposal(proposal_id: str):
        return store.get("proposals", proposal_id)

    @app.post("/api/v1/proposals/{proposal_id}/approve")
    def approve(proposal_id: str):
        return patches.approve(proposal_id, store)

    @app.post("/api/v1/proposals/{proposal_id}/commit")
    def commit(proposal_id: str):
        return patches.commit(proposal_id, store)

    @app.post("/api/v1/candidates/{candidate_id}/exports")
    def export(candidate_id: str, payload: dict):
        record, chart = reviewed(candidate_id, store)
        purpose = payload.get("purpose", "local")
        if purpose not in {"local", "distribution"} or payload.get("include_audio", True) is not True:
            raise ValueError("目前导出包含音乐；用途必须为 local/distribution")
        asset = store.get("assets", record["music_asset_id"])
        if file_hash(settings.path(asset["path"])) != asset["sha256"]:
            raise ValueError("音乐文件与审核时登记版本不符")
        permission_action = "distribution" if purpose == "distribution" else "local_research"
        sources = [asset]
        chart_asset_id = record.get("manifest", {}).get("chart_asset_id")
        if chart_asset_id:
            sources.append(store.get("charts", chart_asset_id))
        if any(permission_action not in s.get("allowed_actions", []) or (purpose == "distribution" and s.get("license_status") != "explicit_permitted") for s in sources):
            raise ValueError("素材许可不允许所选导出用途")
        identifier = new_id()
        target = settings.data_dir / "exports" / (identifier + ".zip")
        from ..services import export_audio
        music_path = export_audio(asset, store)
        result = export_package(chart, music_path, target, {"name": asset["name"], "level": str(record["conditions"].get("difficulty_value", "")), "charter": "PAMOs / 人工审核", "purpose": purpose,
            "conditions": record["conditions"], "chart_mode": record["chart_mode"], "key_count": record.get("key_count"), "audit_id": record["audit_id"], "review_id": record["review_id"], "chart_sha256": record["chart_sha256"]})
        exported = store.put("exports", {"id": identifier, "candidate_id": candidate_id, "path": settings.relative(target), "sha256": file_hash(target), "purpose": purpose, "manifest": result,
            "source_music_sha256": asset["sha256"], "export_music_sha256": file_hash(music_path), "audio_conversion": "decoded_to_flac" if music_path != settings.path(asset["path"]) else "original"}, immutable=True)
        return {**exported, "download_url": f"/api/v1/exports/{identifier}/download"}

    @app.get("/api/v1/exports/{export_id}/download")
    def download_export(export_id: str):
        exported = store.get("exports", export_id)
        return FileResponse(settings.path(exported["path"]), media_type="application/zip", filename="PAMOs-" + export_id[:8] + ".zip")

    @app.post("/api/v1/candidates/{candidate_id}/playtests")
    def playtest(candidate_id: str, payload: dict):
        record, _ = load_candidate(candidate_id, store)
        for field in ("reviewer", "engine_version", "platform"):
            if not str(payload.get(field, "")).strip():
                raise ValueError("试玩记录必须由真人填写审核人、引擎版本和平台")
        if type(payload.get("passed")) is not bool:
            raise ValueError("请明确填写真实试玩是否通过")
        return store.put("playtests", {"candidate_id": candidate_id, "chart_sha256": record["chart_sha256"], **{k: str(payload[k])[:3000] for k in ("reviewer", "engine_version", "platform")}, "passed": payload["passed"], "notes": str(payload.get("notes", ""))[:10000], "source": "human_report"}, immutable=True)

    @app.get("/api/v1/datasets")
    def datasets():
        return {"items": store.list("datasets")}

    @app.post("/api/v1/datasets")
    async def create_dataset(payload: dict):
        ids = payload.get("chart_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 5000 or len(set(ids)) != len(ids):
            raise ValueError("请选择 1..5000 个不同的谱面")
        return jobs.submit("dataset", {"chart_ids": ids, "seed": int(payload.get("seed", 42))})

    @app.get("/api/v1/training/runs")
    def training_runs():
        # Disk manifests include interrupted/failed runs that never reached the registry.
        indexed = {r.get("run_id", r["id"]): r for r in store.list("training_runs")}
        for path in (settings.data_dir / "training").glob("*/run_manifest.json"):
            if path.stat().st_size > 8 * 1024 * 1024:
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("metrics_path"):
                    metric_path = settings.path(record["metrics_path"])
                    if metric_path.is_file():
                        with metric_path.open("rb") as handle:
                            handle.seek(max(0, metric_path.stat().st_size - 128000))
                            lines = handle.read().decode("utf-8", errors="replace").splitlines()
                        events = []
                        for line in lines:
                            try:
                                events.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                        record["recent_metrics"] = events[-200:]
                        record["loss_history"] = [e["loss"] for e in events if isinstance(e.get("loss"), (int, float))][-200:]
                if record.get("job_id"):
                    job = store.get("jobs", record["job_id"])
                    record["job_status"] = job["status"]
                    if job["status"] in {"cancelled", "interrupted", "failed"}:
                        record["display_state"] = job["status"]
                        record["checkpoint_training_state"] = record.get("training_state")
                        record["training_state"] = job["status"]
                indexed[record.get("run_id", record["id"])] = record
            except (ValueError, OSError, KeyError):
                continue
        return {"items": sorted(indexed.values(), key=lambda r: r.get("created_at", ""), reverse=True)}

    @app.post("/api/v1/training/runs")
    async def training(payload: dict):
        store.get("datasets", payload.get("dataset_id"))
        if payload.get("stage") not in {"note_rhythm", "line_motion", "placement", "all"}:
            raise ValueError("未知训练阶段")
        if type(payload.get("epochs")) is not int or not 1 <= payload["epochs"] <= 1000:
            raise ValueError("训练轮数须为 1..1000")
        if payload.get("device", "cuda") not in {"cpu", "cuda"} or payload.get("grad_accum", 16) not in range(1, 129):
            raise ValueError("训练设备或梯度累积设置无效")
        return jobs.submit("training", payload)

    @app.post("/api/v1/models/{model_id}/promote")
    def promote(model_id: str, payload: dict):
        model = store.get("models", model_id)
        target = payload.get("status")
        evidence = str(payload.get("evidence", "")).strip()
        if target not in {"candidate", "stable"} or not evidence:
            raise ValueError("需要有效目标状态与人工证据")
        accepted = []
        for candidate in store.list("candidates"):
            if candidate.get("manifest", {}).get("model_bundle_id") != model_id:
                continue
            try:
                reviewed(candidate["id"], store)
            except ValueError:
                continue
            if any(p["candidate_id"] == candidate["id"] and p["chart_sha256"] == candidate["chart_sha256"] and p["passed"] for p in store.list("playtests")):
                accepted.append(candidate)
        if not accepted:
            raise ValueError("尚无此模型当前候选的审计、人工通过及真实试玩证据")
        if target == "stable":
            modes = model.get("bundle", {}).get("supported_modes", ["regular", "pure_keys"])
            required = {(m, k) for m in modes for k in (model.get("bundle", {}).get("key_counts", [4, 5, 6]) if m == "pure_keys" else [None])}
            covered = {(c["chart_mode"], c.get("key_count")) for c in accepted}
            if not required <= covered or len(accepted) < 3:
                raise ValueError("stable 需要覆盖声明模式/K 数并至少三份人工及实机验收")
        result = store.update("models", model_id, {"status": target, "promotion_evidence": evidence, "accepted_candidate_ids": [c["id"] for c in accepted]})
        store.event("model.promoted", model_id, status=target, accepted_candidate_ids=result["accepted_candidate_ids"])
        return result

    @app.get("/api/v1/settings/llm")
    def get_llm():
        return llm.public()

    @app.put("/api/v1/settings/llm")
    def set_llm(payload: dict):
        return llm.update(payload)

    @app.post("/api/v1/candidates/{candidate_id}/postprocess")
    async def postprocess(candidate_id: str, payload: dict):
        if payload.get("confirm_external_upload") is not True or payload.get("mode", "suggest") not in {"suggest", "human_select"}:
            raise ValueError("外部 API 只可在确认后生成待人工选择的局部建议")
        store.get("candidates", candidate_id)
        return jobs.submit("postprocess", {**{k: payload[k] for k in ("beat_window", "instruction", "confirm_external_upload", "mode") if k in payload}, "candidate_id": candidate_id}, secret=llm.secret())

    @app.get("/api/v1/bridge/status")
    def bridge_status():
        return bridge.status()

    @app.post("/api/v1/bridge/pair")
    def pair_bridge(payload: dict):
        return bridge.pair(payload.get("candidate_id"))

    @app.post("/api/v1/bridge/disconnect")
    async def disconnect_bridge():
        await bridge.disconnect()
        return bridge.status()

    @app.get("/api/v1/bridge/mod")
    def mod():
        return FileResponse(bridge.package(), media_type="application/zip", filename="PAMOs-Bridge.rpenmod")

    @app.post("/api/v1/bridge/candidates/{candidate_id}/send")
    async def bridge_send(candidate_id: str, payload: dict):
        return await bridge.send(candidate_id, payload.get("expected_chart_sha256"))

    @app.websocket("/api/v1/bridge/ws")
    async def bridge_ws(ws: WebSocket):
        await bridge.connect(ws)

    dist = settings.root / "web/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="workbench")
    else:
        @app.get("/")
        def missing_build():
            return JSONResponse({"message": "工作台前端尚未构建；请运行 Install-PAMOs.cmd 或在 web 执行 npm ci && npm run build", "verification": "NOT RUN"}, status_code=503)
    return app

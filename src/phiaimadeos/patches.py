"""Small, hash-bound chart proposals; approval and commit are separate actions."""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import math
import re
from datetime import datetime, timedelta, timezone
from .formats import beat_fraction, beat_triplet, chart_to_ir, ir_to_chart, chart_hash, lane_centers, noise_snapshot
from .services import load_candidate, create_candidate, run_audit, cached_analysis
from .settings import atomic_json, new_id, now
from .store import Store


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("patch 数值必须有限")
    return value


def _beat(value):
    if isinstance(value, (int, float)):
        _number(value)
        return Fraction(str(value))
    return beat_fraction(value)


def adapt_operation(operation, ir):
    """Explicit adapter for the old offline MCP vocabulary, never generic JSON Patch."""
    op = deepcopy(operation)
    legacy = {"SHIFT_NOTE_BEATS": "MOVE_NOTE_TIME", "SET_NOTE_X": "MOVE_NOTE_X", "SET_NOTE_TYPE": "CHANGE_NOTE_KIND", "SET_HOLD_END": "CHANGE_HOLD_END", "MOVE_NOTE_LANE": "MOVE_NOTE_LANE"}
    if op.get("op") in legacy and "target_id" not in op:
        ref = op.get("note_ref", op.get("target"))
        match = re.fullmatch(r"l(\d+):n(\d+)", str(ref))
        if not match:
            raise ValueError("旧 MCP note_ref 必须为 l0:n0")
        line_index, note_index = map(int, match.groups())
        targets = [n for n in ir["notes"] if n["line_id"] == f"line_{line_index}"]
        if note_index >= len(targets):
            raise ValueError("旧 note_ref 不存在")
        target = targets[note_index]
        old = op["op"]
        value = op.get("value")
        if old == "SHIFT_NOTE_BEATS":
            payload = {"new_start_beat": beat_triplet(_beat(target["beat"]) + _beat(value))}
        elif old == "SET_NOTE_X":
            payload = {"new_x": value}
        elif old == "SET_NOTE_TYPE":
            payload = {"new_kind": {1: "TAP", 2: "HOLD", 3: "FLICK", 4: "DRAG"}.get(value, value)}
        elif old == "SET_HOLD_END":
            payload = {"new_end_beat": value}
        else:
            payload = {"new_lane_index": value}
        return {"op": legacy[old], "target_id": target["id"], "payload": payload, "adapter": "offline-mcp-v1-to-v4"}
    return op


def apply_operations(chart, conditions, operations, window):
    ir = chart_to_ir(chart, conditions.get("chart_mode", "regular"), conditions.get("key_count"))
    if any(value for value in noise_snapshot(chart).values()):
        raise ValueError("含噪域的谱面仅允许只读导入，当前禁止自动 patch")
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError("必须指定局部 beat_window")
    left, right = map(_beat, window)
    if left < 0 or right <= left or right - left > 16:
        raise ValueError("局部修改范围最多 16 拍且不得早于零拍")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 12:
        raise ValueError("每份建议必须包含 1..12 个操作")
    operations = [adapt_operation(op, ir) for op in operations]
    used = set()
    changes = []
    for operation in operations:
        op = operation.get("op")
        target_id = operation.get("target_id")
        payload = operation.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是对象")
        if (op, target_id) in used:
            raise ValueError("同一目标的同类操作不能重复")
        used.add((op, target_id))
        notes = {n["id"]: n for n in ir["notes"]}
        if len(notes) != len(ir["notes"]):
            raise ValueError("源谱面音符 ID 重复，不能安全修改")
        if op == "ADD_NOTE":
            b = _beat(payload.get("start_beat"))
            if not left <= b <= right:
                raise ValueError("新增音符超出修改窗口")
            line_id = payload.get("line_id", "line_0")
            if line_id not in {l["id"] for l in ir["judge_lines"]}:
                raise ValueError("新增音符所属判定线不存在")
            kind = str(payload.get("kind", "TAP")).upper()
            if kind not in {"TAP", "FLICK", "DRAG", "HOLD"}:
                raise ValueError("音符类型无效")
            end = _beat(payload.get("end_beat", payload.get("start_beat")))
            if end < b or end > right or (kind == "HOLD" and end == b):
                raise ValueError("新增 Hold 尾部必须在窗口内且晚于头部")
            lane = payload.get("lane_index")
            if conditions.get("chart_mode") == "pure_keys":
                centers = lane_centers(conditions["key_count"])
                if type(lane) is not int or not 0 <= lane < len(centers):
                    raise ValueError("新增纯配置音符需要有效列")
                x = centers[lane]
            else:
                x = _number(payload.get("x", 0))
                if abs(x) > 675:
                    raise ValueError("新增音符超出局部横坐标范围")
            note = {"id": "pamos_" + new_id(), "line_id": line_id, "kind": kind, "beat": beat_triplet(b), "end_beat": beat_triplet(end if kind == "HOLD" else b), "x": x, "lane_index": lane, "above": 1, "fake": False,
                    "raw": {"alpha": 255, "size": 1, "speed": 1, "visibleTime": 999999, "yOffset": 0}}
            note["raw"]["pamosId"] = note["id"]
            ir["notes"].append(note)
            changes.append({"op": op, "target_id": note["id"], "before": None, "after": {k: v for k, v in note.items() if k != "raw"}})
            continue
        if op == "TUNE_LINE_EVENT":
            if conditions.get("chart_mode") == "pure_keys":
                raise ValueError("固定 K 模式禁止线运动修改")
            match = re.fullmatch(r"line_(\d+):layer_(\d+):(moveXEvents|moveYEvents|rotateEvents|alphaEvents):(\d+)", str(target_id))
            if not match:
                raise ValueError("线事件目标不在白名单")
            li, layer, event_kind, ei = match.groups()
            try:
                event = ir["judge_lines"][int(li)]["raw"]["eventLayers"][int(layer)][event_kind][int(ei)]
            except (KeyError, IndexError, TypeError):
                raise ValueError("线事件目标不存在") from None
            if not left <= _beat(event["startTime"]) <= _beat(event["endTime"]) <= right:
                raise ValueError("线事件须完整位于修改窗口")
            if not payload or set(payload) - {"start", "end", "easingType"}:
                raise ValueError("线事件仅可局部调整 start/end/easingType")
            before = deepcopy(event)
            for key, value in payload.items():
                value = _number(value)
                if key == "easingType":
                    if type(value) is not int or not 1 <= value <= 29:
                        raise ValueError("easingType 必须为 1..29")
                else:
                    limit = 30 if event_kind == "rotateEvents" else 50
                    if abs(value - event.get(key, 0)) > limit:
                        raise ValueError("线事件幅度超过局部调整上限")
                    if event_kind == "alphaEvents" and not 0 <= value <= 255:
                        raise ValueError("透明度须为 0..255")
                event[key] = value
            changes.append({"op": op, "target_id": target_id, "before": before, "after": deepcopy(event)})
            continue
        if op not in {"MOVE_NOTE_TIME", "CHANGE_NOTE_KIND", "MOVE_NOTE_X", "MOVE_NOTE_LANE", "CHANGE_HOLD_END", "REMOVE_NOTE"}:
            raise ValueError("操作不在白名单")
        if target_id not in notes:
            raise ValueError("音符目标不存在")
        note = notes[target_id]
        b, end = _beat(note["beat"]), _beat(note["end_beat"])
        if not left <= b <= right:
            raise ValueError("目标音符不在修改窗口")
        before = {k: deepcopy(v) for k, v in note.items() if k != "raw"}
        if op == "MOVE_NOTE_TIME":
            new = _beat(payload.get("new_start_beat"))
            if abs(new - b) > Fraction(1, 8) or not left <= new <= right or not left <= end + new - b <= right:
                raise ValueError("移时最多 ±1/8 拍，头尾必须在窗口内")
            note["beat"], note["end_beat"] = beat_triplet(new), beat_triplet(end + new - b)
        elif op == "CHANGE_NOTE_KIND":
            kind = str(payload.get("new_kind", "")).upper()
            if kind not in {"TAP", "FLICK", "DRAG"} or note["kind"] == "HOLD":
                raise ValueError("类型修改仅允许非 Hold 三类音符")
            note["kind"] = kind
        elif op == "MOVE_NOTE_X":
            if conditions.get("chart_mode") == "pure_keys":
                raise ValueError("固定 K 请使用 MOVE_NOTE_LANE")
            x = _number(payload.get("new_x"))
            if abs(x) > 675 or abs(x - note["x"]) > 120:
                raise ValueError("横向局部调整最多 120 RPE 单位，且在 ±675 内")
            note["x"] = x
        elif op == "MOVE_NOTE_LANE":
            if conditions.get("chart_mode") != "pure_keys":
                raise ValueError("仅固定 K 可调整列")
            lane = payload.get("new_lane_index")
            centers = lane_centers(conditions["key_count"])
            if type(lane) is not int or not 0 <= lane < len(centers):
                raise ValueError("列索引无效")
            note["lane_index"], note["x"] = lane, centers[lane]
        elif op == "CHANGE_HOLD_END":
            new = _beat(payload.get("new_end_beat"))
            if note["kind"] != "HOLD" or new <= b or abs(new - end) > Fraction(1, 8) or not left <= new <= right:
                raise ValueError("Hold 尾部只可在窗口内调整 ±1/8 拍且晚于头部")
            note["end_beat"] = beat_triplet(new)
        else:
            ir["notes"].remove(note)
        changes.append({"op": op, "target_id": target_id, "before": before, "after": None if op == "REMOVE_NOTE" else {k: deepcopy(v) for k, v in note.items() if k != "raw"}})
    result = ir_to_chart(ir)
    if noise_snapshot(result) != noise_snapshot(chart):
        raise ValueError("噪域只读保护阻止修改")
    return result, operations, changes


def propose(candidate_id, payload, source="human", store=None):
    from .audit import audit_chart
    store = store or Store()
    candidate, chart = load_candidate(candidate_id, store)
    if payload.get("expected_chart_sha256") != candidate["chart_sha256"]:
        raise ValueError("谱面版本冲突；建议不会应用")
    result, operations, diff = apply_operations(chart, candidate["conditions"], payload.get("operations"), payload.get("beat_window"))
    analysis = cached_analysis(store.get("assets", candidate["music_asset_id"])) if candidate.get("music_asset_id") else None
    validation = audit_chart(result, analysis, candidate["conditions"])
    identifier = new_id()
    path = store.settings.data_dir / "proposals" / identifier / "preview.json"
    atomic_json(path, result)
    record = store.put("proposals", {"id": identifier, "candidate_id": candidate_id, "base_chart_sha256": candidate["chart_sha256"], "preview_sha256": chart_hash(result),
        "preview_path": store.settings.relative(path), "operations": operations, "beat_window": payload["beat_window"], "diff": diff, "validation": validation,
        "status": "proposed", "source": source, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()})
    store.event("proposal.created", identifier, candidate_id=candidate_id, source=source, base_sha256=candidate["chart_sha256"])
    return record


def approve(proposal_id, store=None):
    store = store or Store()
    proposal = store.get("proposals", proposal_id)
    candidate, _ = load_candidate(proposal["candidate_id"], store)
    if datetime.fromisoformat(proposal["expires_at"]) <= datetime.now(timezone.utc):
        raise ValueError("建议已过期，请重新生成")
    if candidate["chart_sha256"] != proposal["base_chart_sha256"] or proposal["validation"]["status"] == "BLOCK":
        raise ValueError("版本不匹配或审计阻断，不能批准")
    result = store.update("proposals", proposal_id, {"status": "approved", "approved_at": now(), "approval_sha256": proposal["preview_sha256"]}, expected={"status": "proposed"})
    store.event("proposal.human_approved", proposal_id, preview_sha256=proposal["preview_sha256"])
    return result


def commit(proposal_id, store=None):
    store = store or Store()
    proposal = store.get("proposals", proposal_id)
    if proposal["status"] != "approved" or proposal.get("approval_sha256") != proposal["preview_sha256"]:
        raise ValueError("需要工作台人工批准当前 diff")
    if datetime.fromisoformat(proposal["expires_at"]) <= datetime.now(timezone.utc):
        raise ValueError("建议已过期")
    candidate, chart = load_candidate(proposal["candidate_id"], store)
    if candidate["chart_sha256"] != proposal["base_chart_sha256"]:
        raise ValueError("基线版本冲突")
    after, _, _ = apply_operations(chart, candidate["conditions"], proposal["operations"], proposal["beat_window"])
    if chart_hash(after) != proposal["preview_sha256"]:
        raise ValueError("预览内容发生变化，请重新审批")
    store.update("proposals", proposal_id, {"status": "committing"}, expected={"status": "approved"})
    try:
        revision = create_candidate(after, candidate["conditions"], candidate.get("music_asset_id"), candidate["id"], "patch", {**candidate["manifest"], "proposal_id": proposal_id}, store)
        audit = run_audit(revision["id"], store=store)
        store.update("proposals", proposal_id, {"status": "committed", "result_candidate_id": revision["id"]})
        return {"candidate_id": revision["id"], "audit": audit, "candidate": store.get("candidates", revision["id"])}
    except Exception:
        store.update("proposals", proposal_id, {"status": "failed", "message": "提交未完成；原始版本保持不变"})
        raise

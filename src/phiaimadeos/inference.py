"""Full-song learned inference. Absent/incompatible weights fail explicitly.

Only model predictions create events. Repairs enforce finite bounds, ordering,
fixed lanes and local occupancy; the separate audit remains authoritative for
screen geometry, client compatibility, and human playability.
"""
from __future__ import annotations

import copy
import gc
import math
from pathlib import Path
import random
import time

from .models import (ARCH_VERSION, FEATURE_RATE, KINDS, MAX_AUDIO_FRAMES,
                     MAX_LINES, MAX_NOTE_SLOTS, MOTION_PROPERTIES, MOTION_SCALES,
                     TIME_CELLS, POSITION_X_SCALE, ModelError, build_model, encode_conditions, model_config)
from ._model_data import (assert_no_noise, canonical_hash, feature_window,
                          file_hash, finite, line_vectors, load_features,
                          note_queries, motion_queries, note_vectors, relative_path, safe_path)


def _emit(callback, **event):
    if callback is not None:
        callback(event)


def _unavailable(message, **details):
    return ModelError("MODEL_UNAVAILABLE", message, **details)


def _resolve_analysis_path(root, value):
    if not isinstance(value, str):
        raise ModelError("FEATURE_UNAVAILABLE", "音频分析缺少真实特征文件。")
    path = Path(value)
    if path.is_absolute():
        if not path.resolve().is_relative_to(root):
            raise ModelError("UNSAFE_PATH", "音频特征不在项目受管理目录内。")
        value = path.resolve().relative_to(root).as_posix()
    return safe_path(root, value)


def _verify_bundle(bundle, conditions, analysis, root):
    if not isinstance(bundle, dict) or not isinstance(bundle.get("stages"), dict):
        raise _unavailable("没有完整学习式模型组合；请明确使用规则基线或先训练授权数据。")
    if bundle.get("arch_version") != ARCH_VERSION:
        raise _unavailable("模型架构版本与当前实现不一致。")
    if bundle.get("feature_version") != analysis.get("feature_version"):
        raise _unavailable("模型训练特征版本与音频缓存版本不一致。")
    mode = conditions["chart_mode"]
    if mode not in bundle.get("supported_modes", []):
        raise _unavailable("该模型没有所选模式的独立训练/验证覆盖。", chart_mode=mode)
    if mode == "pure_keys" and conditions["key_count"] not in bundle.get("key_counts", []):
        raise _unavailable("该模型没有所选 K 的独立训练/验证覆盖。")
    stages = ("note_rhythm", "placement") if mode == "pure_keys" else ("note_rhythm", "line_motion", "placement")
    capacities = set()
    verified = {}
    for stage in stages:
        metadata = bundle["stages"].get(stage)
        if not isinstance(metadata, dict) or metadata.get("training_state") != "complete":
            raise _unavailable("所需模型阶段没有完成真实训练。", stage=stage)
        config = metadata.get("config")
        try:
            expected = model_config(stage, config.get("max_lines")) if isinstance(config, dict) else None
        except ModelError as exc:
            raise _unavailable("模型阶段的判定线容量无效。", stage=stage) from exc
        if not isinstance(config, dict) or config != expected:
            raise _unavailable("模型阶段缺少一致的判定线容量与架构配置。", stage=stage)
        capacities.add(config["max_lines"])
        digest = metadata.get("checkpoint_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise _unavailable("模型权重没有完整 SHA-256 溯源。", stage=stage)
        try:
            path = safe_path(root, metadata.get("checkpoint_path"))
        except ModelError as exc:
            raise _unavailable("所需真实模型权重不存在或路径不安全。", stage=stage) from exc
        if file_hash(path) != digest:
            raise _unavailable("模型权重校验失败；拒绝加载。", stage=stage)
        if mode not in metadata.get("supported_modes", []):
            raise _unavailable("模型阶段不覆盖所选模式。", stage=stage)
        if mode == "pure_keys" and conditions["key_count"] not in metadata.get("key_counts", []):
            raise _unavailable("模型阶段不覆盖所选固定 K。", stage=stage)
        verified[stage] = (path, metadata)
    if len(capacities) != 1 or bundle.get("max_lines") not in capacities:
        raise _unavailable("模型组合的各阶段判定线容量不一致。")
    return verified


def _load_stage(name, verified, feature_version, torch, device):
    path, metadata = verified[name]
    # Check immediately before each load as well as during bundle preflight.
    if file_hash(path) != metadata["checkpoint_sha256"]:
        raise _unavailable("阶段加载前权重发生变化。", stage=name)
    try:
        state = torch.load(path, map_location="cpu", weights_only=True)
        if state.get("feature_version") != feature_version:
            raise _unavailable("权重内部特征版本不匹配。", stage=name)
        if not isinstance(state.get("config"), dict):
            raise _unavailable("权重内部缺少可校验的架构配置。", stage=name)
        if state["config"] != metadata.get("config"):
            raise _unavailable("权重内部架构与登记阶段配置不一致。", stage=name)
        model = build_model(name, state.get("config"))
        model.load_state_dict(state["model"], strict=True)
    except ModelError:
        raise
    except Exception as exc:
        raise _unavailable("权重不是当前架构的安全 tensor checkpoint。", stage=name) from exc
    del state
    return model.to(device).eval()


def _release(model, torch, device):
    model.to("cpu")
    del model
    gc.collect()
    if device.type == "cuda":
        torch.cuda.empty_cache()


def _validate_prediction(prediction, torch):
    if not all(bool(torch.isfinite(value).all()) for value in prediction.values()):
        raise ModelError("NONFINITE_PREDICTION", "模型输出含 NaN/Inf，已拒绝生成。")


def _bounded(value, lower, upper, repairs, field, event_id):
    result = max(lower, min(upper, value))
    if result != value:
        repairs.append({"code": "BOUND_PROJECTION", "id": event_id, "field": field, "before": value, "after": result})
    return result


def _stitch_events(events, duration, repairs):
    grouped = {}
    for event in events:
        grouped.setdefault((event["line"], event["property"]), []).append(event)
    output = []
    for _, values in grouped.items():
        values.sort(key=lambda e: (e["time"], -e["confidence"]))
        previous = None
        for event in values:
            if previous is not None:
                if event["time"] - previous["time"] < 1e-6:
                    repairs.append({"code": "DUPLICATE_MOTION_PREDICTION", "id": event["id"], "kept_id": previous["id"]})
                    continue
                if previous["end"] > event["time"]:
                    repairs.append({"code": "MOTION_OVERLAP_TRIMMED", "id": previous["id"], "old_end_s": previous["end"], "end_s": event["time"]})
                    previous["end"] = event["time"]
                if abs(previous["end_value"] - event["start_value"]) > 1e-5:
                    repairs.append({"code": "MOTION_CONTINUITY_PROJECTED", "id": event["id"], "before": event["start_value"], "after": previous["end_value"]})
                    event["start_value"] = previous["end_value"]
            event["end"] = min(duration, max(event["time"], event["end"]))
            output.append(event)
            previous = event
    return sorted(output, key=lambda e: (e["line"], e["property"], e["time"]))


def _place_safely(notes, conditions, line_count, duration, repairs):
    pure = conditions["chart_mode"] == "pure_keys"
    k = conditions.get("key_count")
    occupied = []
    lane_until = [0.0] * (k or 0)
    for note in sorted(notes, key=lambda n: (n["time"], n["id"])):
        if not 0 <= note["time"] < duration:
            raise ModelError("INVALID_PREDICTED_TIME", "预测音符时刻越出音频边界。")
        if note["kind"] == 1:
            minimum = min(duration, note["time"] + 0.01)
            if minimum <= note["time"]:
                raise ModelError("INVALID_HOLD", "预测Hold位于音频末端，不能构造合法持续时间。")
            note["end"] = _bounded(note["end"], minimum, duration, repairs, "hold_end_s", note["id"])
        else:
            note["end"] = note["time"]
        if pure:
            ranking = note["lane_ranking"]
            available = [lane for lane in ranking if lane_until[lane] <= note["time"] + 1e-6]
            if not available:
                raise ModelError("PLACEMENT_CONSTRAINT_FAILED", "模型预测的同刻或Hold占用超过 K 列；未静默删音符。", time_s=note["time"])
            lane = available[0]
            if lane != ranking[0]:
                repairs.append({"code": "LANE_OCCUPANCY_PROJECTED", "id": note["id"], "before": ranking[0], "after": lane})
            lane_until[lane] = note["end"] + 0.03
            note.update(lane=lane, line=0, x=675 * (-1 + 2 * (lane + 0.5) / k), above=0, speed=1.0, y_offset=0.0)
        else:
            occupied = [p for p in occupied if p["end"] + 0.03 > note["time"]]
            desired_line, desired_x = note["line_ranking"][0], note["x"]
            chosen = None
            x_candidates = [max(-POSITION_X_SCALE, min(POSITION_X_SCALE, desired_x + shift)) for shift in (0, -72, 72, -144, 144, -216, 216, -288, 288)]
            for line in note["line_ranking"]:
                if line >= line_count:
                    continue
                for x in x_candidates:
                    if not any(p["line"] == line and p["above"] == note["above"] and abs(p["x"] - x) < 64 for p in occupied):
                        chosen = (line, x)
                        break
                if chosen:
                    break
            if chosen is None:
                raise ModelError("PLACEMENT_CONSTRAINT_FAILED", "模型预测在局部位置范围内无法解除音符占用冲突；未删音符。", time_s=note["time"])
            note["line"], note["x"] = chosen
            if chosen != (desired_line, desired_x):
                repairs.append({"code": "LOCAL_OCCUPANCY_PROJECTED", "id": note["id"], "before": {"line": desired_line, "x": desired_x}, "after": {"line": chosen[0], "x": chosen[1]}})
            occupied.append(note)
    return notes


def _chart_from_predictions(notes, events, parents, bpm, duration, conditions, formats):
    exported = [{"id": n["id"], "kind": KINDS[n["kind"]], "time_s": n["time"], "end_time_s": n["end"],
                 "line_id": f"line_{n['line']}", "x": n["x"], "above": n["above"] + 1,
                 "lane_index": n.get("lane")} for n in notes]
    chart = formats.make_chart(exported, bpm, duration, conditions)
    if conditions["chart_mode"] != "pure_keys":
        template = copy.deepcopy(chart["judgeLineList"][0])
        template["notes"] = []
        while len(chart["judgeLineList"]) < len(parents):
            chart["judgeLineList"].append(copy.deepcopy(template))
        if len(chart["judgeLineList"]) != len(parents):
            raise ModelError("EXPORT_LINE_COUNT_MISMATCH", "格式转换后的判定线数量与模型预测不一致。")
        for line_index, line in enumerate(chart["judgeLineList"]):
            line.update(Name=f"PAMOs learned {line_index + 1}", father=parents[line_index], zOrder=line_index)
            layer = {name: [] for name in MOTION_PROPERTIES}
            # Static values fill only intervals where the model emitted no event;
            # this is a renderer default, never reported as learned movement.
            for prop, name in enumerate(MOTION_PROPERTIES):
                selected = [e for e in events if e["line"] == line_index and e["property"] == prop]
                if not selected:
                    layer[name] = copy.deepcopy(template["eventLayers"][0][name])
                    continue
                for event in selected:
                    layer[name].append({"startTime": formats.seconds_to_beat(event["time"], chart["BPMList"]),
                                        "endTime": formats.seconds_to_beat(event["end"], chart["BPMList"]),
                                        "start": event["start_value"], "end": event["end_value"],
                                        "easingType": event["easing"] + 1, "easingLeft": event.get("easing_left", 0.0), "easingRight": event.get("easing_right", 1.0),
                                        "bezier": 0, "bezierPoints": [0, 0, 1, 1], "linkgroup": 0})
            line["eventLayers"] = [layer]
    predictions_by_id = {n["id"]: n for n in notes}
    for line in chart["judgeLineList"]:
        for note in line["notes"]:
            source = predictions_by_id[note["pamosId"]]
            note["speed"], note["yOffset"] = source["speed"], source["y_offset"]
    return chart


def generate_learned(analysis: dict, conditions: dict, bundle: dict, project_root, progress=None) -> dict:
    root = Path(project_root).resolve()
    condition_values = encode_conditions(conditions)
    assert_no_noise(conditions)
    verified = _verify_bundle(bundle, conditions, analysis, root)
    feature_path = _resolve_analysis_path(root, analysis.get("feature_path"))
    features = load_features(feature_path)
    duration = finite(analysis.get("duration_s"), "音频时长")
    bpm = finite(analysis.get("bpm"), "BPM")
    if not 0 < duration <= 7200 or bpm <= 0 or abs(len(features) / FEATURE_RATE - duration) > 0.12:
        raise ModelError("INVALID_ANALYSIS", "音频时长/BPM或25Hz特征时长不一致。")
    feature_sha = file_hash(feature_path)
    windows = [(frame / FEATURE_RATE, min(duration, (frame + MAX_AUDIO_FRAMES) / FEATURE_RATE))
               for frame in range(0, len(features), MAX_AUDIO_FRAMES) if frame / FEATURE_RATE < duration]
    import numpy as np
    import torch
    from . import formats
    seed = int(conditions.get("seed", 42))
    random.seed(seed)
    np.random.seed(seed % 2 ** 32)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    requested_device = bundle.get("inference_device", "cuda" if torch.cuda.is_available() else "cpu")
    if requested_device not in ("cuda", "cuda:0", "cpu") or (requested_device != "cpu" and not torch.cuda.is_available()):
        raise ModelError("DEVICE_UNAVAILABLE", "指定推理设备不可用。")
    device = torch.device(requested_device)
    if device.type == "cuda":
        torch.cuda.set_device(device)
        torch.cuda.reset_peak_memory_stats(device)
    amp_dtype = torch.bfloat16 if device.type == "cuda" and torch.cuda.is_bf16_supported() else torch.float16
    tensor = lambda value: torch.as_tensor(value, dtype=torch.float32, device=device).unsqueeze(0)
    condition_tensor = tensor(condition_values)
    started = time.monotonic()
    notes, events, repairs = [], [], []
    line_count, parents, model = 1, [-1], None
    try:
        model = _load_stage("note_rhythm", verified, analysis["feature_version"], torch, device)
        with torch.inference_mode():
            for index, (start, end) in enumerate(windows):
                width = end - start
                with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=device.type == "cuda"):
                    prediction = model(tensor(feature_window(features, start, end)), condition_tensor,
                                       tensor(note_queries(width)), key_count=conditions.get("key_count") or 6)
                _validate_prediction(prediction, torch)
                p = {k: v[0].float().cpu() for k, v in prediction.items()}
                presence = p["presence"].sigmoid()
                for slot in (presence >= 0.5).nonzero().flatten().tolist():
                    cell = slot // 6
                    hit = start + (cell + 0.5 + float(p["residual"][slot])) / TIME_CELLS * width
                    hit = max(start, min(math.nextafter(end, start), hit))
                    kind = int(p["kind"][slot].argmax())
                    log_hold = min(math.log1p(duration), max(0, float(p["hold"][slot])))
                    notes.append({"id": f"learned_{len(notes):08d}", "time": hit,
                                  "end": hit + math.expm1(log_hold) if kind == 1 else hit,
                                  "kind": kind, "confidence": float(presence[slot]), "window": index,
                                  "line": 0, "x": 0.0, "above": 0, "lane": None})
                del prediction, p
                _emit(progress, phase="note_rhythm", progress=0.3 * (index + 1) / len(windows), message="按全曲窗口预测真实音符事件。")
        _release(model, torch, device)
        model = None
        if not notes:
            raise ModelError("GENERATION_EMPTY", "真实模型未预测音符；未使用规则补造学习式结果。")
        notes.sort(key=lambda n: (n["time"], n["id"]))
        if len(notes) > 300000:
            raise ModelError("GENERATION_CAPACITY_EXCEEDED", "整曲预测音符超过本地安全限额。")
        if conditions["chart_mode"] != "pure_keys":
            model = _load_stage("line_motion", verified, analysis["feature_version"], torch, device)
            with torch.inference_mode():
                for index, (start, end) in enumerate(windows):
                    width = end - start
                    selected = [n for n in notes if n["window"] == index]
                    with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=device.type == "cuda"):
                        prediction = model(tensor(feature_window(features, start, end)), condition_tensor,
                                           tensor(motion_queries(width, model.max_lines)),
                                           tensor(note_vectors(selected, start, width)))
                    _validate_prediction(prediction, torch)
                    p = {k: v[0].float().cpu() for k, v in prediction.items()}
                    window_lines = int(p["line_count"].argmax()) + 1
                    if window_lines > line_count:
                        for line in range(line_count, window_lines):
                            parents.append(int(p["parents"][line, :line + 1].argmax()) - 1)
                        line_count = window_lines
                    presence = p["presence"].sigmoid()
                    for slot in (presence >= 0.5).nonzero().flatten().tolist():
                        line = int(p["line"][slot, :window_lines].argmax())
                        prop = int(p["property"][slot].argmax())
                        begin = min(math.nextafter(end, start), start + float(p["start"][slot]) * width)
                        finish = begin + math.expm1(min(math.log1p(duration), max(0, float(p["duration"][slot]))))
                        limits = ((-675, 675), (-450, 450), (-360, 360), (0, 255), (0.1, 10))
                        event_id = f"motion_{len(events):08d}"
                        values = [_bounded(float(v) * MOTION_SCALES[prop], *limits[prop], repairs, field, event_id)
                                  for v, field in zip(p["values"][slot], ("start_value", "end_value"))]
                        finish = _bounded(finish, begin, duration, repairs, "event_end_s", event_id)
                        events.append({"id": event_id, "time": begin, "end": finish, "line": line, "property": prop,
                                       "easing": int(p["easing"][slot].argmax()), "start_value": values[0], "end_value": values[1],
                                       "easing_left": float(p["easing_bounds"][slot, 0]), "easing_right": float(p["easing_bounds"][slot, 1]),
                                       "confidence": float(presence[slot])})
                    del prediction, p
                    _emit(progress, phase="line_motion", progress=0.3 + 0.3 * (index + 1) / len(windows), message="预测判定线标准运动事件并衔接窗口。")
            _release(model, torch, device)
            model = None
            events = _stitch_events(events, duration, repairs)
        else:
            _emit(progress, phase="line_motion_skipped", progress=0.6, message="纯配置始终跳过 LineMotionNet。")
        model = _load_stage("placement", verified, analysis["feature_version"], torch, device)
        with torch.inference_mode():
            for index, (start, end) in enumerate(windows):
                selected = [n for n in notes if n["window"] == index]
                if not selected:
                    continue
                if len(selected) > MAX_NOTE_SLOTS:
                    raise ModelError("GENERATION_CAPACITY_EXCEEDED", "放置窗口超过192音符；没有截断。")
                width = end - start
                with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=device.type == "cuda"):
                    prediction = model(tensor(feature_window(features, start, end)), condition_tensor,
                                       tensor(note_vectors(selected, start, width)),
                                       tensor(line_vectors(events, parents, start, width, pure=conditions["chart_mode"] == "pure_keys",
                                                           max_lines=model.max_lines)),
                                       key_count=conditions.get("key_count") or 6)
                _validate_prediction(prediction, torch)
                p = {k: v[0].float().cpu() for k, v in prediction.items()}
                for j, note in enumerate(selected):
                    note.update(line_ranking=p["line"][j, :line_count].argsort(descending=True).tolist(),
                                lane_ranking=p["lane"][j, :(conditions.get("key_count") or 6)].argsort(descending=True).tolist(),
                                x=float(p["x"][j]) * POSITION_X_SCALE, above=int(p["above"][j].argmax()),
                                speed=_bounded(float(p["speed"][j]), 0.1, 10, repairs, "note_speed", note["id"]),
                                y_offset=float(p["y_offset"][j]) * 450)
                del prediction, p
                _emit(progress, phase="placement", progress=0.6 + 0.35 * (index + 1) / len(windows), message="预测音符布局及真实固定 K 键位。")
        _release(model, torch, device)
        model = None
        notes = _place_safely(notes, conditions, line_count, duration, repairs)
        chart = _chart_from_predictions(notes, events, parents, bpm, duration, conditions, formats)
        ir = formats.chart_to_ir(chart, conditions["chart_mode"], conditions.get("key_count"))
        if len(ir["notes"]) != len(notes):
            raise ModelError("EXPORT_NOTE_COUNT_MISMATCH", "格式转换改变音符数量，拒绝将结果标为生成成功。")
        metadata = chart.setdefault("pamos", {})
        metadata.update(generator="learned", model_bundle_id=bundle.get("id"), model_status=bundle.get("status", "experimental"),
                        model_arch_version=ARCH_VERSION, model_weight_sha256={name: value[1]["checkpoint_sha256"] for name, value in verified.items()},
                        model_run_ids={name: value[1].get("run_id") for name, value in verified.items()},
                        feature_version=analysis["feature_version"], feature_sha256=feature_sha,
                        conditions_sha256=canonical_hash(conditions), seed=seed, generation_seconds=time.monotonic() - started,
                        full_song_windows=len(windows), line_motion_skipped=conditions["chart_mode"] == "pure_keys",
                        predicted_motion_event_count=len(events), constraint_repairs=repairs,
                        validation_status="NOT RUN", client_playtest="NOT RUN",
                        warnings=["模型输出保持 experimental；独立音频/几何审计、人工审核及客户端试玩尚需执行。",
                                  "占用修复只覆盖局部线坐标；父线变换、运动过程和屏幕几何由独立审计判定。",
                                  "未预测运动属性采用静态渲染默认值，不表示模型已学会该属性。"])
        if device.type == "cuda":
            metadata["cuda_peak_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
        _emit(progress, phase="complete", progress=1.0, message="学习式候选已生成，等待独立审计与人工审核。")
        return chart
    finally:
        if model is not None:
            _release(model, torch, device)

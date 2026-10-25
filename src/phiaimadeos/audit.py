"""Independent format/time/fixed-lane/geometry/DSP rule audit. Never edits notes."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
import math

from .formats import (chart_to_ir, chart_hash, beat_fraction, lane_centers,
                      safe_member, has_noise, has_nontrivial_controls, has_extended_features, _TempoMap, _finite, _check_tree)
from ._geometry import compile_track, scalar_value, line_transform, note_position

ENGINE_VERSION = "non-ai-rules-1.0.0"
TRACKS = ("moveXEvents", "moveYEvents", "rotateEvents", "alphaEvents", "speedEvents")
MAX_EVENTS = 2_000_000
MAX_ISSUES = 1000


def audit_chart(chart, analysis=None, conditions=None):
    if not isinstance(chart, dict):
        return {"status": "BLOCK", "issues": [{"severity": "BLOCK", "code": "FORMAT_INVALID", "message": "谱面必须为JSON对象",
                "time_s": None, "note_id": None, "line_id": None}], "metrics": {"mutated_notes": 0},
                "engine_version": ENGINE_VERSION, "chart_sha256": None}
    pamos = chart.get("pamos", {})
    pamos = pamos if isinstance(pamos, dict) else {}
    conditions = conditions if conditions is not None else pamos.get("conditions", {})
    if not isinstance(conditions, dict):
        conditions = {}
    mode = conditions.get("chart_mode", pamos.get("chart_mode", "regular"))
    key_count = conditions.get("key_count", pamos.get("key_count"))
    issues, counts = [], Counter()
    metrics = {"engine": "traditional_math_dsp", "client_playtest": "NOT RUN",
               "round_trip": "NOT RUN", "geometry_contract": "common_RPE_scalar_tracks",
               "heuristics_calibration": "NOT RUN", "mutated_notes": 0}
    digest = None
    def issue(severity, code, message, note=None, line_id=None, evidence=None, time_s=None):
        counts[severity] += 1
        if len(issues) >= MAX_ISSUES:
            return
        issues.append({"severity": severity, "code": code, "message": message,
                       "time_s": note.get("time_s") if note else time_s,
                       "note_id": note.get("id") if note else None,
                       "line_id": note.get("line_id") if note else line_id,
                       "evidence": evidence or {}, "suggested_action": "review_only"})
    def result():
        metrics["issue_counts"] = dict(counts)
        metrics["issues_truncated"] = sum(counts.values()) > len(issues)
        return {"status": "BLOCK" if counts["BLOCK"] else "WARN" if counts["WARN"] else "PASS",
                "issues": issues, "metrics": metrics, "engine_version": ENGINE_VERSION, "chart_sha256": digest}
    try:
        _check_tree(chart)
        digest = chart_hash(chart)
        ir = chart_to_ir(chart, mode, key_count, copy_raw=False)
    except (ValueError, KeyError, TypeError, IndexError, OverflowError, AttributeError) as exc:
        issue("BLOCK", "FORMAT_INVALID", str(exc))
        return result()
    notes = ir["notes"]
    lines = chart["judgeLineList"]
    if "offset" not in chart["META"]:
        issue("BLOCK", "META_FIELD_MISSING", "RPE 客户端要求 META.offset")
    elif isinstance(chart["META"]["offset"], bool) or not isinstance(chart["META"]["offset"], int) or not -(2 ** 31) <= chart["META"]["offset"] < 2 ** 31:
        issue("BLOCK", "META_OFFSET_INVALID", "RPE META.offset 必须是32位整数毫秒")
    metrics.update({"note_count": len(notes), "judge_line_count": len(lines), "bpm_segment_count": len(ir["bpm_map"]),
                    "time_mapping": ir["time_mapping"], "raw_fields_preserved": True})
    for warning in ir["unsupported_features"]:
        issue("WARN", "UNSUPPORTED_FEATURE", warning)
    identifiers = [note["id"] for note in notes]
    if len(set(identifiers)) != len(identifiers):
        issue("BLOCK", "NOTE_ID_DUPLICATE", "音符 ID 重复，无法可靠定位修订")
    # Parent cycles and invalid references are certain format errors.
    colors = [0] * len(lines)
    def visit(index):
        if colors[index] == 1:
            raise ValueError("判定线父子关系形成循环")
        if colors[index] == 2:
            return
        colors[index] = 1
        parent = lines[index].get("father", -1)
        if parent is not None and parent >= 0:
            visit(parent)
        colors[index] = 2
    try:
        for index in range(len(lines)):
            visit(index)
    except (ValueError, RecursionError) as exc:
        issue("BLOCK", "PARENT_CYCLE", str(exc))
        return result()
    imported = chart.get("_pamos_import", {})
    for field in ("music", "illustration", "chart"):
        reference = imported.get("info", {}).get(field)
        if reference:
            try:
                safe_member(reference)
            except (TypeError, ValueError) as exc:
                issue("BLOCK", "ASSET_PATH_INVALID", str(exc))
    compiled, event_count, unsupported_lines = [], 0, set()
    tempo = _TempoMap(ir["bpm_map"])
    offset = ir["offset_ms"] / 1000 + ir.get("info_offset_s", 0)
    for index, line in enumerate(lines):
        line_id = f"line_{index}"
        missing = sorted({"Name", "Texture", "eventLayers", "isCover"} - set(line))
        if missing:
            issue("BLOCK", "LINE_FIELD_MISSING", "RPE 判定线缺少客户端字段", line_id=line_id, evidence={"fields": missing})
        if not isinstance(line.get("Name", ""), str) or not isinstance(line.get("Texture", "line.png"), str):
            issue("BLOCK", "LINE_STRING_INVALID", "Name/Texture 必须为字符串", line_id=line_id)
        cover = line.get("isCover", 1)
        if isinstance(cover, bool) or not isinstance(cover, int) or not 0 <= cover <= 255:
            issue("BLOCK", "LINE_COVER_INVALID", "isCover 必须为0..255整数", line_id=line_id)
        tracks = defaultdict(list)
        factor = ir["judge_lines"][index]["time_scale"]
        layers = line.get("eventLayers", [])
        if not isinstance(layers, list) or len(layers) > 64:
            issue("BLOCK", "EVENT_LAYERS_INVALID", "事件层必须是长度不超过64的数组", line_id=line_id)
            layers = []
        for layer in layers:
            if layer is None:
                continue
            if not isinstance(layer, dict):
                issue("BLOCK", "EVENT_LAYER_INVALID", "事件层必须为对象或 null", line_id=line_id)
                continue
            for name, events in layer.items():
                if name not in TRACKS:
                    if events:
                        issue("WARN", "EVENT_TRACK_UNSUPPORTED", f"未知轨道 {name} 已保留，未求值", line_id=line_id)
                        unsupported_lines.add(index)
                    continue
                events = [] if events is None else events
                if not isinstance(events, list):
                    issue("BLOCK", "EVENT_ARRAY_INVALID", f"{name} 必须为数组", line_id=line_id)
                    continue
                event_count += len(events)
                if event_count > MAX_EVENTS:
                    issue("BLOCK", "EVENT_LIMIT", f"事件数量超过{MAX_EVENTS}有界处理上限")
                    return result()
                parsed, previous_start, previous_end, previous_value = [], None, None, None
                for event in events:
                    try:
                        if not isinstance(event, dict) or any(not isinstance(event.get(key), list) for key in ("startTime", "endTime")):
                            raise ValueError("事件必须为对象且时间必须为三元数组")
                        start = tempo.to_seconds(event["startTime"]) * factor + offset
                        end = tempo.to_seconds(event["endTime"]) * factor + offset
                        _finite(event["start"], "事件 start")
                        _finite(event["end"], "事件 end")
                        if end < start:
                            raise ValueError("事件结束时间早于开始时间")
                        easing = event.get("easingType", 1)
                        if isinstance(easing, bool) or not isinstance(easing, int) or not 0 <= easing <= 29:
                            raise ValueError("不支持此 easingType")
                        left, right = event.get("easingLeft", 0), event.get("easingRight", 1)
                        _finite(left, "easingLeft")
                        _finite(right, "easingRight")
                        if not 0 <= left <= 1 or not 0 <= right <= 1:
                            raise ValueError("缓动区间超出[0,1]")
                        if event.get("bezier", 0):
                            points = event.get("bezierPoints", [])
                            if len(points) != 4:
                                raise ValueError("Bezier 必须含4个控制数值")
                            for value in points:
                                _finite(value, "Bezier 控制点")
                            if not 0 <= points[0] <= 1 or not 0 <= points[2] <= 1:
                                raise ValueError("Bezier 的时间轴控制点超出[0,1]")
                        if previous_start is not None and start < previous_start:
                            issue("BLOCK", "EVENT_UNSORTED", "同一事件轨道起点没有按时间排序", line_id=line_id, time_s=start)
                        if previous_end is not None and start < previous_end:
                            issue("WARN", "EVENT_OVERLAP", "事件相互重叠；几何只作近似提示", line_id=line_id, time_s=start)
                            unsupported_lines.add(index)
                        elif previous_end is not None and abs(start - previous_end) < 1e-6 and abs(event["start"] - previous_value) > 1e-4:
                            issue("WARN", "EVENT_DISCONTINUITY", "事件边界数值发生跳变，需人工检查演出", line_id=line_id, time_s=start)
                        if any("trajectory" in key.lower() or key.lower().startswith("path") for key in event):
                            unsupported_lines.add(index)
                            issue("WARN", "TRAJECTORY_UNSUPPORTED", "整体轨迹仅 raw 保留，标量几何无法完整解释", line_id=line_id)
                        parsed.append((start, end, event))
                        previous_start, previous_end, previous_value = start, end, event["end"]
                    except (KeyError, TypeError, ValueError, OverflowError) as exc:
                        issue("BLOCK", "EVENT_INVALID", f"{name}: {exc}", line_id=line_id)
                if parsed:
                    tracks[name].append(compile_track(parsed))
        compiled.append(tracks)
        if line.get("attachUI") not in (None, "", False) or line.get("Texture", "line.png") != "line.png":
            unsupported_lines.add(index)
        if has_nontrivial_controls(line):
            issue("WARN", "CONTROL_CURVE_GEOMETRY", "控制曲线已保留，音符几何未完整复现", line_id=line_id)
            unsupported_lines.add(index)
        extended = line.get("extended") or {}
        if not isinstance(extended, dict):
            issue("BLOCK", "EXTENDED_INVALID", "extended 必须为对象或 null", line_id=line_id)
            extended = {}
        if has_extended_features(line):
            issue("WARN", "EXTENDED_GEOMETRY", "扩展事件仅保留，完整视觉/判定语义需客户端确认", line_id=line_id)
            unsupported_lines.add(index)
        if mode == "pure_keys" and line.get("father", -1) not in (-1, None):
            unsupported_lines.add(index)
            issue("WARN", "PURE_KEYS_PARENT_PROFILE", "当前纯配置静线认证没有覆盖父线布局，需专用适配器", line_id=line_id)
        if mode == "pure_keys" and index not in unsupported_lines:
            # Endpoints and interior values prove movement when different. Constant
            # scalar events are analytically constant; sampling is not a certificate
            # for unknown extended trajectories or overlapping events.
            for name in TRACKS:
                sample_times = {offset, offset + max(0, ir["duration_s"])}
                for track in tracks.get(name, []):
                    for start, end, event in track[1]:
                        sample_times.update((start - 1e-7, start, end, end + 1e-7))
                        sample_times.update(start + (end - start) * fraction / 8 for fraction in range(1, 8))
                values = [scalar_value(tracks, name, time) for time in sample_times]
                if values and max(values) - min(values) > 1e-5:
                    issue("BLOCK", "PURE_KEYS_DYNAMIC_LINE", f"纯配置 {name} 存在确定的数值变化", line_id=line_id,
                          evidence={"min": min(values), "max": max(values)})
        if mode == "pure_keys" and isinstance(extended, dict):
            for name, events in extended.items():
                if name in {"scaleXEvents", "scaleYEvents", "colorEvents", "textEvents", "gifEvents", "inclineEvents"} and isinstance(events, list) and events:
                    values = [event.get(key) for event in events if isinstance(event, dict) for key in ("start", "end")]
                    if values and any(value != values[0] for value in values[1:]):
                        issue("BLOCK", "PURE_KEYS_EXTENDED_ANIMATION", f"纯配置含变化的扩展轨道 {name}", line_id=line_id)
    metrics["event_count"] = event_count
    # Unsupported parents also invalidate the geometry coverage of children.
    for _ in range(len(lines)):
        descendants = {index for index, line in enumerate(lines) if line.get("father", -1) in unsupported_lines}
        if descendants <= unsupported_lines:
            break
        unsupported_lines.update(descendants)
    if mode == "pure_keys":
        if has_noise(chart) or conditions.get("special_features"):
            issue("BLOCK", "PURE_KEYS_SPECIAL_FEATURE", "纯配置不能包含噪域或特殊机制")
        if unsupported_lines:
            issue("WARN", "PURE_KEYS_STATIC_UNVERIFIED", "存在未解释的视觉/轨迹字段，尚不能认证全曲静线")
    duration = analysis.get("duration_s") if analysis else ir.get("duration_s")
    if duration is not None:
        try:
            _finite(duration, "duration_s")
            if duration < 0:
                raise ValueError("时长不能为负")
        except ValueError as exc:
            issue("BLOCK", "DURATION_INVALID", str(exc))
            duration = None
    real_notes, per_lane, anchors, kind_counts = [], defaultdict(list), [], Counter()
    centers = lane_centers(key_count) if mode == "pure_keys" else None
    for note in notes:
        kind_counts[note["kind"]] += 1
        raw = note["raw"]
        missing = sorted({"type", "above", "startTime", "endTime", "positionX", "yOffset", "alpha", "size", "speed", "isFake", "visibleTime"} - set(raw))
        if missing:
            issue("BLOCK", "NOTE_FIELD_MISSING", "RPE 音符缺少客户端字段", note, evidence={"fields": missing})
        for field, maximum in (("alpha", 65535), ("isFake", 255)):
            value = raw.get(field, 255 if field == "alpha" else 0)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                issue("BLOCK", "NOTE_INTEGER_INVALID", f"{field} 必须为0..{maximum}整数", note)
        if isinstance(note["above"], bool) or not isinstance(note["above"], int) or note["above"] not in (1, 2):
            issue("BLOCK", "ABOVE_INVALID", "above 必须为1或2", note)
        for field in ("size", "speed", "yOffset", "visibleTime", "alpha"):
            if field in raw:
                try:
                    _finite(raw[field], field)
                except ValueError as exc:
                    issue("BLOCK", "NOTE_VALUE_INVALID", str(exc), note)
        if isinstance(raw.get("size", 1), (int, float)) and raw.get("size", 1) <= 0:
            issue("BLOCK", "NOTE_SIZE_INVALID", "音符 size 必须为正", note)
        if note["kind"] == "HOLD" and beat_fraction(note["end_beat"]) <= beat_fraction(note["beat"]):
            issue("BLOCK", "HOLD_NON_POSITIVE", "Hold 结束拍必须大于起始拍", note)
        if centers is not None:
            lane = note.get("lane_index")
            if isinstance(lane, bool) or not isinstance(lane, int) or not 0 <= lane < key_count:
                issue("BLOCK", "LANE_INDEX_INVALID", "纯配置缺少合法固定列标签", note)
            elif abs(note["x"] - centers[lane]) > 1e-4:
                issue("BLOCK", "LANE_POSITION_INVALID", "音符位置与固定列中心不一致", note,
                      evidence={"expected_x": centers[lane], "actual_x": note["x"]})
            elif note["above"] != 1:
                issue("BLOCK", "LANE_DIRECTION_INVALID", "当前单静线纯配置适配器要求 above=1", note)
        if note["fake"]:
            continue
        real_notes.append(note)
        if duration is not None and (note["time_s"] < -1e-4 or note["end_time_s"] > duration + 2):
            issue("BLOCK", "NOTE_OUTSIDE_AUDIO", "真实判定音符超出歌曲时间范围（尾部容差2秒）", note,
                  evidence={"end_time_s": note["end_time_s"], "duration_s": duration})
        if raw.get("yOffset", 0):
            issue("WARN", "NOTE_YOFFSET_GEOMETRY", "yOffset 几何未完整复现，需客户端确认", note)
        if not anchors or abs(note["time_s"] - anchors[-1]) > 0.001:
            anchors.append(note["time_s"])
        identity = note.get("lane_index") if mode == "pure_keys" else round(note["x"], 4)
        if not isinstance(identity, (str, int, float, type(None))):
            identity = "invalid"
        above_key = note["above"] if isinstance(note["above"], (str, int, float)) else "invalid"
        per_lane[(note["line_id"], identity, above_key)].append(note)
    # Notes in the raw file need not be sorted: sorting here changes no chart data.
    anchors = sorted(set(round(note["time_s"], 3) for note in real_notes))
    for lane_notes in per_lane.values():
        ordered = sorted(lane_notes, key=lambda note: note["time_s"])
        hold_end, hold_id, previous = -math.inf, None, None
        for note in ordered:
            if previous and abs(note["time_s"] - previous["time_s"]) < 1e-7:
                issue("BLOCK" if mode == "pure_keys" else "WARN", "SAME_POSITION_COLLISION", "同一列/位置同时出现多个真实音符", note,
                      evidence={"other_note_id": previous["id"]})
            if note["time_s"] < hold_end - 1e-6:
                issue("WARN", "HOLD_LANE_CONFLICT", "同位置 Hold 持续期间存在另一音符；需按客户端手法人工检查", note,
                      evidence={"hold_note_id": hold_id, "hold_end_s": hold_end})
            if note["kind"] == "HOLD" and note["end_time_s"] > hold_end:
                hold_end, hold_id = note["end_time_s"], note["id"]
            previous = note
    metrics["note_kinds"] = dict(kind_counts)
    metrics["real_note_count"] = len(real_notes)
    density = Counter(math.floor(note["time_s"]) for note in real_notes)
    metrics["peak_notes_per_second"] = max(density.values(), default=0)
    metrics["average_notes_per_second"] = len(real_notes) / max(float(duration or 0), 1e-6)
    if metrics["peak_notes_per_second"] > 24:
        issue("WARN", "DENSITY_SPIKE", "一秒内真实音符数超过24；这是未校准的密度提示", evidence={"peak_nps": metrics["peak_notes_per_second"]})
    concurrent = Counter(round(note["time_s"], 3) for note in real_notes)
    metrics["max_simultaneous_heads"] = max(concurrent.values(), default=0)
    if metrics["max_simultaneous_heads"] > 4:
        issue("WARN", "MULTITOUCH_RISK", "存在超过4个同时判定起点，需按目标触屏与手法审核")
    # The supported pure-key export profile has canonical world-space columns.
    # This checks every note, independently of the heuristic sampling budget.
    if mode == "pure_keys" and not counts["BLOCK"]:
        for note in notes:
            line_index = int(note["line_id"].split("_")[-1])
            if line_index in unsupported_lines:
                continue
            projected = note_position(note, line_transform(line_index, offset, lines, compiled))
            expected_x = centers[note["lane_index"]] / 675
            if abs(projected[0] - expected_x) > 1e-4:
                issue("BLOCK", "PURE_KEYS_LANE_PROJECTION", "静线变换后的落点偏离当前固定列布局", note,
                      evidence={"expected_x_normalized": expected_x, "actual_x_normalized": projected[0]})
    # Hard errors above remain separate from sampled heuristic geometry below.
    if not counts["BLOCK"]:
        sampled = real_notes[:20000]
        previous_position = None
        checked = 0
        for note in sorted(sampled, key=lambda note: note["time_s"]):
            line_index = int(note["line_id"].split("_")[-1])
            if line_index in unsupported_lines:
                continue
            try:
                transform = line_transform(line_index, note["time_s"], lines, compiled)
                position = note_position(note, transform)
                if not all(math.isfinite(value) for value in (*transform, *position)):
                    issue("BLOCK", "GEOMETRY_NON_FINITE", "几何求值产生非有限数值", note)
                    continue
                checked += 1
                if abs(position[0]) > 1.05 or abs(position[1]) > 1.05:
                    issue("WARN", "HIT_POSITION_OFFSCREEN", "估计判定落点位于标准视口外，需人工预览", note,
                          evidence={"x_normalized": position[0], "y_normalized": position[1]})
                if previous_position:
                    elapsed = note["time_s"] - previous_position[0]
                    distance = math.hypot(position[0] - previous_position[1][0], position[1] - previous_position[1][1])
                    if 0.02 < elapsed < 0.12 and distance > 1.2:
                        issue("WARN", "TRAVEL_SPEED_RISK", "相邻判定位置短时间跨越较远，需检查手法", note,
                              evidence={"distance_normalized": distance, "interval_s": elapsed})
                if note["kind"] == "HOLD":
                    hold_positions = []
                    for fraction in (0, 0.25, 0.5, 0.75, 1):
                        time = note["time_s"] + (note["end_time_s"] - note["time_s"]) * fraction
                        hold_positions.append(note_position(note, line_transform(line_index, time, lines, compiled)))
                    if any(abs(x) > 1.05 or abs(y) > 1.05 for x, y in hold_positions):
                        issue("WARN", "HOLD_TRAJECTORY_RISK", "Hold 采样轨迹离开标准视口，需人工确认", note)
                previous_position = (note["time_s"], position)
            except (ValueError, OverflowError, RecursionError) as exc:
                issue("WARN", "GEOMETRY_INCOMPLETE", str(exc), note)
        metrics["geometry_heads_checked"] = checked
        metrics["geometry_heads_total"] = len(real_notes)
        if len(real_notes) > 20000:
            issue("WARN", "GEOMETRY_SAMPLE_LIMIT", "超过20000个真实音符；启发式几何只采样前20000个，格式/时间检查仍覆盖全部")
    if analysis:
        _alignment(anchors, real_notes, analysis, metrics, issue)
    else:
        issue("WARN", "AUDIO_EVIDENCE_UNAVAILABLE", "未提供音频 DSP，无法判断音频对齐或静音密度")
    return result()


def _alignment(anchors, real_notes, analysis, metrics, issue):
    onsets = sorted(value for value in analysis.get("onsets_s", []) if isinstance(value, (int, float)) and math.isfinite(value))
    metrics["audio_confidence"] = analysis.get("confidence", 0)
    if not onsets:
        issue("WARN", "ONSET_EVIDENCE_UNKNOWN", "没有可用 onset 证据；不会判定节奏质量或改动音符")
        return
    used, deltas, matches, regions = set(), [], [], defaultdict(list)
    for anchor in anchors:
        insertion = bisect_left(onsets, anchor)
        options = [index for index in (insertion - 1, insertion, insertion + 1) if 0 <= index < len(onsets) and index not in used]
        if not options:
            continue
        nearest = min(options, key=lambda index: abs(onsets[index] - anchor))
        delta = anchor - onsets[nearest]
        if abs(delta) <= 0.2:
            used.add(nearest)
            deltas.append(delta)
            matches.append(anchor)
            regions[int(anchor // 15)].append(delta)
    metrics["anchor_count"] = len(anchors)
    metrics["anchor_onset_hit_rate"] = sum(abs(delta) <= 0.08 for delta in deltas) / max(1, len(anchors))
    metrics["onset_matching_window_s"] = 0.08
    if deltas:
        absolute = sorted(abs(delta) * 1000 for delta in deltas)
        signed = sorted(deltas)
        median = signed[len(signed) // 2]
        metrics["anchor_abs_error_p50_ms"] = absolute[len(absolute) // 2]
        metrics["anchor_abs_error_p90_ms"] = absolute[min(len(absolute) - 1, int(len(absolute) * 0.9))]
        metrics["signed_error_median_ms"] = median * 1000
        metrics["timing_delta_histogram"] = {"edges_ms": [-200, -120, -80, -40, 0, 40, 80, 120, 200],
                                             "counts": [sum(left <= delta * 1000 < right for delta in deltas)
                                                        for left, right in zip([-200, -120, -80, -40, 0, 40, 80, 120], [-120, -80, -40, 0, 40, 80, 120, 200.001])]}
        if len(deltas) >= 8 and abs(median) > 0.08:
            issue("WARN", "OFFSET_SUSPECT", "音符起点相对附近 onset 存在持续偏移；需人工试听，不自动移动音符", evidence={"median_delta_ms": median * 1000})
        if len(deltas) >= 8:
            mean_t, mean_d = sum(matches) / len(matches), sum(deltas) / len(deltas)
            divisor = sum((time - mean_t) ** 2 for time in matches)
            slope = sum((time - mean_t) * (delta - mean_d) for time, delta in zip(matches, deltas)) / max(divisor, 1e-12)
            metrics["timing_drift_slope"] = slope
            if abs(slope) > 0.001:
                issue("WARN", "TIMING_DRIFT_SUSPECT", "匹配误差随歌曲时间变化；需检查 BPM/变拍/录音漂移", evidence={"slope_s_per_s": slope})
    metrics["alignment_regions"] = [{"start_s": region * 15, "matched_anchors": len(values),
                                     "median_delta_ms": sorted(values)[len(values) // 2] * 1000,
                                     "confidence": "LOW" if len(values) < 4 else "HEURISTIC"}
                                    for region, values in sorted(regions.items())]
    quiet_count = 0
    tap_times = sorted(note["time_s"] for note in real_notes if note["kind"] == "TAP")
    for interval in analysis.get("silence_intervals", []):
        start, end = interval.get("start_s", 0), interval.get("end_s", 0)
        count = max(0, bisect_left(tap_times, end) - bisect_left(tap_times, start))
        quiet_count += count
        if end > start and count / (end - start) > 4 and count >= 4:
            issue("WARN", "DENSE_IN_LOW_RMS", "低能量区存在较多 Tap，可能为弱声/演出，需人工确认", evidence={"start_s": start, "end_s": end, "tap_count": count}, time_s=start)
    metrics["tap_heads_in_low_rms"] = quiet_count

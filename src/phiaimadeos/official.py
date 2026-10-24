"""Independent Phigros v1/v3 -> common RPE normalization.

SPDX-License-Identifier: GPL-3.0-or-later

The public runtime contracts were inspected at Phira-Pro commit
4ed6aaf6b844cfe59c9122a068f3fe5411553936: prpr/src/parse/{pgr,rpe,rpen}.rs,
core/{anim,object}.rs and scene/game.rs. This adapter does not execute the
client, certify round trips, infer music tempo or grant training rights.
The caller keeps original native bytes separately; normalized files contain
only mapped fields, unmapped fields and compact references to source objects.
"""
from __future__ import annotations

import copy
from fractions import Fraction
import hashlib

from .formats import (MAX_JSON_BYTES, MAX_LINES, MAX_NOTES, _check_tree,
                      _finite, beat_triplet, canonical_bytes, has_noise)

MAPPING_VERSION = "phira-pro-4ed6aaf-native-rpe-v1"
MAX_SOURCE_EVENTS = 100_000
MAX_TARGET_EVENTS = 150_000
MAX_ABS_TICKS = 2 ** 31
MAX_ABS_SCALAR = 10 ** 12
MAX_DENOMINATOR = 1_000_000
MAX_TIME_ERROR_S = 1e-6
TYPE_MAP = {1: 1, 2: 4, 3: 2, 4: 3}
EVENT_NAMES = ("judgeLineMoveEvents", "judgeLineRotateEvents", "judgeLineDisappearEvents", "speedEvents")
NOTE_FIELDS = {"type", "time", "positionX", "holdTime", "speed", "floorPosition"}
EVENT_FIELDS = {"startTime", "endTime", "start", "end", "start2", "end2"}
LINE_FIELDS = {"bpm", "notesAbove", "notesBelow", *EVENT_NAMES,
               "numOfNotes", "numOfNotesAbove", "numOfNotesBelow"}
ROOT_FIELDS = {"formatVersion", "offset", "judgeLineList", "numOfNotes"}


def _number(value, path, maximum=MAX_ABS_SCALAR):
    try:
        _finite(value, path)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{path}: 必须是安全范围内的有限数值") from exc
    if abs(value) > maximum:
        raise ValueError(f"{path}: 数值超过转换器安全限额 {maximum}")
    return value


def _fraction(value, path, maximum=MAX_ABS_TICKS):
    return Fraction(str(_number(value, path, maximum)))


def _array(value, path):
    if not isinstance(value, list):
        raise ValueError(f"{path}: 必须为数组")
    return value


def _unknown(value, known):
    return {key: copy.deepcopy(child) for key, child in value.items() if key not in known}


def _reject_extensions(value, path="chart"):
    """Never reinterpret active noise, shaders, parents or other dialects."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("_", "")
            if normalized in {"effects", "shaderevents", "shaders", "globalevents", "bpmList".lower(),
                              "eventlayers", "extended", "trajectory", "noisearealayers"}:
                active = any(bool(v) for v in child.values()) if isinstance(child, dict) else bool(child)
                if active:
                    raise ValueError(f"{path}.{key}: 原生 v1/v3 转换器尚不支持此机制")
            if normalized in {"father", "parent", "parentid"} and child not in (None, -1):
                raise ValueError(f"{path}.{key}: 原生扁平判定线不能推定父线语义")
            if normalized in {"isfake", "fake"} and child:
                raise ValueError(f"{path}.{key}: 不支持推定原生扩展假音符语义")
            _reject_extensions(child, path + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_extensions(child, f"{path}[{index}]")


class _Conversion:
    def __init__(self, reference_bpm):
        self.reference = Fraction(str(reference_bpm))
        self.warnings = []
        self._warning_set = set()
        self.resolutions = []
        self.max_time_error_s = 0.0
        self.target_events = 0

    def warn(self, message):
        if message not in self._warning_set:
            self._warning_set.add(message)
            self.warnings.append(message)

    def beat(self, seconds):
        exact = seconds * self.reference / 60
        representable = exact.limit_denominator(MAX_DENOMINATOR)
        error = float(abs(exact - representable) * 60 / self.reference)
        self.max_time_error_s = max(self.max_time_error_s, error)
        if error > MAX_TIME_ERROR_S:
            raise ValueError("原生时标无法在RPE安全有理数范围内达到1微秒转换精度")
        result = beat_triplet(representable)
        if not -(2 ** 31) <= result[0] < 2 ** 31 or not 0 <= result[1] < 2 ** 32 or not 1 <= result[2] < 2 ** 32:
            raise ValueError("转换后的拍数超出Phira-Pro Triple(i32,u32,u32)范围")
        return result

    def event(self, start_s, end_s, start_value, end_value, provenance):
        self.target_events += 1
        if self.target_events > MAX_TARGET_EVENTS:
            raise ValueError("转换后事件超过150000个，拒绝截断")
        return {"startTime": self.beat(start_s), "endTime": self.beat(end_s),
                "start": _number(start_value, provenance + ".start"),
                "end": _number(end_value, provenance + ".end"), "easingType": 1,
                "easingLeft": 0, "easingRight": 1, "bezier": 0,
                "bezierPoints": [0, 0, 1, 1], "linkgroup": 0,
                "pamosNative": {"source": provenance}}


def _source_event(event, source):
    if not isinstance(event, dict):
        raise ValueError(f"{source}: 事件必须为对象")
    required = {"startTime", "endTime", "start", "end"}
    if required - set(event):
        raise ValueError(f"{source}: 缺少事件字段 {sorted(required - set(event))}")
    start, end = _fraction(event["startTime"], source + ".startTime"), _fraction(event["endTime"], source + ".endTime")
    if start > end:
        # Upstream discards these. Refusal is explicit and keeps the raw chart;
        # silently deleting a source event would hide a compatibility decision.
        raise ValueError(f"{source}: 反向事件在客户端会被忽略；本转换器拒绝静默删除")
    for key in ("start", "end", "start2", "end2"):
        _number(event.get(key, 0), source + "." + key)
    return start, end


def _motion_track(events, tick_seconds, mapping, source, conversion, format_version=3):
    """Rebuild native linear keyframes, including native gap interpolation."""
    points = []
    previous_end = None
    for index, original in enumerate(events):
        location = f"{source}[{index}]"
        start, end = _source_event(original, location)
        unknown = _unknown(original, EVENT_FIELDS)
        if unknown:
            conversion.resolutions.append({"source": location, "action": "unknown_fields_preserved", "fields": unknown})
            conversion.warn("存在未识别事件字段：仅按锁定原生客户端已知线性字段求值，原字段与原件引用均保留")
        if mapping == "move":
            if format_version == 1:
                # fmod rather than Python % reproduces the sign of Rust's
                # floating remainder for negative packed coordinates.
                import math
                start_y, end_y = math.fmod(original["start"], 1000), math.fmod(original["end"], 1000)
                begin = ((original["start"] - start_y) / 1000 / 880, start_y / 520)
                finish = ((original["end"] - end_y) / 1000 / 880, end_y / 520)
            else:
                begin = (original["start"], original.get("start2", 0))
                finish = (original["end"], original.get("end2", 0))
        else:
            begin, finish = (original["start"],), (original["end"],)
        if previous_end is not None and end <= previous_end:
            conversion.resolutions.append({"source": location, "action": "covered_by_prior_event",
                                           "original_ticks": [original["startTime"], original["endTime"]]})
            conversion.warn("原生重叠运动按客户端先事件优先：被覆盖事件不再参与运行时，逐项解析动作已登记，原始JSON保留")
            continue
        if previous_end is not None and start < previous_end:
            factor = float((previous_end - start) / (end - start))
            begin = tuple(a + (b - a) * factor for a, b in zip(begin, finish))
            conversion.resolutions.append({"source": location, "action": "trimmed_to_prior_end",
                                           "original_start_tick": original["startTime"], "effective_start_tick": str(previous_end)})
            conversion.warn("原生部分重叠运动已按客户端优先级裁剪并插值起值；不是原始结构无损往返")
            start = previous_end
        previous_end = end
        clamped = max(Fraction(0), start)
        if start < 0:
            conversion.resolutions.append({"source": location, "action": "native_start_clamped_to_zero",
                                           "original_start_tick": original["startTime"]})
            conversion.warn("负起点运动按锁定原生客户端将起点时间夹到0，保持其起值；原字段见原始JSON")
        points.append((clamped * tick_seconds, begin, location, "start"))
        if end > clamped:
            points.append((end * tick_seconds, finish, location, "end"))
    axes = 2 if mapping == "move" else 1
    if not points:
        # Anim::default => zero translation/rotation, alpha defaults to one.
        defaults = (0.0, 0.0) if mapping == "move" else ((255.0,) if mapping == "alpha" else (0.0,))
        conversion.warn("存在空运动轨道：按原生客户端的默认位置/旋转/透明度显式补常量")
        return [[conversion.event(Fraction(0), Fraction(1), defaults[axis], defaults[axis], source + ":empty_default")]
                for axis in range(axes)]
    # The scalar parser omits equal-valued starts even through gaps; the move
    # parser only omits duplicate (time,value) starts. Axis-specific compaction
    # reproduces these native rules without resampling a whole song.
    output = []
    for axis in range(axes):
        native_points = []
        for time_s, values, location, role in points:
            value = values[axis]
            if mapping != "move" and role == "start" and native_points and native_points[-1][1] == value:
                # Native scalar parsing omits this start even through a gap:
                # the preceding endpoint then interpolates straight to this end.
                continue
            if native_points and native_points[-1][0] == time_s and native_points[-1][1] == value:
                continue
            native_points.append((time_s, value, location))
        def mapped(value):
            if mapping == "move":
                return value * (1350 if axis == 0 else 900) - (675 if axis == 0 else 450)
            return value * 255 if mapping == "alpha" else -value
        if native_points[0][0] > 0:
            first_time, first, _ = native_points[0]
            if len(native_points) > 1 and native_points[1][0] > first_time:
                next_time, following, _ = native_points[1]
                initial = first - float(first_time / (next_time - first_time)) * (following - first)
            elif len(native_points) > 1:
                raise ValueError(f"{source}: 首关键帧正时间同点跳变在原生客户端会产生非有限外插，无法安全转换")
            else:
                initial = first
            native_points.insert(0, (Fraction(0), initial, source + ":native_preroll_extrapolation"))
        result = []
        for left, right in zip(native_points, native_points[1:]):
            if right[0] < left[0]:
                raise ValueError(f"{source}: 客户端关键帧非单调，拒绝重排后假称等价")
            result.append(conversion.event(left[0], right[0], mapped(left[1]), mapped(right[1]), left[2]))
            if right[2] != left[2] and right[0] > left[0] and right[1] != left[1]:
                conversion.warn("原生事件间空档的线性插值已显式桥接；RPE空档保持语义不同，不能按事件逐项直拷贝")
        tail = native_points[-1]
        result.append(conversion.event(tail[0], tail[0] + 1, mapped(tail[1]), mapped(tail[1]), tail[2] + ":constant_tail"))
        output.append(result)
    return output


def _speed_track(events, tick_seconds, native_max_s, target_max_s, source, conversion):
    if not events:
        raise ValueError(f"{source}: 原生客户端要求至少一个speedEvent，不能猜测缺失流速")
    parsed = []
    for index, event in enumerate(events):
        location = f"{source}[{index}]"
        if not isinstance(event, dict) or not {"startTime", "endTime", "value"} <= set(event):
            raise ValueError(f"{location}: 流速事件缺少字段")
        start, end = _fraction(event["startTime"], location + ".startTime"), _fraction(event["endTime"], location + ".endTime")
        if start > end:
            raise ValueError(f"{location}: 反向流速事件会被原生客户端丢弃，转换器拒绝静默删除")
        value = Fraction(str(_number(event["value"], location + ".value")))
        unknown = _unknown(event, {"startTime", "endTime", "value"})
        if unknown:
            conversion.resolutions.append({"source": location, "action": "unknown_fields_preserved", "fields": unknown})
        if index == 0 and start != 0:
            conversion.resolutions.append({"source": location, "action": "native_first_speed_start_forced_zero",
                                           "original_start_tick": event["startTime"]})
            conversion.warn("首个流速起点按锁定原生客户端强制归0，而不是保留其原始负/正起点")
            start = Fraction(0)
        parsed.append((start, end, value, location))
    height_area = Fraction(0)
    keyframes = []
    for index, (start, end, value, location) in enumerate(parsed):
        keyframes.append((start * tick_seconds, height_area * tick_seconds, location))
        if index + 1 < len(parsed):
            height_area += (end - start) * value
            if end != parsed[index + 1][0]:
                conversion.resolutions.append({"source": location, "action": "speed_integral_reconstructed",
                                               "authored_end_tick": str(end), "next_start_tick": str(parsed[index + 1][0])})
                conversion.warn("不连续/重叠流速已按原生height积分及相邻起点斜率重建；不承诺编辑器结构无损")
        else:
            if start * tick_seconds > native_max_s:
                raise ValueError(f"{location}: 最后流速起点超过原生全曲height终点，客户端会形成非单调关键帧")
            final_area = height_area * tick_seconds + (native_max_s - start * tick_seconds) * value
            keyframes.append((native_max_s, final_area, location))
    compact = []
    for frame in keyframes:
        if compact and frame[0] < compact[-1][0]:
            raise ValueError(f"{source}: 流速起点未递增，不能安全匹配原生积分")
        if compact and frame[0] == compact[-1][0]:
            if frame[1] != compact[-1][1]:
                raise ValueError(f"{source}: 存在瞬时高度跳变，标准RPE流速积分无法无损表达")
            conversion.resolutions.append({"source": frame[2], "action": "redundant_speed_height_keyframe", "time_s": float(frame[0])})
            conversion.warn("同时间同高度的冗余流速关键帧已明确登记，不产生额外可见事件")
            continue
        compact.append(frame)
    result = []
    for left, right in zip(compact, compact[1:]):
        effective_speed = (right[1] - left[1]) / (right[0] - left[0])
        value = float(effective_speed * Fraction(9, 2))
        result.append(conversion.event(left[0], right[0], value, value, left[2] + ":native_height_slope"))
    # Native height becomes constant after its final (last-note + 1s) keyframe.
    # RPE otherwise extends its last speed through longer motion events.
    result.append(conversion.event(native_max_s, max(native_max_s, target_max_s), 0, 0, source + ":native_height_after_end"))
    return result


def convert_official(chart, info=None):
    """Convert one already decoded native object; performs no file I/O.

    Returns an ordinary RPE dict plus ``pamos`` provenance and bounded internal
    package metadata. ``ValueError`` means the complete chart is unsupported;
    the caller should archive raw bytes and report the reason, not drop notes.
    """
    if not isinstance(chart, dict):
        raise ValueError("仅支持原生Phigros v1/v3 JSON对象；PEC需要独立解析器")
    _check_tree(chart)
    source_bytes = canonical_bytes(chart)
    if len(source_bytes) > MAX_JSON_BYTES:
        raise ValueError("原生JSON超过32 MiB安全限额")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    del source_bytes
    version = chart.get("formatVersion")
    if isinstance(version, bool) or not isinstance(version, int) or version not in (1, 3):
        raise ValueError("仅支持formatVersion=1或3，不猜测其他格式")
    if has_noise(chart):
        raise ValueError("原生谱面包含噪域/BlockArea，当前转换器不支持；原件须只读保留")
    _reject_extensions(chart)
    info = {} if info is None else info
    if not isinstance(info, dict):
        raise ValueError("info必须是已解析的元数据对象")
    _check_tree(info)
    if len(canonical_bytes(info)) > 256 * 1024:
        raise ValueError("info元数据超过256 KiB限额")
    source_info = copy.deepcopy(info)
    native_lines = _array(chart.get("judgeLineList"), "judgeLineList")
    if not 1 <= len(native_lines) <= MAX_LINES:
        raise ValueError("原生判定线数量必须为1..512")
    bpms = []
    total_notes = total_events = 0
    last_note_s = Fraction(0)
    for line_index, line in enumerate(native_lines):
        path = f"judgeLineList[{line_index}]"
        if not isinstance(line, dict):
            raise ValueError(f"{path}: 判定线必须为对象")
        bpm = _number(line.get("bpm"), path + ".bpm", 10000)
        if bpm <= 0:
            raise ValueError(f"{path}: BPM必须为正")
        bpms.append(Fraction(str(bpm)))
        tick_seconds = Fraction(60, 32) / bpms[-1]
        for side in ("notesAbove", "notesBelow"):
            notes = _array(line.get(side), path + "." + side)
            total_notes += len(notes)
            for index, note in enumerate(notes):
                location = f"{path}.{side}[{index}]"
                if not isinstance(note, dict) or not NOTE_FIELDS <= set(note):
                    raise ValueError(f"{location}: 原生音符缺少客户端要求的字段")
                kind = note["type"]
                if isinstance(kind, bool) or not isinstance(kind, int) or kind not in TYPE_MAP:
                    raise ValueError(f"{location}: 未识别的原生音符类型，拒绝删除")
                start = _fraction(note["time"], location + ".time")
                hold = _fraction(note["holdTime"], location + ".holdTime")
                if kind == 3 and hold <= 0:
                    raise ValueError(f"{location}: Hold持续时间必须为正")
                for field in ("positionX", "speed", "floorPosition"):
                    _number(note[field], location + "." + field)
                last_note_s = max(last_note_s, (start + (hold if kind == 3 else 0)) * tick_seconds)
        for name in EVENT_NAMES:
            total_events += len(_array(line.get(name), path + "." + name))
        if total_notes > MAX_NOTES or total_events > MAX_SOURCE_EVENTS:
            raise ValueError("原生音符/事件数量超出安全上限，拒绝截断")
    reference_bpm = native_lines[0]["bpm"]
    conversion = _Conversion(reference_bpm)
    native_max_s = last_note_s + 1
    converted = []
    motion_end_s = Fraction(0)
    for line_index, line in enumerate(native_lines):
        path = f"judgeLineList[{line_index}]"
        tick_seconds = Fraction(60, 32) / bpms[line_index]
        move_x, move_y = _motion_track(line["judgeLineMoveEvents"], tick_seconds, "move", path + ".judgeLineMoveEvents", conversion, version)
        rotate, = _motion_track(line["judgeLineRotateEvents"], tick_seconds, "rotate", path + ".judgeLineRotateEvents", conversion)
        alpha, = _motion_track(line["judgeLineDisappearEvents"], tick_seconds, "alpha", path + ".judgeLineDisappearEvents", conversion)
        # Track ends can use official far-future sentinels. Keep them; do not
        # clip the authored motion to the music length without authorization.
        for track in (move_x, move_y, rotate, alpha):
            for event in track:
                beat = Fraction(event["endTime"][0]) + Fraction(event["endTime"][1], event["endTime"][2])
                motion_end_s = max(motion_end_s, beat * 60 / conversion.reference)
        unknown = _unknown(line, LINE_FIELDS)
        if unknown:
            conversion.warn("存在未识别判定线字段：保存在pamosNative.unknown_fields，未假称实现其运行时语义")
        target = {"Name": f"Native line {line_index}", "Texture": "line.png", "father": -1, "bpmfactor": 1,
                  "isCover": 1, "rotateWithFather": False, "zOrder": 0, "Group": 0,
                  "notes": [], "eventLayers": [{"moveXEvents": move_x, "moveYEvents": move_y,
                       "rotateEvents": rotate, "alphaEvents": alpha, "speedEvents": []}],
                  "extended": {}, "alphaControl": [], "posControl": [], "sizeControl": [], "yControl": [], "skewControl": [],
                  "pamosNative": {"source": path, "bpm": line["bpm"], "unknown_fields": unknown,
                       "declared_counts": {key: line[key] for key in ("numOfNotes", "numOfNotesAbove", "numOfNotesBelow") if key in line}}}
        for side, above in (("notesAbove", 1), ("notesBelow", 2)):
            for index, note in enumerate(line[side]):
                location = f"{path}.{side}[{index}]"
                start = Fraction(str(note["time"])) * tick_seconds
                end = start + (Fraction(str(note["holdTime"])) * tick_seconds if note["type"] == 3 else 0)
                unknown_note = _unknown(note, NOTE_FIELDS)
                unused = {"floorPosition": note["floorPosition"]}
                if note["type"] == 3:
                    unused["speed"] = note["speed"]
                    if note["speed"] != 1:
                        conversion.warn("Hold自身speed按锁定原生客户端忽略并映射为1；原数值保存在音符pamosNative.unused_fields")
                elif note["holdTime"] != 0:
                    unused["holdTime"] = note["holdTime"]
                    conversion.warn("非Hold的holdTime不参与原生运行时；原字段保存在unused_fields")
                if unknown_note:
                    conversion.warn("存在未识别音符字段：保存在音符pamosNative.unknown_fields，未静默删除或推定标签")
                target["notes"].append({"type": TYPE_MAP[note["type"]], "startTime": conversion.beat(start), "endTime": conversion.beat(end),
                    "positionX": _number(note["positionX"] * (1215 / 16), location + ".mappedPositionX"),
                    "above": above, "isFake": 0, "speed": 1 if note["type"] == 3 else note["speed"],
                    "alpha": 255, "size": 1, "visibleTime": 999999, "yOffset": 0,
                    "pamosId": f"native_{line_index}_{above}_{index}",
                    "pamosNative": {"source": location, "unused_fields": unused, "unknown_fields": unknown_note}})
        converted.append(target)
    target_max_s = max(last_note_s, motion_end_s) + 1
    for index, line in enumerate(native_lines):
        converted[index]["eventLayers"][0]["speedEvents"] = _speed_track(line["speedEvents"], Fraction(60, 32) / bpms[index],
            native_max_s, target_max_s, f"judgeLineList[{index}].speedEvents", conversion)
    native_offset = _fraction(chart.get("offset"), "offset", 86400)
    package_offset = _fraction(info.get("offset", 0), "info.offset", 86400)
    meta_offset_ms = round(native_offset * 1000)
    residual = native_offset - Fraction(meta_offset_ms, 1000)
    playback_info = copy.deepcopy(info)
    playback_info.update({"format": "rpe", "useRpe170Speed": True, "useRpen": False,
                          "offset": float(package_offset + residual)})
    if residual:
        conversion.warn("原生offset包含非整数毫秒：META存最近整数，精确残差保留在包info.offset；当前只合并整毫秒的导出器会明确拒绝该情况")
    root_unknown = _unknown(chart, ROOT_FIELDS)
    if root_unknown:
        conversion.warn("存在未识别原生根字段：保存在pamos.native_unmapped_fields，运行时不作支持承诺")
    if len(set(bpms)) > 1:
        conversion.warn("不同判定线BPM已映射到统一记账拍轴；这不是从音频推断的全曲变BPM，也不保证原编辑器拍坐标往返")
    if "numOfNotes" in chart and chart["numOfNotes"] != total_notes:
        conversion.warn("原生numOfNotes与实际音符数组数量不一致；保留声明值并转换全部实际音符")
    limits = ["仅原生Phigros JSON v1/v3；PEC、噪域、shader、父线及其他扩展机制不支持",
              "固定全局BPM只是作者时标归一化，不能解释为音乐tempo检测或完整变BPM还原",
              "线性运动/流速按锁定Phira-Pro运行时重建；事件覆盖、间隙、负起点等规范化有逐项provenance，不承诺编辑器结构无损",
              "原生floorPosition在锁定客户端中不参与渲染；Hold speed按原生规则固定1",
              "Python有理数到客户端f32运算不承诺位级一致；有理拍分母上限1000000，超出1微秒误差拒绝",
              "原生客户端与RPE的遮罩/线宽/下侧Hold显示可能不同，需人工对照",
              "原生JSON由调用者单独只读保存；此文件不是原生格式的无损备份",
              "转换回归、音画同步与Phira-Pro实际导入试玩 NOT RUN"]
    warnings = list(conversion.warnings) + ["格式归一化不授予训练/分发权限，不自动确认人工对齐或真人可玩性"]
    result = {"BPMList": [{"bpm": reference_bpm, "startTime": [0, 0, 1]}],
              "META": {"RPEVersion": 170, "offset": meta_offset_ms, "name": str(info.get("name", "")),
                       "composer": str(info.get("composer", "")), "charter": str(info.get("charter", "")),
                       "level": str(info.get("level", ""))},
              "judgeLineGroup": ["Native import"], "judgeLineList": converted,
              "pamos": {"schema_version": "1.0.0", "chart_mode": "regular", "key_count": None,
                        "source_format": "PHIGROS_NATIVE", "source_format_version": version,
                        "mapping_version": MAPPING_VERSION, "generator": "format_adapter",
                        "source_native_canonical_sha256": source_hash, "source_info": source_info,
                        "native_unmapped_fields": root_unknown, "declared_note_count": chart.get("numOfNotes"),
                        "converted_note_count": total_notes, "source_event_count": total_events,
                        "converted_event_count": conversion.target_events, "event_resolutions": conversion.resolutions,
                        "offset_mapping": {"native_offset_s": float(native_offset), "source_info_offset_s": float(package_offset),
                                           "rpe_meta_offset_ms": meta_offset_ms, "rpe_info_offset_s": float(package_offset + residual),
                                           "direction": "audio_time=chart_time+META.offset/1000+info.offset"},
                        "time_mapping": {"native_ticks_per_beat": 32, "reference_bpm": reference_bpm,
                                         "per_line_bpm": [line["bpm"] for line in native_lines],
                                         "max_rational_time_error_s": conversion.max_time_error_s,
                                         "music_bpm_inferred": False},
                        "compatibility_limits": limits, "warnings": warnings, "client_playtest": "NOT RUN"},
              "_pamos_import": {"container": "normalized_official", "info_format": "yaml", "info": playback_info,
                                "warnings": warnings, "parser_version": MAPPING_VERSION}}
    _check_tree(result)
    if len(canonical_bytes(result)) > MAX_JSON_BYTES:
        raise ValueError("转换后的RPE超过32 MiB安全限额；原件保留，不截断音符或provenance")
    return result

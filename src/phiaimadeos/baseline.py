"""Reproducible onset-driven rule draft, explicitly not a trained model."""
from __future__ import annotations

import copy
import math
import random

from .formats import make_chart, _event, seconds_to_beat

BASELINE_VERSION = "onset-fixedlane-rules-1.0.0"


def generate_baseline(analysis, conditions):
    effective = copy.deepcopy(conditions)
    mode = effective.get("chart_mode", "regular")
    key_count = effective.get("key_count")
    if mode not in {"regular", "pure_keys", "anomaly"}:
        raise ValueError("未知生成模式")
    if effective.get("special_features"):
        raise ValueError("规则基线没有经认证的特殊机制；不能生成噪域或宣称支持异像扩展")
    if mode == "pure_keys" and key_count not in (4, 5, 6):
        raise ValueError("纯配置必须选择4/5/6键")
    if mode != "pure_keys" and key_count is not None:
        raise ValueError("常规/异像模式 key_count 必须为空")
    overrides = []
    if mode == "pure_keys":
        for field, value in (("performance_intensity", 0), ("performance_style", "none")):
            if effective.get(field) != value:
                overrides.append({"field": field, "requested": effective.get(field), "effective": value})
            effective[field] = value
        if effective.get("generation_priority") == "performance":
            effective["generation_priority"] = "playability"
            overrides.append({"field": "generation_priority", "requested": "performance", "effective": "playability"})
    level = effective.get("difficulty_value", 15)
    difficulty = effective.get("difficulty_class", "IN")
    ranges = {"EZ": (0, 10), "HD": (11, 14), "IN": (14, 17), "AT": (15, 18)}
    if difficulty not in ranges or isinstance(level, bool) or not isinstance(level, int) or not ranges[difficulty][0] <= level <= ranges[difficulty][1]:
        raise ValueError("难度类别/数值不符合产品范围")
    wildness = effective.get("wildness", 30)
    intensity = effective.get("performance_intensity", 50)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100
           for value in (wildness, intensity)):
        raise ValueError("狂野度/演出强度必须在0..100")
    duration = float(analysis["duration_s"])
    if not math.isfinite(duration) or not 0 < duration <= 7200:
        raise ValueError("分析时长无效")
    bpm = analysis.get("bpm")
    warnings = ["baseline_only：按传统 DSP onset 与确定性规则生成，未加载任何训练权重",
                "难度/狂野度为规则目标；没有真人可玩性或难度认证", "Phira-Pro 导入试玩 NOT RUN"]
    if bpm is None:
        bpm = 120.0
        warnings.append("DSP 没有可靠 BPM，拍坐标使用明确标记的120 BPM参考；音符仍使用原 onset 秒数")
    if not isinstance(bpm, (int, float)) or not math.isfinite(bpm) or not 0 < bpm <= 1000:
        raise ValueError("分析 BPM 无效")
    onset_times = analysis.get("onsets_s", [])
    evidence = sorted(set(float(time) for time in onset_times if isinstance(time, (int, float)) and math.isfinite(time) and 0.12 <= time <= duration - 0.08))
    source = "spectral_flux_onsets"
    if not evidence:
        evidence = sorted(set(float(time) for time in analysis.get("beat_times_s", [])
                              if isinstance(time, (int, float)) and math.isfinite(time) and 0.12 <= time <= duration - 0.08))
        source = "estimated_beat_grid"
        warnings.append("没有 onset 峰，使用估计节拍网格；此网格必须人工试听确认")
    if not evidence:
        raise ValueError("音频没有可用 onset/beat 证据；不能生成有意义的规则初稿")
    minimum_gap = max(0.095, 0.34 - level * 0.012)
    selected, last = [], -math.inf
    for time in evidence:
        if time - last >= minimum_gap:
            selected.append(time)
            last = time
    if len(selected) > 50000:
        raise ValueError("规则初稿音符证据过多，请缩短音频或分段处理")
    seed = effective.get("seed", 42)
    seed = 42 if seed is None else int(seed)
    rng = random.Random(seed)
    lanes = key_count if mode == "pure_keys" else 7
    occupied_until = [-math.inf] * lanes
    notes, last_lane = [], -1
    line_count = 1 if mode == "pure_keys" or intensity < 65 else 2
    for index, time in enumerate(selected):
        available = [lane for lane in range(lanes) if occupied_until[lane] <= time - 0.04]
        if not available:
            # This can only happen when every lane is held; no input label is being
            # discarded because these are newly proposed rule events, not imports.
            continue
        if wildness >= 60 and index % 4 < 3:
            preferred = (last_lane + 1) % lanes
        else:
            preferred = rng.choice(available)
        lane = preferred if preferred in available else rng.choice(available)
        if lane == last_lane and len(available) > 1 and wildness < 75:
            lane = rng.choice([value for value in available if value != lane])
        next_time = selected[index + 1] if index + 1 < len(selected) else duration
        kind, end = "TAP", time
        if index % 13 == 7 and next_time - time > 0.26 and level >= 5:
            kind = "HOLD"
            end = min(duration - 0.05, time + min(1.2, max(0.25, (next_time - time) * 0.8)))
            occupied_until[lane] = end
        elif mode != "pure_keys" and level >= 11:
            if index % 11 == 5:
                kind = "FLICK"
            elif index % 9 == 4:
                kind = "DRAG"
        line_id = f"line_{index % line_count}"
        note = {"id": f"baseline_{index}_0", "kind": kind, "time_s": time, "end_time_s": end,
                "line_id": line_id, "x": (lane - (lanes - 1) / 2) * (150 if mode != "pure_keys" else 1),
                "lane_index": lane if mode == "pure_keys" else None, "above": 1, "fake": False}
        notes.append(note)
        if level >= 12 and index % max(4, 12 - int(wildness / 15)) == 0 and len(available) > 1:
            other_lanes = [other for other in available if other != lane]
            other = max(other_lanes, key=lambda value: abs(value - lane))
            notes.append({**note, "id": f"baseline_{index}_1", "kind": "TAP", "end_time_s": time,
                          "x": (other - (lanes - 1) / 2) * (150 if mode != "pure_keys" else 1),
                          "lane_index": other if mode == "pure_keys" else None})
        last_lane = lane
    chart = make_chart(notes, float(bpm), duration, effective)
    if mode != "pure_keys" and intensity > 0:
        # Ordinary scalar motion is bounded and uses public RPE linear events.
        # This is a rule motif, not learned performance or an anomaly mechanism.
        bpm_map = chart["BPMList"]
        segment_s = max(2.0, 480 / bpm)
        for line_index, line in enumerate(chart["judgeLineList"]):
            track = line["eventLayers"][0]
            track["moveXEvents"], track["moveYEvents"], track["rotateEvents"] = [], [], []
            start, step = 0.0, 0
            previous_x, previous_y, previous_angle = 0.0, 0.0, 0.0
            while start < duration + 4:
                end = min(duration + 4, start + segment_s)
                sign = 1 if (step + line_index) % 2 == 0 else -1
                target_x = sign * 100 * intensity / 100
                target_y = -40 + sign * 35 * intensity / 100
                target_angle = sign * 9 * intensity / 100
                first, last_beat = seconds_to_beat(start, bpm_map), seconds_to_beat(end, bpm_map)
                for name, value, final in (("moveXEvents", previous_x, target_x), ("moveYEvents", previous_y, target_y),
                                           ("rotateEvents", previous_angle, target_angle)):
                    track[name].append(_event(first, last_beat, value, final))
                previous_x, previous_y, previous_angle = target_x, target_y, target_angle
                start, step = end, step + 1
    if mode == "anomaly":
        warnings.append("anomaly 仅产出普通 RPE 线运动，尚未生成任何未经认证的特殊机制")
    chart["pamos"].update({"generator": "baseline_only", "baseline_version": BASELINE_VERSION,
                            "evidence_source": source, "seed": seed, "effective_conditions": effective,
                            "overrides": overrides, "warnings": warnings, "model_bundle_id": None,
                            "bpm_was_assumed": analysis.get("bpm") is None})
    return chart

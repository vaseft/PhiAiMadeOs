"""Private, bounded data contract shared by learned training and inference."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from .models import (FEATURE_DIM, FEATURE_RATE, MAX_AUDIO_FRAMES, MAX_LINES,
                     MAX_MOTION_EVENTS, MAX_NOTE_SLOTS, TIME_CELLS, VOICES,
                     KINDS, MOTION_PROPERTIES, MOTION_SCALES, MOTION_DICTIONARY_VERSION, ModelError,
                     encode_conditions)


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_path(root: Path, relative: str, *, exists=True) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ModelError("UNSAFE_PATH", "模型文件路径必须是项目根下的安全相对路径。")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ModelError("UNSAFE_PATH", "模型数据路径越出项目根目录。")
    if exists and not path.is_file():
        raise ModelError("FILE_UNAVAILABLE", "所需本地模型或数据文件不存在。", relative_path=relative)
    return path


def relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def finite(value, label):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelError("INVALID_TARGET", f"{label} 不是数字。") from exc
    if not math.isfinite(value):
        raise ModelError("INVALID_TARGET", f"{label} 包含 NaN/Inf。")
    return value


def assert_no_noise(value):
    """Fail closed for noise mechanisms at any nesting level, before target use."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(c for c in str(key).lower() if c.isalnum())
            if ("noise" in normalized or "噪域" in str(key)) and child not in (None, False, [], {}):
                raise ModelError("NOISE_TRAINING_FORBIDDEN", "含噪域的数据不得用于训练或学习式生成。")
            assert_no_noise(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_noise(child)


def read_manifest(path: Path, root: Path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    samples = manifest.get("samples", [])
    if not samples:
        raise ModelError("DATASET_EMPTY", "数据集没有可训练样本；没有创建训练权重。")
    groups, assets, features = {}, {}, {}
    for sample in samples:
        if not isinstance(sample, dict):
            raise ModelError("INVALID_MANIFEST", "manifest sample 必须是对象。")
        group, split = sample.get("group_id"), sample.get("split")
        if sample.get("group_method") == "exact_audio_bytes_only":
            raise ModelError("SONG_GROUP_UNCONFIRMED", "精确音频去重尚未经过人工歌曲簇确认，不能用于训练划分。")
        if not group or split not in ("train", "val", "test"):
            raise ModelError("INVALID_SPLIT", "每条样本必须有歌曲簇 group_id 和 train/val/test 划分。")
        if group in groups and groups[group] != split:
            raise ModelError("DATA_LEAKAGE", "同一歌曲簇跨越数据划分。")
        groups[group] = split
        for identity, table in ((sample.get("music_asset_id"), assets),
                                (sample.get("feature_sha256") or sample.get("feature_path"), features)):
            if identity is not None:
                if identity in table and table[identity] != group:
                    raise ModelError("DATA_LEAKAGE", "同源音频特征或音频资产被分入不同歌曲簇。")
                table[identity] = group
        if split == "test":
            continue  # Never open test charts or tune against test labels.
        actions = sample.get("allowed_actions")
        if (sample.get("license_status") != "explicit_permitted" or not isinstance(actions, list)
                or not all(isinstance(action, str) for action in actions) or "training" not in actions):
            raise ModelError("TRAINING_PERMISSION_REQUIRED", "样本没有明确训练许可；已拒绝整个训练请求。",
                             chart_id=sample.get("chart_id"))
        # Source provenance never substitutes for the explicit permission gate.
        assert_no_noise(sample.get("conditions", {}))
        safe_path(root, sample.get("chart_path"))
        safe_path(root, sample.get("feature_path"))
        for field, expected in (("feature_sample_rate", 22050), ("feature_hop", 882)):
            if sample.get(field, expected) != expected:
                raise ModelError("FEATURE_SCHEMA_MISMATCH", "模型需要22050Hz/882hop/25Hz的104维特征。", field=field)
        version = sample.get("feature_version") or manifest.get("feature_version")
        if not version:
            raise ModelError("FEATURE_VERSION_REQUIRED", "特征缓存必须记录提取器版本。")
        sample["feature_version"] = version
        encode_conditions(sample.get("conditions", {}))
    usable = [s for s in samples if s["split"] != "test"]
    if len({s["feature_version"] for s in usable}) != 1:
        raise ModelError("FEATURE_VERSION_MISMATCH", "同一轮训练不能混合不同特征提取器版本。")
    if not all(any(s["split"] == split for s in usable) for split in ("train", "val")):
        raise ModelError("DATASET_INSUFFICIENT", "真实训练需要互不重叠的 train 和 val 歌曲簇。")
    return manifest, usable


@dataclass(frozen=True)
class Window:
    sample_index: int
    start: float
    end: float


class SongCache:
    """One parsed chart and one mmap at a time; never retain an entire library."""
    def __init__(self, root: Path, samples: list[dict]):
        self.root, self.samples, self.index, self.song = root, samples, None, None

    def get(self, index):
        if self.index != index:
            self.song = None
            self.song = load_song(self.root, self.samples[index])
            self.index = index
        return self.song


def load_features(path: Path):
    import numpy as np
    try:
        values = np.load(path, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise ModelError("INVALID_FEATURE_CACHE", "特征缓存不能作为安全 NPY 文件读取。") from exc
    if values.ndim != 2 or values.shape[1] != FEATURE_DIM or not 1 <= values.shape[0] <= 180001 or values.dtype.kind != "f":
        raise ModelError("INVALID_FEATURE_SHAPE", "特征缓存必须是非空浮点 NPY [frames,104]。")
    return values


def load_song(root: Path, sample: dict):
    from . import formats
    chart_path = safe_path(root, sample["chart_path"])
    feature_path = safe_path(root, sample["feature_path"])
    for path, key in ((chart_path, "chart_file_sha256"), (feature_path, "feature_sha256")):
        actual_hash = file_hash(path)
        if sample.get(key) and actual_hash != sample[key]:
            raise ModelError("DATA_HASH_MISMATCH", "数据文件内容与 manifest 哈希不符。", chart_id=sample.get("chart_id"))
        sample[key] = actual_hash
    chart = formats.read_chart(chart_path)
    if sample.get("chart_sha256") not in (None, sample["chart_file_sha256"], formats.chart_hash(chart)):
        raise ModelError("DATA_HASH_MISMATCH", "谱面规范化哈希与 manifest 不一致。")
    if formats.has_noise(chart):
        raise ModelError("NOISE_TRAINING_FORBIDDEN", "含实际噪域的数据不得用于训练。")
    conditions = sample["conditions"]
    ir = formats.chart_to_ir(chart, conditions["chart_mode"], conditions.get("key_count"))
    if ir.get("unsupported_features"):
        raise ModelError("UNSUPPORTED_TARGET", "谱面解析含未支持目标，不能静默用于学习。", features=ir["unsupported_features"])
    features = load_features(feature_path)
    duration = features.shape[0] / FEATURE_RATE
    lines = ir.get("judge_lines", [])
    if not 1 <= len(lines) <= MAX_LINES:
        raise ModelError("LINE_CAPACITY_EXCEEDED", "当前模型支持 1..8 条判定线；没有截断。")
    by_id = {str(line["id"]): line for line in lines}
    ordered, visiting = [], set()

    def visit(line_id):
        if line_id in visiting:
            raise ModelError("INVALID_PARENT_DAG", "判定线父子关系包含循环。")
        if line_id in ordered:
            return
        visiting.add(line_id)
        parent = by_id[line_id].get("parent_id")
        if parent is not None:
            parent = str(parent)
            if parent not in by_id:
                raise ModelError("INVALID_PARENT_DAG", "父判定线引用不存在。")
            visit(parent)
        visiting.remove(line_id)
        ordered.append(line_id)

    for line_id in by_id:
        visit(line_id)
    line_ids = {line_id: i for i, line_id in enumerate(ordered)}
    parents, events = [], []
    for line_id in ordered:
        line = by_id[line_id]
        parent = line.get("parent_id")
        parents.append(-1 if parent is None else line_ids[str(parent)])
        raw = line.get("raw", {})
        if (formats.has_extended_features(raw) or formats.has_nontrivial_controls(raw)
                or raw.get("attachUI") not in (None, "", False) or raw.get("Texture", "line.png") != "line.png"):
            raise ModelError("UNSUPPORTED_TARGET", "当前运动字典不能表达扩展线事件、UI绑定或自定义线纹理。")
        if raw.get("bpmfactor", 1) != 1 or raw.get("isCover", 1) != 1:
            raise ModelError("UNSUPPORTED_TARGET", "当前运动模型尚不支持 bpmfactor 或遮罩变体。")
        layers = raw.get("eventLayers", [])
        if len(layers) > 1 and any(layer for layer in layers[1:] if any(layer.values())):
            raise ModelError("UNSUPPORTED_TARGET", "多 eventLayer 不能无损映射当前运动字典。")
        layer = layers[0] if layers else {}
        unknown = [k for k, v in layer.items() if k not in MOTION_PROPERTIES and v]
        if unknown:
            raise ModelError("UNSUPPORTED_TARGET", "发现运动模型未覆盖的事件类型。", fields=unknown)
        for prop, name in enumerate(MOTION_PROPERTIES):
            for event in layer.get(name, []):
                if (event.get("bezier", 0) or event.get("easingLeft", 0) != 0
                        or event.get("easingRight", 1) != 1 or event.get("linkgroup", 0)):
                    raise ModelError("UNSUPPORTED_TARGET", "当前模型不支持贝塞尔、裁切缓动或linkgroup。")
                offset = ir.get("offset_ms", 0) / 1000 + ir.get("info_offset_s", 0)
                start = formats.beat_to_seconds(event["startTime"], ir["bpm_map"]) + offset
                end = formats.beat_to_seconds(event["endTime"], ir["bpm_map"]) + offset
                easing = int(event.get("easingType", 1))
                if not 0 <= start <= end or not 1 <= easing <= 29:
                    raise ModelError("UNSUPPORTED_TARGET", "当前模型不支持负时间线事件、反向事件或未知缓动。")
                events.append({"time": start, "end": end, "line": line_ids[line_id], "property": prop,
                               "start_value": finite(event.get("start", 1 if prop == 4 else 0), "事件起值"),
                               "end_value": finite(event.get("end", event.get("start", 1 if prop == 4 else 0)), "事件终值"),
                               "easing": easing - 1})
    notes = []
    for note in ir.get("notes", []):
        raw = note.get("raw", {})
        if note.get("fake") or raw.get("isFake", 0):
            raise ModelError("UNSUPPORTED_TARGET", "当前训练目标未覆盖假音符，已拒绝而非丢弃。")
        kind = str(note["kind"]).upper()
        start, end = finite(note["time_s"], "音符时刻"), finite(note.get("end_time_s", note["time_s"]), "音符尾时刻")
        if finite(raw.get("visibleTime", 999999.0), "可见时间") < max(0, start) or raw.get("alpha", 255) != 255 or raw.get("size", 1) != 1:
            raise ModelError("UNSUPPORTED_TARGET", "当前放置模型未覆盖歌曲内延迟显现、透明度或音符缩放标签。")
        if kind not in KINDS or not 0 <= start < duration or end < start or end > duration + 1 / FEATURE_RATE:
            raise ModelError("UNSUPPORTED_TARGET", "音符类型或音频范围不受支持；没有裁掉标签。")
        if kind == "HOLD" and end <= start:
            raise ModelError("INVALID_HOLD", "Hold 必须有正持续时间。")
        x = finite(note["x"], "音符位置")
        if abs(x) > 675:
            raise ModelError("UNSUPPORTED_TARGET", "放置模型的训练范围为局部 X -675..675。")
        above = int(note.get("above", 1))
        if above not in (1, 2):
            raise ModelError("INVALID_TARGET", "above 标签必须为 1 或 2。")
        lane = note.get("lane_index")
        if conditions["chart_mode"] == "pure_keys":
            k = conditions["key_count"]
            if not isinstance(lane, int) or not 0 <= lane < k or abs(x - 675 * (-1 + 2 * (lane + 0.5) / k)) > 1e-3:
                raise ModelError("INVALID_LANE_TARGET", "纯配置音符必须已验证为固定 K 列。")
        notes.append({"time": start, "end": end, "kind": KINDS.index(kind),
                      "line": line_ids[str(note["line_id"])], "x": x, "above": above - 1,
                      "lane": lane, "speed": finite(raw.get("speed", 1), "音符速度"),
                      "y_offset": finite(raw.get("yOffset", 0), "音符偏移")})
    if any(not 0.1 <= n["speed"] <= 10 or abs(n["y_offset"]) > 450 for n in notes):
        raise ModelError("UNSUPPORTED_TARGET", "音符速度或偏移超出当前模型表达范围。")
    if conditions["chart_mode"] == "pure_keys":
        if len(lines) != 1 or parents != [-1]:
            raise ModelError("INVALID_PURE_KEYS_TARGET", "纯配置必须为单条静态无父线。")
        for prop in range(5):
            related = [e for e in events if e["property"] == prop]
            values = {e[field] for e in related for field in ("start_value", "end_value")}
            if len(values) > 1 or (prop in (0, 2) and values and values != {0.0}):
                raise ModelError("INVALID_PURE_KEYS_TARGET", "纯配置标签包含移动、旋转或其他线状态变化。")
        if any(n["above"] != 0 or n["y_offset"] != 0 or n["speed"] != 1 for n in notes):
            raise ModelError("UNSUPPORTED_TARGET", "纯配置模型当前仅支持上侧、零偏移、音符速度1的真实列标签。")
    # Events outside the song remain unsupported instead of disappearing from a window index.
    if any(e["time"] >= duration for e in events):
        raise ModelError("UNSUPPORTED_TARGET", "存在音频结束后开始的判定线事件，需显式整理数据后训练。")
    return {"features": features, "duration": duration, "parser_warnings": ir.get("warnings", []),
            "notes": sorted(notes, key=lambda n: (n["time"], n["line"], n["x"])),
            "events": sorted(events, key=lambda e: (e["time"], e["line"], e["property"])),
            "parents": parents, "conditions": conditions}


def select_notes(song, window):
    return [n for n in song["notes"] if window.start <= n["time"] < window.end]


def select_events(song, window):
    return [e for e in song["events"] if window.start <= e["time"] < window.end]


def build_windows(cache: SongCache):
    windows, report = [], []
    for index, sample in enumerate(cache.samples):
        song = cache.get(index)
        count, splits = 0, 0

        def add(start, end, depth=0):
            nonlocal count, splits
            window = Window(index, start, end)
            notes, events = select_notes(song, window), select_events(song, window)
            bins = [0] * TIME_CELLS
            for note in notes:
                bins[min(TIME_CELLS - 1, int((note["time"] - start) / (end - start) * TIME_CELLS))] += 1
            frames = min(len(song["features"]), math.ceil(end * FEATURE_RATE - 1e-8)) - max(0, math.floor(start * FEATURE_RATE + 1e-8))
            if len(notes) > MAX_NOTE_SLOTS or len(events) > MAX_MOTION_EVENTS or max(bins) > VOICES or frames > MAX_AUDIO_FRAMES:
                if depth >= 24 or end - start < 1e-5:
                    raise ModelError("DENSITY_UNSUPPORTED", "同时事件超出模型容量，拆窗仍不能完整表示；未丢标签。", chart_id=sample.get("chart_id"))
                splits += 1
                mid = (start + end) / 2
                add(start, mid, depth + 1)
                add(mid, end, depth + 1)
            else:
                windows.append(window)
                count += 1

        for frame in range(0, len(song["features"]), MAX_AUDIO_FRAMES):
            add(frame / FEATURE_RATE, min(len(song["features"]), frame + MAX_AUDIO_FRAMES) / FEATURE_RATE)
        report.append({"chart_id": sample.get("chart_id"), "group_id": sample["group_id"], "split": sample["split"],
                       "windows": count, "additional_splits": splits, "notes": len(song["notes"]), "motion_events": len(song["events"]),
                       "parser_warnings": song["parser_warnings"]})
    return windows, report


def feature_window(features, start, end):
    import numpy as np
    first = max(0, min(len(features) - 1, math.floor(start * FEATURE_RATE + 1e-8)))
    last = min(len(features), max(first + 1, math.ceil(end * FEATURE_RATE - 1e-8)))
    value = np.array(features[first:last], dtype=np.float32, copy=True)
    if len(value) > MAX_AUDIO_FRAMES or not np.isfinite(value).all():
        raise ModelError("INVALID_FEATURE_WINDOW", "音频窗口超限或包含 NaN/Inf。")
    return value


def note_queries(width):
    return [[(cell + 0.5) / TIME_CELLS, voice / (VOICES - 1), math.log1p(width),
             1 / TIME_CELLS, math.sin((cell + 0.5) / TIME_CELLS * math.tau),
             math.cos((cell + 0.5) / TIME_CELLS * math.tau), 0.0, 1.0]
            for cell in range(TIME_CELLS) for voice in range(VOICES)]


def note_vectors(notes, start, width):
    vectors = []
    for n in notes:
        vector = [(n["time"] - start) / width, math.log1p(max(0, n["end"] - n["time"]))]
        vector += [float(n["kind"] == k) for k in range(4)]
        vector += [0.0] * 8  # Placement must not see ground-truth line/x/lane.
        vector += [math.log1p(width), 1.0]
        vectors.append(vector)
    return vectors or [[0.0] * 16]


def line_vectors(events, parents, start, width, pure=False):
    """Carry state plus every current event, at most 64 + 8*5 context tokens.

    Original easing and boundaries remain explicit; no curved trajectory is
    substituted with a supposed linear ground truth.
    """
    result = []
    for line, parent in enumerate(parents):
        for prop in range(5):
            related = [e for e in events if e["line"] == line and e["property"] == prop]
            preceding = [e for e in related if e["time"] <= start]
            selected = [e for e in related if start < e["time"] < start + width]
            if preceding:
                selected.insert(0, max(preceding, key=lambda e: e["time"]))
            else:
                default = (0, -202.5 if pure else 0, 0, 255, 6)[prop]
                selected.insert(0, {"time": start, "end": start, "start_value": default, "end_value": default, "easing": 0})
            for event in selected:
                delta = event["time"] - start
                row = [line / 7.0, (parent + 1) / 8.0, math.copysign(math.log1p(abs(delta)), delta),
                       math.log1p(event["end"] - event["time"]),
                       event["start_value"] / MOTION_SCALES[prop], event["end_value"] / MOTION_SCALES[prop]]
                row += [float(prop == p) for p in range(5)] + [event["easing"] / 28.0]
                result.append(row)
    if len(result) > MAX_MOTION_EVENTS + MAX_LINES * 5:
        raise ModelError("LINE_CONTEXT_CAPACITY_EXCEEDED", "窗口线事件与延续状态超过容量，未截断。")
    return result


def fit_motion_dictionary(cache: SongCache, seed: int):
    """Bounded deterministic CPU k-means, exclusively on training songs.

    Reservoir sampling bounds fitting RAM; every original event still participates
    in supervised training and receives a nearest-family prototype label. Easing
    and original start/end boundaries remain independent, non-discarded labels.
    """
    import numpy as np
    import random
    rng = random.Random(seed)
    reservoirs, observed = {}, {}
    groups = set()
    for index, sample in enumerate(cache.samples):
        if sample["split"] != "train" or sample["conditions"]["chart_mode"] == "pure_keys":
            continue
        song = cache.get(index)
        groups.add(sample["group_id"])
        for event in song["events"]:
            prop = event["property"]
            row = [event["start_value"] / MOTION_SCALES[prop], event["end_value"] / MOTION_SCALES[prop]]
            bucket = reservoirs.setdefault(prop, [])
            observed[prop] = observed.get(prop, 0) + 1
            if len(bucket) < 8192:
                bucket.append(row)
            else:
                position = rng.randrange(observed[prop])
                if position < len(bucket):
                    bucket[position] = row
    if not reservoirs:
        raise ModelError("MOTION_TARGETS_MISSING", "没有可用于拟合运动原型的真实训练事件。")
    centers, properties = [], []
    per_family = 64 // len(reservoirs)
    for prop, bucket in sorted(reservoirs.items()):
        rows = np.unique(np.asarray(bucket, dtype=np.float32), axis=0)
        count = min(per_family, len(rows))
        chosen = [rows[0]]
        # Farthest-point initialization avoids unobserved fabricated prototypes.
        for _ in range(1, count):
            distances = ((rows[:, None] - np.asarray(chosen)[None]) ** 2).sum(-1).min(-1)
            chosen.append(rows[int(distances.argmax())])
        fitted = np.asarray(chosen, dtype=np.float32)
        for _ in range(20):
            assignments = ((rows[:, None] - fitted[None]) ** 2).sum(-1).argmin(-1)
            updated = np.asarray([rows[assignments == k].mean(0) if (assignments == k).any() else fitted[k] for k in range(count)], dtype=np.float32)
            if np.allclose(updated, fitted, atol=1e-6, rtol=0):
                fitted = updated
                break
            fitted = updated
        centers.extend(fitted.tolist())
        properties.extend([prop] * len(fitted))
    result = {"version": MOTION_DICTIONARY_VERSION, "centers": centers, "properties": properties,
              "fitting": "per-event-family-kmeans20-reservoir8192", "seed": seed,
              "training_group_ids": sorted(groups), "training_events_seen_by_family": observed,
              "easing_policy": "original_easing29_label_and_event_boundaries_retained"}
    result["sha256"] = canonical_hash(result)
    return result


def batch_for(stage, song, window, device):
    import torch
    width = window.end - window.start
    notes = select_notes(song, window)
    tensor = lambda v, dtype=torch.float32: torch.as_tensor(v, dtype=dtype, device=device).unsqueeze(0)
    common = {"features": tensor(feature_window(song["features"], window.start, window.end)),
              "conditions": tensor(encode_conditions(song["conditions"]))}
    targets = {}
    if stage == "note_rhythm":
        common.update(queries=tensor(note_queries(width)), key_count=song["conditions"].get("key_count") or 6)
        p, kind, residual, hold, lane = [0.0] * 192, [0] * 192, [0.0] * 192, [0.0] * 192, [0] * 192
        used = [0] * TIME_CELLS
        for n in notes:
            cell = min(31, int((n["time"] - window.start) / width * TIME_CELLS))
            slot = cell * VOICES + used[cell]
            used[cell] += 1
            if used[cell] > VOICES:
                raise ModelError("DENSITY_UNSUPPORTED", "训练索引与音符容量不符。")
            p[slot], kind[slot] = 1.0, n["kind"]
            residual[slot] = (n["time"] - window.start) / (width / TIME_CELLS) - cell - 0.5
            hold[slot], lane[slot] = math.log1p(n["end"] - n["time"]), n["lane"] or 0
        targets = {"presence": tensor(p), "kind": tensor(kind, torch.long), "residual": tensor(residual),
                   "hold": tensor(hold), "lane": tensor(lane, torch.long)}
    elif stage == "line_motion":
        events = select_events(song, window)
        common.update(queries=tensor([[i / 63, math.log1p(width), 0, 0, 0, 0, 0, 1] for i in range(64)]),
                      notes=tensor(note_vectors(notes, window.start, width)))
        targets = {"presence": tensor([1.0] * len(events) + [0.0] * (64 - len(events))),
                   "line_count": torch.tensor([len(song["parents"]) - 1], device=device),
                   "parents": tensor([p + 1 for p in song["parents"]], torch.long)}
        specs = {"line": (lambda e: e["line"], torch.long), "property": (lambda e: e["property"], torch.long),
                 "easing": (lambda e: e["easing"], torch.long), "start": (lambda e: (e["time"] - window.start) / width, torch.float32),
                 "duration": (lambda e: math.log1p(e["end"] - e["time"]), torch.float32)}
        for field, (getter, dtype) in specs.items():
            targets[field] = tensor([getter(e) for e in events] + [0] * (64 - len(events)), dtype)
        targets["values"] = tensor([[e["start_value"] / MOTION_SCALES[e["property"]], e["end_value"] / MOTION_SCALES[e["property"]]] for e in events] + [[0, 0]] * (64 - len(events)))
        dictionary = song["motion_dictionary"]
        prototypes = []
        for event in events:
            prop = event["property"]
            value = [event["start_value"] / MOTION_SCALES[prop], event["end_value"] / MOTION_SCALES[prop]]
            options = [i for i, family in enumerate(dictionary["properties"]) if family == prop]
            if not options:
                raise ModelError("MOTION_FAMILY_UNSEEN", "验证集含训练原型未覆盖的事件类别，不能伪造该类别的原型。")
            prototypes.append(min(options, key=lambda i: sum((a - b) ** 2 for a, b in zip(value, dictionary["centers"][i]))))
        targets["prototype"] = tensor(prototypes + [0] * (64 - len(events)), torch.long)
    else:
        common.update(queries=tensor(note_vectors(notes, window.start, width)),
                      lines=tensor(line_vectors(song["events"], song["parents"], window.start, width,
                                               pure=song["conditions"]["chart_mode"] == "pure_keys")),
                      key_count=song["conditions"].get("key_count") or 6)
        targets["valid"] = tensor([bool(notes)] * max(1, len(notes)), torch.bool)
        targets["line_count"] = len(song["parents"])
        for field in ("line", "above", "lane", "x", "y_offset", "speed"):
            dtype = torch.long if field in ("line", "above", "lane") else torch.float32
            scale = 675 if field == "x" else 450 if field == "y_offset" else 1
            targets[field] = tensor([(n[field] or 0) / scale if dtype == torch.float32 else n[field] or 0 for n in notes] or [0], dtype)
    return common, targets

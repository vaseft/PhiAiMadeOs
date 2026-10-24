"""One immutable chart cache and exact event windows for reference previews."""
from bisect import bisect_right
import threading

from .formats import chart_to_ir, _TempoMap
from .services import load_candidate
from .settings import file_hash

TRACKS = {"moveXEvents", "moveYEvents", "rotateEvents", "alphaEvents", "speedEvents"}


class TimelineCache:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.key = None
        self.ir = None
        self.tracks = {}

    def window(self, candidate_id, start_s, end_s):
        with self.lock:
            record = self.store.get("candidates", candidate_id)
            path = self.store.settings.path(record["chart_path"])
            # Still check immutable file integrity on cache hits; mtime alone
            # must never allow modified bytes to impersonate the old revision.
            digest = file_hash(path)
            if record.get("file_sha256") and digest != record["file_sha256"]:
                raise ValueError("候选文件字节发生变化，已停止预览")
            key = (candidate_id, digest, record["chart_sha256"], record["chart_mode"], record.get("key_count"))
            if key != self.key:
                # Release the previous large snapshot before loading another.
                self.key, self.ir, self.tracks = None, None, {}
                _, chart = load_candidate(candidate_id, self.store)
                ir = chart_to_ir(chart, record["chart_mode"], record.get("key_count"), copy_raw=False)
                tempo = _TempoMap(ir["bpm_map"])
                seconds = {}
                offset = ir["offset_ms"] / 1000 + ir.get("info_offset_s", 0)
                for line in ir["judge_lines"]:
                    scale = line["time_scale"]
                    for layer in line["raw"].get("eventLayers", []):
                        if not isinstance(layer, dict):
                            continue
                        for name, events in layer.items():
                            if name not in TRACKS or not isinstance(events, list) or not events:
                                continue
                            starts = []
                            for event in events:
                                beat = tuple(event["startTime"])
                                if beat not in seconds:
                                    seconds[beat] = tempo.to_seconds(list(beat))
                                starts.append(seconds[beat] * scale + offset)
                            order = sorted(range(len(events)), key=starts.__getitem__)
                            self.tracks[id(events)] = ([starts[index] for index in order], order)
                self.ir, self.key = ir, key
            ir = self.ir
            lines = []
            for line in ir["judge_lines"]:
                raw = line["raw"]
                layers = []
                for layer in raw.get("eventLayers", []):
                    if not isinstance(layer, dict):
                        layers.append(layer)
                        continue
                    window = {}
                    for name, events in layer.items():
                        index = self.tracks.get(id(events))
                        if index is None:
                            window[name] = events
                            continue
                        starts, order = index
                        left = max(0, bisect_right(starts, start_s) - 1)
                        right = max(left + 1, bisect_right(starts, end_s))
                        # Include the active predecessor and first future anchor
                        # when before the track. Never clip authored event times.
                        chosen = sorted(order[left:right])
                        window[name] = [events[index] for index in chosen]
                    layers.append(window)
                lines.append({**line, "raw": {**raw, "notes": [], "eventLayers": layers}})
            selected = [note for note in ir["notes"] if note["end_time_s"] >= start_s and note["time_s"] <= end_s]
            return {key: ir[key] for key in ("bpm_map", "offset_ms", "duration_s", "chart_mode", "key_count", "info_offset_s", "warnings")} | {
                "judge_lines": lines, "notes": selected, "time_mapping": ir.get("time_mapping"),
                "start_s": start_s, "end_s": end_s, "event_windowed": True}

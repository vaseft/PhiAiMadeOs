"""Bounded, real training-log curves; validation losses are not playability."""
from __future__ import annotations

from collections import defaultdict
import json
import math
import threading

STAGES = ("note_rhythm", "line_motion", "placement")
MAX_LOG_BYTES = 8 * 1024 * 1024


class TrainingAnalysis:
    def __init__(self):
        self.lock = threading.Lock()
        self.cached_key = None
        self.cached = None

    def read(self, path, run_id):
        if not path.is_file():
            return {"stages": [], "truncated": False, "message": "等待真实训练日志"}
        with self.lock:
            stat = path.stat()
            key = (run_id, stat.st_mtime_ns, stat.st_size)
            if key == self.cached_key:
                return self.cached
            train, validation = {s: {} for s in STAGES}, {s: {} for s in STAGES}
            truncated = stat.st_size > MAX_LOG_BYTES
            with path.open("rb") as handle:
                if truncated:
                    handle.seek(stat.st_size - MAX_LOG_BYTES)
                    handle.readline()  # Discard an incomplete first line.
                for raw in handle.read(MAX_LOG_BYTES).splitlines():
                    try:
                        row = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        continue  # A worker can be appending the final line.
                    if not isinstance(row, dict):
                        continue
                    name, phase = row.get("stage"), row.get("phase")
                    step, epoch = row.get("optimizer_step"), row.get("epoch")
                    loss = row.get("loss") if phase == "train" else row.get("validation_loss_song_macro")
                    if (name not in train or phase not in {"train", "validation"} or type(step) is not int
                            or type(epoch) is not int or type(loss) not in (float, int) or not math.isfinite(loss)):
                        continue
                    point = {"x": step, "loss": loss, "epoch": epoch}
                    if phase == "train":
                        # Retries cannot count a repeated optimizer step twice.
                        point["windows"] = max(1, int(row.get("accumulated_windows", 1)))
                        train[name][step] = point
                    else:
                        validation[name][epoch] = point
            stages = []
            for name in STAGES:
                training = sorted(train[name].values(), key=lambda p: p["x"])
                val = sorted(validation[name].values(), key=lambda p: p["epoch"])
                epoch_totals = defaultdict(lambda: [0., 0])
                for p in training:
                    epoch_totals[p["epoch"]][0] += p["loss"] * p["windows"]
                    epoch_totals[p["epoch"]][1] += p["windows"]
                latest = val[-1]["loss"] if val else None
                previous = val[-2]["loss"] if len(val) > 1 else None
                change = (latest - previous) / abs(previous) * 100 if previous is not None and previous != 0 else None
                trend = "insufficient"
                if change is not None:
                    trend = "improving" if change < 0 else "rising" if change > 0 else "flat"
                if len(val) >= 3 and val[-1]["loss"] > val[-2]["loss"] > val[-3]["loss"]:
                    epochs = [p["epoch"] for p in val[-3:]]
                    means = [epoch_totals[e][0] / epoch_totals[e][1] for e in epochs if epoch_totals[e][1]]
                    if len(means) == 3 and means[-1] < means[-2] < means[-3]:
                        trend = "possible_overfit"
                visible = training[-600:]
                floor = visible[0]["x"] if visible else 0
                visible_val = [p for p in val if p["x"] >= floor][-200:]
                latest_epoch = max(epoch_totals) if epoch_totals else None
                stages.append({"stage": name, "training": visible, "validation": visible_val,
                    "latest_validation": latest, "validation_change_percent": change, "trend": trend,
                    "latest_train_epoch_mean": epoch_totals[latest_epoch][0] / epoch_totals[latest_epoch][1] if latest_epoch else None,
                    "latest_validation_epoch": val[-1]["epoch"] if val else None})
            self.cached_key = key
            self.cached = {"stages": stages, "truncated": truncated,
                "message": "每阶段独立量纲；训练为真实批次损失，验证为独立歌曲簇宏平均损失。损失不是可玩性评分。"}
            return self.cached

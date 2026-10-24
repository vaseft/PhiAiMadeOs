"""Machine-local calibrated execution defaults; optimizer semantics stay explicit."""
import json
import math
from pathlib import Path

MICROBATCHES = (1, 2, 4, 8, 16, 32, 64, 128, 256)
RUNTIME_KEYS = ("microbatch", "grad_accum", "prefetch_batches", "prepare_workers", "vram_budget_gib")


def validate_runtime(value):
    batch = value.get("microbatch", 1)
    accumulation = value.get("grad_accum", 16)
    prefetch = value.get("prefetch_batches", 0)
    workers = value.get("prepare_workers", 0)
    budget = value.get("vram_budget_gib", 6.2)
    if type(batch) is not int or batch not in MICROBATCHES:
        raise ValueError("并行窗口数须为1/2/4/8/16/32/64/128/256")
    if type(accumulation) is not int or not 1 <= accumulation <= 128 or batch * accumulation > 2048:
        raise ValueError("梯度累积须为1..128，且每次更新不超过2048个窗口")
    if type(prefetch) is not int or prefetch not in (0, 1):
        raise ValueError("CPU预取须为0或1")
    if type(workers) is not int or not 0 <= workers <= 8:
        raise ValueError("CPU准备路数须为0（自动）或1..8")
    if type(budget) not in (int, float) or not math.isfinite(budget) or not 2 <= budget <= 7.2:
        raise ValueError("训练显存预算须为2..7.2 GiB")
    return {"microbatch": batch, "grad_accum": accumulation, "prefetch_batches": prefetch,
            "prepare_workers": workers, "vram_budget_gib": float(budget), "effective_batch_windows": batch * accumulation}


def save_runtime(root, value):
    from .settings import atomic_json, now
    runtime = {**validate_runtime(value), "source": "user", "updated_at": now(), "calibration_id": None}
    atomic_json(Path(root) / ".local/training-runtime.json", runtime)
    return runtime


def recommended_runtime(root):
    baseline = {**validate_runtime({}),
                "source": "baseline", "calibration_id": None}
    path = Path(root) / ".local/training-runtime.json"
    if not path.is_file() or path.stat().st_size > 16384:
        return baseline
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {**validate_runtime(value), "source": "user" if value.get("source") == "user" else "local_calibration",
                "calibration_id": value.get("calibration_id"), "updated_at": value.get("updated_at")}
    except (OSError, ValueError, TypeError):
        return baseline


def export_runtime_asset(root):
    """Let an already running older backend serve the safe display defaults."""
    from .settings import atomic_json
    assets = Path(root) / "web/dist/assets"
    if assets.is_dir():
        atomic_json(assets / "training-runtime.json", recommended_runtime(root), compact=True)

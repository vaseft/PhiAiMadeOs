"""Machine-local calibrated execution defaults; optimizer semantics stay explicit."""
import json
from pathlib import Path


def recommended_runtime(root):
    baseline = {"microbatch": 1, "grad_accum": 16, "prefetch_batches": 0, "effective_batch_windows": 16,
                "source": "baseline", "calibration_id": None}
    path = Path(root) / ".local/training-runtime.json"
    if not path.is_file() or path.stat().st_size > 16384:
        return baseline
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        batch, accumulation, prefetch = (value.get(key) for key in ("microbatch", "grad_accum", "prefetch_batches"))
        if (type(batch) is not int or batch not in (1, 2, 4, 8, 16) or type(accumulation) is not int
                or not 1 <= accumulation <= 128 or batch * accumulation != 16 or type(prefetch) is not int or prefetch not in (0, 1)):
            return baseline
        return {**baseline, "microbatch": batch, "grad_accum": accumulation, "prefetch_batches": prefetch,
                "source": "local_calibration", "calibration_id": value.get("calibration_id")}
    except (OSError, ValueError, TypeError):
        return baseline


def export_runtime_asset(root):
    """Let an already running older backend serve the safe display defaults."""
    from .settings import atomic_json
    assets = Path(root) / "web/dist/assets"
    if assets.is_dir():
        atomic_json(assets / "training-runtime.json", recommended_runtime(root), compact=True)

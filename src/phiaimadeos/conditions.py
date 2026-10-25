from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from .settings import get_settings


def normalize(request):
    value = deepcopy(request)
    overrides = []
    value.setdefault("condition_schema_version", "3.0.0")
    value.setdefault("seed", 42)
    value.setdefault("special_features", [])
    value.setdefault("key_count", None)
    value.setdefault("strict_playability", True)
    value.setdefault("generation_priority", "playability")
    if value.get("chart_mode") == "pure_keys":
        for key, effective in (("performance_intensity", 0), ("performance_style", "none")):
            if value.get(key) != effective:
                overrides.append({"field": key, "requested": value.get(key), "effective": effective, "reason": "固定 K 轨道要求判定线静止"})
            value[key] = effective
    schema = json.loads((get_settings().root / "schemas/generation_request.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError("；".join(f"{'.'.join(map(str,e.path))}: {e.message}" for e in errors[:8]))
    if value.get("chart_mode") == "anomaly" or value.get("special_features"):
        raise ValueError("异像特性尚无 Phira-Pro 实机能力证据，当前不可生成")
    return {"effective_conditions": value, "overrides": overrides}

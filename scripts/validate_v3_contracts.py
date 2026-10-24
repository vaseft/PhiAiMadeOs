#!/usr/bin/env python3
"""检查 V3 Agent 的 JSON Schema、示例及条件契约（非模型训练或 Phira 真机验收）。"""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("缺少 jsonschema。先运行 python -m pip install jsonschema")

ROOT = Path(__file__).resolve().parent.parent


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf8"))


def expect_valid(validator, value: dict, name: str):
    errors = list(validator.iter_errors(value))
    if errors:
        raise AssertionError(f"{name}: 应合法却不合法：{[e.message for e in errors]}")
    print(f"PASS valid: {name}")


def expect_invalid(validator, value: dict, name: str):
    errors = list(validator.iter_errors(value))
    if not errors:
        raise AssertionError(f"{name}: 应拒绝却错误放行")
    print(f"PASS invalid: {name}")


def main() -> None:
    schema = load("schemas/generation_request.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    examples = {}
    for name in (
        "generation_regular.json", "generation_pure_4k.json",
        "generation_pure_5k.json", "generation_pure_6k.json",
        "generation_anomaly.json",
    ):
        item = load("examples/" + name)
        expect_valid(validator, item, name)
        examples[name] = item
    for name in ("chart_ir.schema.json", "condition_label.schema.json", "capability_matrix.schema.json"):
        Draft202012Validator.check_schema(load("schemas/" + name))
        print(f"PASS schema: {name}")

    pure = examples["generation_pure_4k.json"]
    regular = examples["generation_regular.json"]
    anomaly = examples["generation_anomaly.json"]

    def change(base: dict, **updates) -> dict:
        result = copy.deepcopy(base)
        result.update(updates)
        return result

    negative = [
        (change(pure, key_count=None), "pure_keys without K"),
        (change(pure, key_count=7), "pure_keys K=7"),
        (change(pure, special_features=["visual_noise"]), "pure_keys anomaly effect"),
        (change(regular, key_count=6), "regular with key_count"),
        (change(regular, difficulty_class="EZ", difficulty_value=11), "EZ out of range"),
        (change(regular, difficulty_class="HD", difficulty_value=10), "HD out of range"),
        (change(regular, difficulty_class="IN", difficulty_value=18), "IN out of range"),
        (change(regular, difficulty_class="AT", difficulty_value=14), "AT out of range"),
        (change(regular, wildness=101), "wildness over 100"),
        (change(anomaly, key_count=4), "anomaly key_count not null"),
        (change(regular, special_features=["visual_noise"]), "regular anomaly effects"),
        (change(pure, generation_priority="performance"), "pure_keys performance priority"),
        (change(pure, layout_density_mode="6k_style"), "deprecated field"),
    ]
    for item, name in negative:
        expect_invalid(validator, item, name)
    # Schema permits a stale pure_keys performance setting, but the runtime
    # ConditionNormalizer MUST force its effective value to 0. The schema is
    # only the structural contract, not a substitute for runtime testing.
    stale = change(pure, performance_intensity=99, performance_style="ornate")
    expect_valid(validator, stale, "stale UI performance, runtime normalization required")
    print("PASS: v3 JSON contract examples checked. 尚未运行 GPU、模型、真实 RPE/Phira 兼容测试。")

if __name__ == "__main__":
    main()

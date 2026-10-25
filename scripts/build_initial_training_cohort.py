"""Select complete, already prepared songs without changing stable hold-outs."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preparation-id", required=True)
    args = parser.parse_args()
    if len(args.preparation_id) != 32 or any(c not in "0123456789abcdef" for c in args.preparation_id):
        raise ValueError("准备记录ID无效")
    os.environ.setdefault("PAMOS_ROOT", str(Path(__file__).resolve().parents[1]))
    from phiaimadeos.store import Store
    from phiaimadeos.settings import atomic_json, file_hash, new_id
    from phiaimadeos.training_prepare import PROFILE, _analysis, _register_dataset
    from phiaimadeos.training_readiness import sample_for_chart
    from phiaimadeos.dataset import build_manifest, stable_group_split
    from phiaimadeos._model_data import canonical_hash
    store = Store(); settings = store.settings
    folder = settings.data_dir / "training_preparation" / args.preparation_id
    destination = folder / "early-cohort.json"
    if destination.exists():
        raise ValueError("此准备批次已经登记初训队列，请读取已有记录，不能覆盖")
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if report.get("profile") != PROFILE:
        raise ValueError("准备配置版本不符")
    rows = []
    for item in report["items"]:
        if item["status"] != "ready":
            continue
        chart = store.get("charts", item["chart_id"])
        readiness = chart.get("training_readiness", {})
        if readiness.get("run_id") != args.preparation_id or readiness.get("status") != "ready":
            continue
        asset = store.get("assets", chart["music_asset_id"])
        if any(row.get("license_status") != "explicit_permitted" or "training" not in row.get("allowed_actions", []) for row in (chart, asset)):
            continue
        sample = sample_for_chart(chart, asset, _analysis(asset, settings), settings)
        rows.append((item, sample))
    selected, seen, inventory = [], set(), []
    for split, quota in (("train", 18), ("val", 4), ("test", 2)):
        candidates = sorted((pair for pair in rows if stable_group_split(pair[1]["group_id"], 42) == split),
            key=lambda pair: (pair[0]["windows"], pair[0]["events"], pair[0]["notes"]))
        count = 0
        for item, sample in candidates:
            if sample["group_id"] in seen:
                continue
            selected.append(sample); seen.add(sample["group_id"]); count += 1
            inventory.append({**item, "split": split, "group_id": sample["group_id"]})
            if count == quota:
                break
        if count != quota:
            raise ValueError(f"已准备的独立{split}歌曲簇尚不足{quota}个，请等待准备继续")
    manifest = build_manifest(selected, settings.data_dir / "datasets" / new_id(), seed=42)
    if manifest["split_version"] != "song-union-hash-80-10-10-v2" or manifest["split_counts"] != {"train": 18, "val": 4, "test": 2}:
        raise ValueError("初训队列的稳定拆分与选择不一致，未登记")
    manifest.update(source_preparation_id=args.preparation_id, selection_policy="first-prepared-low-window-complete-songs-stable-holdouts-v1")
    manifest["sha256"] = canonical_hash({k: v for k, v in manifest.items() if k not in {"sha256", "manifest_path"}})
    path = settings.path(manifest["manifest_path"])
    atomic_json(path, manifest, compact=True)
    record = _register_dataset(store, manifest)
    result = {"dataset_id": record["id"], "manifest_sha256": record["sha256"], "sample_count": len(selected),
        "split_counts": manifest["split_counts"], "window_counts": {split: sum(item["windows"] for item in inventory if item["split"] == split) for split in ("train", "val", "test")},
        "source_preparation_id": args.preparation_id, "inventory": inventory, "tests": "NOT RUN"}
    atomic_json(destination, result)
    store.event("training.initial_cohort_registered", record["id"], source_preparation_id=args.preparation_id,
        split_counts=result["split_counts"], split_version=manifest["split_version"])
    print(json.dumps({k: v for k, v in result.items() if k != "inventory"}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()

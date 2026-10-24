"""Explicit local source transitions, immutable lineage and split protection."""
from __future__ import annotations

import json
from pathlib import Path

from .settings import file_hash, new_id, now

PATIENCE = 8
IDENTITIES = ("group_id", "source_group_id", "music_asset_id", "audio_sha256", "feature_sha256")
SAMPLE_KEYS = (*IDENTITIES, "chart_id", "chart_file_sha256", "chart_sha256", "split", "license_status", "allowed_actions", "conditions")


def plateau_stages(record):
    return [name for name, stage in record.get("stages", {}).items()
            if stage.get("early_stopped") or (stage.get("best_epoch") is not None
                and stage.get("epochs_completed", 0) - stage["best_epoch"] >= PATIENCE)]


def read_run(settings, run_id):
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 100 or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError("来源运行ID无效")
    base = (settings.data_dir / "training").resolve()
    path = (base / run_id / "run_manifest.json").resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("来源训练记录不可用")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("run_id") != run_id:
        raise ValueError("来源训练记录身份不符")
    return record, path


class SourcePlanner:
    def __init__(self, store):
        self.store, self.settings = store, store.settings

    def manifest(self, dataset_id):
        dataset = self.store.get("datasets", dataset_id)
        path = self.settings.path(dataset["manifest_path"])
        if not path.is_file() or path.stat().st_size > 128 * 1024 * 1024 or file_hash(path) != dataset["sha256"]:
            raise ValueError("已登记训练源的文件大小或SHA校验不符")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("samples"), list):
            raise ValueError("训练源manifest格式无效")
        # Projection provenance can make a corpus manifest tens of MiB; retain
        # only identity/permission metadata while planning, never chart labels.
        compact = {k: raw.get(k) for k in ("feature_version", "split_version", "seed", "group_count", "split_counts")}
        compact["samples"] = [{k: p.get(k) for k in SAMPLE_KEYS} for p in raw["samples"]]
        return dataset, compact

    @staticmethod
    def sample_key(sample):
        return (sample["chart_id"], sample.get("chart_file_sha256") or sample.get("chart_sha256"), sample.get("feature_sha256"))

    def compatible(self, parent, target_id):
        ancestors = [*parent.get("source_lineage", []), {"run_id": parent["run_id"], "dataset_id": parent["dataset_id"],
                    "dataset_manifest_sha256": parent["dataset_manifest_sha256"]}]
        if len(ancestors) > 64:
            raise ValueError("已达到自动换源历史上限")
        splits, seen_training = {}, set()
        old_feature, split_version = None, None
        for ancestor in ancestors:
            dataset, metadata = self.manifest(ancestor["dataset_id"])
            if dataset["sha256"] != ancestor["dataset_manifest_sha256"]:
                raise ValueError("历史训练源已变化，拒绝自动换源")
            old_feature = metadata["feature_version"]
            split_version = metadata["split_version"]
            for sample in metadata["samples"]:
                for field in IDENTITIES:
                    if sample.get(field):
                        identity = ("group" if field in {"group_id", "source_group_id"} else field, sample[field])
                        if identity in splits and splits[identity] != sample["split"]:
                            raise ValueError("历史来源存在跨拆分污染")
                        splits[identity] = sample["split"]
                if sample["split"] == "train":
                    seen_training.add(self.sample_key(sample))
        dataset, metadata = self.manifest(target_id)
        if (metadata["feature_version"] != old_feature or metadata["split_version"] != split_version
                or metadata["seed"] != parent["config"]["seed"]):
            raise ValueError("训练源特征/拆分版本或种子不兼容")
        new_train, permissions, groups = set(), {}, {}
        parent_modes = set(parent.get("bundle", {}).get("supported_modes", []))
        for sample in metadata["samples"]:
            split = sample.get("split")
            if split not in {"train", "val", "test"}:
                raise ValueError("训练源缺少有效歌曲拆分")
            for field in IDENTITIES:
                if sample.get(field):
                    identity = ("group" if field in {"group_id", "source_group_id"} else field, sample[field])
                    if identity in splits and splits[identity] != split:
                        raise ValueError("新来源会改变历史歌曲拆分，拒绝自动换源")
                    if identity in groups and groups[identity] != split:
                        raise ValueError("新来源存在歌曲簇跨拆分")
                    groups[identity] = split
            if split == "test":
                continue  # Never open held-out charts or features.
            if sample.get("license_status") != "explicit_permitted" or "training" not in (sample.get("allowed_actions") or []):
                raise ValueError("训练源有未授权样本")
            for kind, key in (("charts", "chart_id"), ("assets", "music_asset_id")):
                identity = (kind, sample[key])
                if identity not in permissions:
                    record = self.store.get(kind, sample[key])
                    permissions[identity] = record.get("license_status") == "explicit_permitted" and "training" in record.get("allowed_actions", [])
                if not permissions[identity]:
                    raise ValueError("本机素材当前许可不允许训练")
            if sample.get("conditions", {}).get("chart_mode") not in parent_modes:
                raise ValueError("自动换源仅接受父模型已覆盖的模式")
            if split == "train":
                new_train.add(self.sample_key(sample))
        fresh = new_train - seen_training
        counts = metadata.get("split_counts") or {}
        if not fresh or not all(counts.get(k, 0) for k in ("train", "val")):
            raise ValueError("没有未使用的训练内容，不能用副本或旧批次循环换源")
        return {"dataset_id": target_id, "dataset_sha256": dataset["sha256"], "manifest_path": dataset["manifest_path"],
                "sample_count": dataset["sample_count"], "split_counts": counts, "new_training_samples": len(fresh),
                "source_lineage": ancestors}

    def next_source(self, parent):
        eligible, rejected = [], []
        for dataset in self.store.list("datasets"):
            if dataset["id"] == parent["dataset_id"]:
                continue
            try:
                eligible.append(self.compatible(parent, dataset["id"]))
            except (ValueError, KeyError, OSError) as exc:
                rejected.append({"dataset_id": dataset["id"], "reason": str(exc)[:500]})
        if not eligible:
            raise ValueError("没有未使用、已获授权且保持历史歌曲拆分的训练源，自动训练已停止")
        selected = max(eligible, key=lambda x: (x["new_training_samples"], x["sample_count"]))
        selected["rejected_source_count"] = len(rejected)
        return selected

    def request(self, parent, runtime):
        selected = self.next_source(parent)
        config = parent["config"]
        return {"dataset_id": selected["dataset_id"], "new_run_id": new_id(), "warm_start_run_id": parent["run_id"],
                "stage": config["stage"], "epochs": 1, "seed": config["seed"], "max_lines": config["max_lines"],
                "device": "cuda" if config["device"].startswith("cuda") else "cpu",
                **{k: runtime[k] for k in ("microbatch", "grad_accum", "prefetch_batches")},
                "simple_trainer": True, "progress_epoch_start": 0, "progress_floor": 0.,
                "source_transition": {**selected, "from_dataset_id": parent["dataset_id"], "from_run_id": parent["run_id"],
                    "created_at": now(), "reason": "validation_plateau", "patience": PATIENCE,
                    "trigger_stages": plateau_stages(parent), "optimizer_reset": True, "preserve_motion_dictionary": True}}


def guard_warm_start(root, run_id, target):
    """File-only guard for the standalone trainer; never opens held-out labels."""
    from .settings import Settings
    settings = Settings(Path(root))
    parent, _ = read_run(settings, run_id)
    if parent.get("training_state") != "complete":
        raise ValueError("换源只允许在完整一轮结束后使用最优权重")
    lineage = [*parent.get("source_lineage", []), {"run_id": run_id}]
    if len(lineage) > 64 or len({p["run_id"] for p in lineage}) != len(lineage):
        raise ValueError("来源历史过长或重复")
    identities, old_training = {}, set()
    for entry in lineage:
        record, _ = read_run(settings, entry["run_id"])
        path = settings.path(record["manifest_path"])
        if path.stat().st_size > 128 * 1024 * 1024 or file_hash(path) != record["dataset_manifest_sha256"]:
            raise ValueError("历史来源manifest校验不符")
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if (metadata.get("feature_version") != target.get("feature_version") or metadata.get("split_version") != target.get("split_version")
                or metadata.get("seed") != target.get("seed")):
            raise ValueError("换源特征或拆分版本不兼容")
        for sample in metadata["samples"]:
            for field in IDENTITIES:
                if sample.get(field):
                    identity = ("group" if field in {"group_id", "source_group_id"} else field, sample[field])
                    if identity in identities and identities[identity] != sample["split"]:
                        raise ValueError("历史来源歌曲拆分冲突")
                    identities[identity] = sample["split"]
            if sample["split"] == "train":
                old_training.add(SourcePlanner.sample_key(sample))
    for sample in target["samples"]:
        for field in IDENTITIES:
            identity = ("group" if field in {"group_id", "source_group_id"} else field, sample.get(field))
            if sample.get(field) and identity in identities and identities[identity] != sample["split"]:
                raise ValueError("换源会改变历史训练/验证/保留身份")
    if not {SourcePlanner.sample_key(s) for s in target["samples"] if s["split"] == "train"} - old_training:
        raise ValueError("换源缺少新的训练内容")
    return parent

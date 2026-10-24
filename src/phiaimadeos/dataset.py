"""Local manifests with explicit rights and deterministic song-group splitting."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import random
import uuid

import numpy as np

from .formats import canonical_bytes, read_chart, chart_to_ir, chart_hash, has_noise, _check_tree
from .audio import FEATURE_VERSION

MANIFEST_VERSION = "1.0.0"


def _root():
    from .settings import get_settings
    return Path(get_settings().root).resolve()


def _relative_file(path, root):
    if not isinstance(path, (str, Path)):
        raise ValueError("样本路径必须是项目根内的相对路径")
    text = str(path)
    candidate = Path(text)
    if candidate.is_absolute() or PureWindowsPath(text).is_absolute() or ".." in candidate.parts:
        raise ValueError("manifest 不接受绝对路径或目录穿越")
    resolved = (root / candidate).resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("样本路径经符号链接指向项目根以外") from exc
    if not resolved.is_file():
        raise ValueError("样本路径不是普通文件")
    return relative.as_posix(), resolved


def _sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(samples, output_dir, seed=42):
    """Validate every sample or reject all; no label is silently dropped.

    Groups require human identity or source-bound export/audio evidence.
    Exact audio hashes/asset IDs additionally merge groups. Discovery is a
    separate preparation step; building a manifest does not certify identity.
    """
    if not isinstance(samples, list) or not samples:
        raise ValueError("数据集至少需要一个明确授权的样本")
    if len(samples) > 100000:
        raise ValueError("数据集样本数超过安全限额")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("数据集 seed 必须为整数")
    root = _root()
    destination = Path(output_dir)
    destination = destination if destination.is_absolute() else root / destination
    destination = destination.resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError("manifest 输出必须位于项目根目录内") from exc
    prepared, seen, errors = [], set(), []
    allowed_modes = {"regular", "pure_keys", "anomaly"}
    for index, sample in enumerate(samples):
        try:
            if not isinstance(sample, dict):
                raise ValueError("sample 必须为对象")
            item = copy.deepcopy(sample)
            _check_tree(item)
            if item.get("license_status") != "explicit_permitted" or "training" not in item.get("allowed_actions", []):
                raise ValueError("缺少明确训练授权；需要 explicit_permitted 且 allowed_actions 包含 training")
            if not isinstance(item.get("allowed_actions"), list) or not all(isinstance(action, str) for action in item["allowed_actions"]):
                raise ValueError("allowed_actions 必须是显式字符串数组")
            # A source label is provenance, not a grant of rights. Explicit
            # per-record training permission is required above for every source.
            from .training_readiness import alignment_ready, training_group
            if not alignment_ready(item):
                raise ValueError("训练样本缺少人工对齐或哈希绑定的游戏导出元数据核对记录")
            for key in ("chart_id", "music_asset_id", "chart_path", "feature_path", "conditions"):
                if key not in item or item[key] is None:
                    raise ValueError(f"缺少字段 {key}")
            if not isinstance(item["chart_id"], str) or not item["chart_id"] or item["chart_id"] in seen:
                raise ValueError("chart_id 必须是唯一非空字符串")
            if not isinstance(item["music_asset_id"], str) or not item["music_asset_id"]:
                raise ValueError("music_asset_id 必须为非空字符串")
            group = item.get("group_id", item.get("song_group_id"))
            if not isinstance(group, str) or not group.strip():
                raise ValueError("必须明确给出歌曲簇 group_id，不能按谱面随机拆分")
            if training_group(item) != group:
                raise ValueError("歌曲簇缺少人工确认或有效导出身份/音频联合分组依据")
            conditions = item["conditions"]
            if not isinstance(conditions, dict):
                raise ValueError("conditions 必须为完整标签对象")
            if "chart_mode" not in conditions:
                raise ValueError("conditions.chart_mode 必须显式给出，不能静默填标签")
            mode = conditions.get("chart_mode", item.get("chart_mode"))
            key_count = conditions.get("key_count", item.get("key_count"))
            if mode not in allowed_modes:
                raise ValueError("训练需要明确 regular/pure_keys/anomaly 标签")
            if (mode == "pure_keys" and key_count not in (4, 5, 6)) or (mode != "pure_keys" and key_count is not None):
                raise ValueError("模式与 key_count 不一致")
            chart_relative, chart_path = _relative_file(item["chart_path"], root)
            feature_relative, feature_path = _relative_file(item["feature_path"], root)
            if feature_path.suffix.lower() != ".npy":
                raise ValueError("仅接受 NPY 音频特征")
            features = np.load(feature_path, mmap_mode="r", allow_pickle=False)
            if features.ndim != 2 or features.shape[1] != 104 or features.shape[0] < 1 or features.shape[0] > 180001:
                raise ValueError("特征形状必须为 [frames,104] 且不超过2小时")
            if features.dtype != np.float32:
                raise ValueError("特征 dtype 必须为 float32")
            for start in range(0, len(features), 8192):
                if not np.isfinite(features[start:start + 8192]).all():
                    raise ValueError("特征含非有限值")
            feature_frames = len(features)
            del features
            if item.get("feature_version") != FEATURE_VERSION:
                raise ValueError("不支持此 feature_version；不能静默迁移特征")
            if item.get("audio_sha256") is not None and (not isinstance(item["audio_sha256"], str) or len(item["audio_sha256"]) != 64
                                                         or any(c not in "0123456789abcdef" for c in item["audio_sha256"].lower())):
                raise ValueError("audio_sha256 必须为64位十六进制字符串")
            chart = read_chart(chart_path)
            ir = chart_to_ir(chart, mode, key_count, copy_raw=False)
            if has_noise(chart):
                raise ValueError("噪域只读，V1 禁止将含噪域样本加入训练")
            chart_digest, feature_digest = _sha_file(chart_path), _sha_file(feature_path)
            if item.get("chart_sha256") not in (None, chart_digest, chart_hash(chart)):
                raise ValueError("chart_sha256 与当前文件不一致")
            if item.get("feature_sha256") not in (None, feature_digest):
                raise ValueError("feature_sha256 与当前特征不一致")
            normalized_paths = []
            if isinstance(item.get("analysis"), dict):
                for key in ("feature_path", "waveform_path", "analysis_path"):
                    if item["analysis"].get(key):
                        nested = Path(item["analysis"][key])
                        if nested.is_absolute():
                            nested = nested.resolve(strict=True)
                            try:
                                nested = nested.relative_to(root)
                            except ValueError as exc:
                                raise ValueError("analysis 缓存路径必须位于项目根内") from exc
                        nested_relative, _ = _relative_file(nested, root)
                        item["analysis"][key] = nested_relative
                        normalized_paths.append("analysis." + key)
            # Preserve original labels, provenance, quality tags and unknown fields.
            # Explicit new normalized keys never replace the original source labels.
            item.update({"chart_path": chart_relative, "feature_path": feature_relative, "group_id": group,
                         "feature_version": FEATURE_VERSION, "feature_frames": feature_frames,
                         "feature_sample_rate": 22050, "feature_hop": 882, "chart_file_sha256": chart_digest,
                         "chart_sha256": item.get("chart_sha256") or chart_digest, "feature_sha256": feature_digest,
                         "parser_warnings": list(dict.fromkeys(list(item.get("parser_warnings", [])) + ir["warnings"])),
                         "unsupported_features": list(dict.fromkeys(list(item.get("unsupported_features", [])) + ir["unsupported_features"]))})
            if normalized_paths:
                item["normalized_paths"] = normalized_paths
            if item.get("split") is not None:
                item["source_split"] = item["split"]
            seen.add(item["chart_id"])
            prepared.append(item)
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            errors.append({"sample_index": index, "chart_id": sample.get("chart_id") if isinstance(sample, dict) else None,
                           "code": "SAMPLE_UNSUPPORTED", "message": str(exc)})
    if errors:
        raise ValueError(json.dumps({"code": "DATASET_REJECTED", "message": "未丢弃任何样本；请修正全部问题后重建", "errors": errors}, ensure_ascii=False))
    # Union exact-source identities before splitting, including hashes that reveal
    # two user groups as the same audio. Never let a chart-level seed split them.
    parents = {item["group_id"]: item["group_id"] for item in prepared}
    def find(group):
        while parents[group] != group:
            parents[group] = parents[parents[group]]
            group = parents[group]
        return group
    def merge(left, right):
        a, b = find(left), find(right)
        if a != b:
            parents[max(a, b)] = min(a, b)
    identities = {}
    for item in prepared:
        keys = [("music_asset_id", item["music_asset_id"])]
        if item.get("audio_sha256"):
            keys.append(("audio_sha256", item["audio_sha256"]))
        for key in keys:
            if key in identities:
                merge(item["group_id"], identities[key])
            else:
                identities[key] = item["group_id"]
    groups = sorted({find(item["group_id"]) for item in prepared})
    random.Random(int(seed)).shuffle(groups)
    count = len(groups)
    if count >= 3:
        validation_count = max(1, round(count * 0.1))
        test_count = max(1, round(count * 0.1))
    elif count == 2:
        validation_count, test_count = 1, 0
    else:
        validation_count = test_count = 0
    training_count = count - validation_count - test_count
    assignments = {group: ("train" if index < training_count else "val" if index < training_count + validation_count else "test")
                   for index, group in enumerate(groups)}
    warnings = ["按已记录歌曲簇与精确音频身份联合拆分；自动导出身份/有序chroma分组不保证识别全部变速与重混版本",
                "训练/GPU/独立锁定测试集评估 NOT RUN"]
    if count < 10:
        warnings.append("歌曲簇不足10个，拆分不能代表泛化能力；小样本可能缺少 val/test")
    for item in prepared:
        canonical_group = find(item["group_id"])
        if canonical_group != item["group_id"]:
            item["source_group_id"] = item["group_id"]
        item["group_id"] = canonical_group
        item["split"] = assignments[canonical_group]
    identifier = uuid.uuid4().hex
    manifest = {"id": identifier, "version": MANIFEST_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "feature_version": FEATURE_VERSION, "sample_rate": 22050, "hop": 882, "feature_dim": 104,
                "seed": int(seed), "split_version": "song-union-shuffle-80-10-10-v1", "samples": prepared,
                "group_count": count, "split_counts": {split: sum(item["split"] == split for item in prepared) for split in ("train", "val", "test")},
                "warnings": warnings, "sha256_scope": "canonical manifest excluding sha256 and manifest_path"}
    manifest["sha256"] = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"manifest-{identifier}.json"
    manifest["manifest_path"] = path.relative_to(root).as_posix()
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    return manifest

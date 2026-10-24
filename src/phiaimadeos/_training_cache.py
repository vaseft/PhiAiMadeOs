"""Private JSON projection cache, bound to inputs and implementation hashes."""
from __future__ import annotations

from functools import lru_cache
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import zlib

VERSION = "exact-song-projection-json-v1"
MAX_BYTES = 256 * 1024 * 1024
FIELDS = ("duration", "parser_warnings", "notes", "events", "parents", "conditions", "max_lines", "training_projection")


def _digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=1)
def _implementation():
    base = Path(__file__).parent
    return {name: _digest(base / name) for name in ("_model_data.py", "_training_cache.py", "models.py", "formats.py", "_geometry.py")}


def _replace(source, destination):
    for attempt in range(9):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 8:
                raise
            time.sleep(min(.02 * 2 ** attempt, .25))


def _atomic(path, data):
    fd, temp = tempfile.mkstemp(prefix=".projection-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _restore(data, root, sample):
    from ._model_data import load_features, safe_path
    song = dict(data)
    song["features"] = load_features(safe_path(root, sample["feature_path"]))
    song["event_starts"] = [event["time"] for event in song["events"]]
    song["note_starts"] = [note["time"] for note in song["notes"]]
    tracks = {}
    for event in song["events"]:
        tracks.setdefault((event["line"], event["property"]), []).append(event)
    song["event_tracks"] = {key: ([event["time"] for event in rows], rows) for key, rows in tracks.items()}
    return song


def load(root, sample, max_lines, uncached):
    from ._model_data import ModelError, safe_path, canonical_hash
    root = Path(root).resolve()
    actual = {}
    for field, expected in (("chart_path", "chart_file_sha256"), ("feature_path", "feature_sha256")):
        actual[expected] = _digest(safe_path(root, sample[field]))
        if sample.get(expected) and sample[expected] != actual[expected]:
            raise ModelError("DATA_HASH_MISMATCH", "源文件与manifest哈希不符，未使用解析缓存。")
        sample[expected] = actual[expected]
    identity = {"version": VERSION, "inputs": actual, "conditions": sample["conditions"],
                "max_lines": max_lines, "implementation": _implementation(), "chart_sha256": sample.get("chart_sha256")}
    key = canonical_hash(identity)
    folder = (root / "data/training_cache/projections").resolve()
    if not folder.is_relative_to(root):
        raise ModelError("UNSAFE_PATH", "训练解析缓存指向项目根以外。")
    folder.mkdir(parents=True, exist_ok=True)
    metadata_path = folder / (key + ".json")
    try:
        if metadata_path.stat().st_size > 8192:
            raise ValueError("cache metadata too large")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        digest = metadata["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid digest")
        blob = folder / (key + "-" + digest + ".json.gz")
        if blob.stat().st_size > MAX_BYTES:
            raise ValueError("compressed cache too large")
        with gzip.open(blob, "rb") as stream:
            encoded = stream.read(MAX_BYTES + 1)
        if len(encoded) > MAX_BYTES or hashlib.sha256(encoded).hexdigest() != digest:
            raise ValueError("cache integrity mismatch")
        payload = json.loads(encoded)
        if payload["identity"] != identity or any(field not in payload["song"] for field in FIELDS):
            raise ValueError("cache identity mismatch")
        song = _restore(payload["song"], root, sample)
        song["_cache"] = {"hit": True, "path": blob.relative_to(root).as_posix(), "sha256": digest}
        return song
    except (OSError, EOFError, ValueError, KeyError, TypeError, zlib.error):
        pass  # An incomplete/corrupt cache never becomes training truth.
    song = uncached(root, sample, max_lines=max_lines)
    payload = {"identity": identity, "song": {field: song[field] for field in FIELDS}}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    song["_cache"] = {"hit": False, "path": None, "sha256": None}
    if len(encoded) <= MAX_BYTES:
        digest = hashlib.sha256(encoded).hexdigest()
        blob = folder / (key + "-" + digest + ".json.gz")
        _atomic(blob, gzip.compress(encoded, compresslevel=1, mtime=0))
        _atomic(metadata_path, json.dumps({"sha256": digest, "bytes": len(encoded)}, separators=(",", ":")).encode())
        song["_cache"].update(path=blob.relative_to(root).as_posix(), sha256=digest)
    return song

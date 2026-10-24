from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2).encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=".pamos-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class Settings:
    root: Path

    @property
    def data_dir(self):
        return self.root / "data"

    @property
    def db_path(self):
        return self.data_dir / "workbench.sqlite3"

    def ensure(self):
        for name in ("assets", "charts", "candidates", "features", "datasets", "exports", "proposals", "jobs"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
        for name in ("runs", "models/registry", ".local/tmp"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        return self

    def path(self, relative):
        candidate = (self.root / relative).resolve()
        allowed = (self.data_dir.resolve(), (self.root / "runs").resolve(), (self.root / "models/registry").resolve())
        if not any(candidate.is_relative_to(p) for p in allowed):
            raise ValueError("路径必须位于本机受管理数据目录")
        return candidate

    def relative(self, path):
        candidate = Path(path).resolve()
        self.path(candidate)
        return candidate.relative_to(self.root.resolve()).as_posix()


@lru_cache(maxsize=1)
def get_settings():
    return Settings(Path(os.environ.get("PAMOS_ROOT", Path(__file__).resolve().parents[2])).resolve()).ensure()

"""SQLite state with immutable records and transactional compare-and-set."""
from __future__ import annotations
from contextlib import contextmanager
import json
import sqlite3
from .settings import get_settings, now, new_id


class Store:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    immutable INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, action TEXT NOT NULL,
                    record_id TEXT, payload TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.settings.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    def put(self, kind, record, immutable=False):
        return self.put_many([(kind, record, immutable)])[0]

    def put_many(self, entries):
        """Register one imported package atomically across its related records."""
        prepared = []
        for kind, record, immutable in entries:
            record = dict(record)
            record.setdefault("id", new_id())
            record.setdefault("created_at", now())
            record["updated_at"] = now()
            prepared.append((kind, record, immutable))
        with self.connection() as db:
            for kind, record, immutable in prepared:
                db.execute("INSERT INTO records VALUES (?,?,?,?,?,?)", (kind, record["id"], self.encode(record), int(immutable), record["created_at"], record["updated_at"]))
        return [record for _, record, _ in prepared]

    def get(self, kind, record_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        if row is None:
            raise KeyError(f"找不到 {kind}: {record_id}")
        return json.loads(row[0])

    def revise_import(self, chart_id, expected, changes, candidate=None):
        """CAS an imported record and its optional new immutable-content version."""
        timestamp = now()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload,immutable FROM records WHERE kind='charts' AND id=?", (chart_id,)).fetchone()
            if row is None or row["immutable"]:
                raise ValueError("导入记录不存在或不可修改")
            value = json.loads(row["payload"])
            if any(value.get(key) != item for key, item in expected.items()):
                raise ValueError("素材标签或版本已变化，拒绝覆盖，请刷新后重试")
            if set(changes) & {"id", "created_at", "original_path", "original_sha256", "source_archive_sha256"}:
                raise ValueError("补处理不能更改原件身份")
            if candidate:
                candidate = {**candidate, "created_at": timestamp, "updated_at": timestamp}
                db.execute("INSERT INTO records VALUES (?,?,?,?,?,?)", ("candidates", candidate["id"], self.encode(candidate), 0, timestamp, timestamp))
            value.update(changes)
            value["updated_at"] = timestamp
            db.execute("UPDATE records SET payload=?,updated_at=? WHERE kind='charts' AND id=?", (self.encode(value), timestamp, chart_id))
            db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (new_id(), timestamp, "library.reprocessed", chart_id,
                self.encode({"candidate_id": candidate["id"] if candidate else None, "import_status": value["import_status"], "run_id": changes.get("reprocess_run_id")})))
        return value

    def list(self, kind):
        with self.connection() as db:
            rows = db.execute("SELECT payload FROM records WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def update(self, kind, record_id, changes, expected=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
            if row is None:
                raise KeyError(f"找不到 {kind}: {record_id}")
            if row["immutable"]:
                raise ValueError("不可变记录只能新建版本")
            value = json.loads(row["payload"])
            if expected and any(value.get(k) != v for k, v in expected.items()):
                raise ValueError("记录版本冲突，请刷新后重试")
            if "id" in changes or "created_at" in changes:
                raise ValueError("不能修改记录身份")
            if kind == "candidates" and set(changes) - {"status", "audit_id", "review_id"}:
                raise ValueError("候选内容不可变；请创建修订")
            value.update(changes)
            value["updated_at"] = now()
            db.execute("UPDATE records SET payload=?,updated_at=? WHERE kind=? AND id=?", (self.encode(value), value["updated_at"], kind, record_id))
        return value

    def event(self, action, record_id=None, **payload):
        # Callers pass metadata only; never keys, music bytes or authorization headers.
        with self.connection() as db:
            db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (new_id(), now(), action, record_id, self.encode(payload)))

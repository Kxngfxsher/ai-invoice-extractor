"""Хранилище на SQLite: документы, извлечённые данные и результаты проверок."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    status TEXT NOT NULL,              -- new | approved | rejected
    verdict TEXT NOT NULL,             -- ready | check | attention
    number TEXT,
    doc_date TEXT,
    seller_name TEXT,
    seller_inn TEXT,
    total REAL,
    data_json TEXT NOT NULL,           -- текущие данные (после правок оператора)
    original_json TEXT NOT NULL,       -- то, что извлёк движок
    issues_json TEXT NOT NULL,
    meta_json TEXT NOT NULL,
    edited INTEGER NOT NULL DEFAULT 0,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _summary_columns(data: dict) -> dict:
    """Поля, вынесенные в колонки для списка и поиска дублей."""
    return {
        "number": data["number"],
        "doc_date": data["date"],
        "seller_name": data["seller"]["name"],
        "seller_inn": data["seller"]["inn"],
        "total": data["total"],
    }


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def insert(self, *, filename, stored_name, kind, sha256, data: dict, issues: list[dict], verdict: str, meta: dict) -> int:
        row = {
            "filename": filename,
            "stored_name": stored_name,
            "kind": kind,
            "sha256": sha256,
            "uploaded_at": iso(utcnow()),
            "status": "new",
            "verdict": verdict,
            **_summary_columns(data),
            "data_json": json.dumps(data, ensure_ascii=False),
            "original_json": json.dumps(data, ensure_ascii=False),
            "issues_json": json.dumps(issues, ensure_ascii=False),
            "meta_json": json.dumps(meta, ensure_ascii=False),
        }
        names = ", ".join(row)
        marks = ", ".join(f":{name}" for name in row)
        with self._conn() as conn:
            return conn.execute(f"INSERT INTO documents ({names}) VALUES ({marks})", row).lastrowid

    def update_data(self, doc_id: int, data: dict, issues: list[dict], verdict: str, edited: bool) -> None:
        row = {
            **_summary_columns(data),
            "data_json": json.dumps(data, ensure_ascii=False),
            "issues_json": json.dumps(issues, ensure_ascii=False),
            "verdict": verdict,
            "edited": int(edited),
            "id": doc_id,
        }
        assignments = ", ".join(f"{name} = :{name}" for name in row if name != "id")
        with self._conn() as conn:
            conn.execute(f"UPDATE documents SET {assignments} WHERE id = :id", row)

    def set_status(self, doc_id: int, status: str) -> None:
        decided_at = None if status == "new" else iso(utcnow())
        with self._conn() as conn:
            conn.execute("UPDATE documents SET status = ?, decided_at = ? WHERE id = ?", (status, decided_at, doc_id))

    def get(self, doc_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return self._to_dict(row) if row else None

    def all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
        return [self._to_dict(row) for row in rows]

    def find_duplicates(self, seller_inn: str | None, number: str | None, doc_date: str | None, exclude_id: int | None) -> list[dict]:
        """Документы с тем же поставщиком, номером и датой (кроме отклонённых)."""
        if not (seller_inn and number and doc_date):
            return []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, filename FROM documents WHERE seller_inn = ? AND number = ? AND doc_date = ? "
                "AND status != 'rejected' AND id != ?",
                (seller_inn, number, doc_date, exclude_id or 0),
            ).fetchall()
        return [dict(row) for row in rows]

    def hashes(self) -> set[str]:
        with self._conn() as conn:
            return {row[0] for row in conn.execute("SELECT sha256 FROM documents")}

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    def clear(self) -> None:
        with self._conn() as conn:
            # Счётчик номеров тоже сбрасывается: после сброса демо документы снова нумеруются с 1.
            conn.executescript("DELETE FROM documents; DELETE FROM meta; DELETE FROM sqlite_sequence;")

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["data"] = json.loads(data.pop("data_json"))
        data["original"] = json.loads(data.pop("original_json"))
        data["issues"] = json.loads(data.pop("issues_json"))
        data["meta"] = json.loads(data.pop("meta_json"))
        data["edited"] = bool(data["edited"])
        return data

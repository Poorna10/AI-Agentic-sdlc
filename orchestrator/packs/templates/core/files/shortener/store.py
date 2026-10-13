"""SQLite persistence. All SQL is parameterised; one connection guarded by a lock."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass

from .errors import AliasTaken

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    code TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL REFERENCES links(code),
    ts REAL NOT NULL,
    referrer TEXT
);
CREATE INDEX IF NOT EXISTS idx_clicks_code_ts ON clicks(code, ts);
"""

_INSERT_LINK = "INSERT INTO links (code, url, created_at) VALUES (?, ?, ?)"
_SELECT_LINK = "SELECT code, url, created_at FROM links WHERE code = ?"


@dataclass(frozen=True)
class Link:
    code: str
    url: str
    created_at: float
    # [ext:link-fields]


def _link_params(link: Link) -> tuple:
    return (link.code, link.url, link.created_at)


def _to_link(row: sqlite3.Row) -> Link:
    return Link(code=row["code"], url=row["url"], created_at=row["created_at"])


class LinkStore:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Additive, idempotent schema migrations."""
        # [ext:migrations]

    def insert_link(self, link: Link) -> None:
        try:
            with self._lock:
                self._conn.execute(_INSERT_LINK, _link_params(link))
        except sqlite3.IntegrityError as exc:
            raise AliasTaken(link.code) from exc

    def get_link(self, code: str) -> Link | None:
        with self._lock:
            row = self._conn.execute(_SELECT_LINK, (code,)).fetchone()
        return _to_link(row) if row else None

    def record_click(self, code: str, ts: float, referrer: str | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO clicks (code, ts, referrer) VALUES (?, ?, ?)",
                (code, ts, (referrer or None) and referrer[:512]),
            )

    def count_clicks(self, code: str, since: float | None = None) -> int:
        with self._lock:
            if since is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM clicks WHERE code = ?", (code,)).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM clicks WHERE code = ? AND ts >= ?", (code, since)).fetchone()
        return int(row[0])

    def top_referrers(self, code: str, limit: int = 5) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT referrer, COUNT(*) AS n FROM clicks WHERE code = ? AND referrer IS NOT NULL "
                "GROUP BY referrer ORDER BY n DESC, referrer ASC LIMIT ?",
                (code, limit),
            ).fetchall()
        return [{"referrer": r["referrer"], "clicks": r["n"]} for r in rows]

    # [ext:store-methods]

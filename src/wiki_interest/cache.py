"""Local SQLite cache: daily pageviews, their confirmed coverage, raw API JSON responses.

One file, standard-library sqlite3 only. Days are stored as ISO strings (YYYY-MM-DD).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Callable, Iterable

from .errors import CacheError

SCHEMA_VERSION = 1

# coverage.status:
#   ok          - the API returned this range; days without a record are 0
#   empty_404   - the API answered 404 for a title confirmed by resolve: all days are 0
#   unavailable - the API has no data of this class for the range (e.g. `automated`
#                 before May 2020); values are unknown, never zero
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS pageviews (
    project TEXT NOT NULL,
    article TEXT NOT NULL,
    access  TEXT NOT NULL,
    agent   TEXT NOT NULL,
    day     TEXT NOT NULL,
    views   INTEGER NOT NULL,
    PRIMARY KEY (project, article, access, agent, day)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS coverage (
    project    TEXT NOT NULL,
    article    TEXT NOT NULL,
    access     TEXT NOT NULL,
    agent      TEXT NOT NULL,
    "start"    TEXT NOT NULL,
    "end"      TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'ok',
    PRIMARY KEY (project, article, access, agent, "start", "end")
);
CREATE TABLE IF NOT EXISTS http_cache (
    url        TEXT PRIMARY KEY,
    body       TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""

COVERAGE_STATUSES = ("ok", "empty_404", "unavailable")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


class Cache:
    def __init__(self, path: Path, *, now: Callable[[], dt.datetime] = _utcnow) -> None:
        self.path = Path(path)
        self._now = now
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.path))
            self.conn.executescript(SCHEMA)
            # Explicit write: proves the file is writable even when the schema already exists.
            with self.conn:
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
        except (OSError, sqlite3.Error) as exc:
            raise CacheError(
                f"Cannot open or write the cache at {self.path}: {exc}",
                hint="Pass --cache-dir or set WIKI_INTEREST_CACHE to a writable folder",
            ) from exc

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- raw JSON responses of MediaWiki / Wikidata ------------------------------------

    def http_get(self, url: str, ttl_days: float) -> str | None:
        row = self.conn.execute("SELECT body, fetched_at FROM http_cache WHERE url = ?", (url,)).fetchone()
        if row is None:
            return None
        if self._now() - _parse_iso(row[1]) > dt.timedelta(days=ttl_days):
            return None
        return row[0]

    def http_put(self, url: str, body: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO http_cache(url, body, fetched_at) VALUES (?, ?, ?)",
                (url, body, _iso(self._now())),
            )

    # -- pageviews ---------------------------------------------------------------------

    def put_pageviews(
        self,
        project: str,
        article: str,
        access: str,
        agent: str,
        rows: Iterable[tuple[str, int]],
        *,
        start: str,
        end: str,
        status: str = "ok",
    ) -> None:
        """Store daily views and record [start, end] as covered, atomically."""
        if status not in COVERAGE_STATUSES:
            raise ValueError(f"unknown coverage status {status!r}")
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO pageviews(project, article, access, agent, day, views)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [(project, article, access, agent, day, int(v)) for day, v in rows],
            )
            self.conn.execute(
                'INSERT OR REPLACE INTO coverage(project, article, access, agent, "start", "end", fetched_at, status)'
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project, article, access, agent, start, end, _iso(self._now()), status),
            )

    def get_pageviews(
        self, project: str, article: str, access: str, agent: str, start: str, end: str
    ) -> list[tuple[str, int]]:
        cur = self.conn.execute(
            "SELECT day, views FROM pageviews WHERE project = ? AND article = ? AND access = ? AND agent = ?"
            " AND day BETWEEN ? AND ? ORDER BY day",
            (project, article, access, agent, start, end),
        )
        return [(d, v) for d, v in cur]

    def coverage(self, project: str, article: str, access: str, agent: str) -> list[dict[str, str]]:
        cur = self.conn.execute(
            'SELECT "start", "end", status, fetched_at FROM coverage'
            ' WHERE project = ? AND article = ? AND access = ? AND agent = ? ORDER BY "start", "end"',
            (project, article, access, agent),
        )
        return [{"start": s, "end": e, "status": st, "fetched_at": f} for s, e, st, f in cur]

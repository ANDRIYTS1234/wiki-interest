from __future__ import annotations

import datetime as dt

import pytest

from wiki_interest.cache import Cache
from wiki_interest.errors import CacheError


class Now:
    def __init__(self) -> None:
        self.t = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)

    def __call__(self) -> dt.datetime:
        return self.t


def test_http_cache_ttl(tmp_path):
    now = Now()
    with Cache(tmp_path / "c.sqlite", now=now) as c:
        c.http_put("u", '{"a": 1}')
        now.t += dt.timedelta(days=6)
        assert c.http_get("u", ttl_days=7) == '{"a": 1}'
        now.t += dt.timedelta(days=2)
        assert c.http_get("u", ttl_days=7) is None
        assert c.http_get("missing", ttl_days=7) is None


def test_pageviews_roundtrip_with_coverage(tmp_path):
    with Cache(tmp_path / "c.sqlite") as c:
        c.put_pageviews(
            "uk.wikipedia", "Сузір'я", "all-access", "user",
            [("2026-01-01", 10), ("2026-01-03", 5)],
            start="2026-01-01", end="2026-01-31",
        )
        assert c.get_pageviews("uk.wikipedia", "Сузір'я", "all-access", "user", "2026-01-01", "2026-01-02") == [
            ("2026-01-01", 10)
        ]
        cov = c.coverage("uk.wikipedia", "Сузір'я", "all-access", "user")
        assert [(x["start"], x["end"], x["status"]) for x in cov] == [("2026-01-01", "2026-01-31", "ok")]


def test_cache_persists_across_connections(tmp_path):
    path = tmp_path / "sub" / "dir" / "c.sqlite"
    with Cache(path) as c:
        c.http_put("u", "{}")
    with Cache(path) as c:
        assert c.http_get("u", ttl_days=1) == "{}"


def test_unknown_coverage_status_rejected(tmp_path):
    with Cache(tmp_path / "c.sqlite") as c, pytest.raises(ValueError):
        c.put_pageviews("p", "a", "all-access", "user", [], start="2026-01-01", end="2026-01-31", status="zero")


def test_unwritable_location_is_explained(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    with pytest.raises(CacheError) as ei:
        Cache(blocker / "cache.sqlite")
    assert "WIKI_INTEREST_CACHE" in ei.value.hint

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from wiki_interest.config import latest_full_month, load_settings, resolve_contact, user_agent
from wiki_interest.errors import InputError

PROJECT_URL = "https://github.com/ANDRIYTS1234/wiki-interest"


@pytest.mark.parametrize(
    "now, expected",
    [
        (dt.datetime(2026, 9, 27, tzinfo=dt.timezone.utc), "2026-08"),
        (dt.datetime(2026, 9, 3, 23, 59, tzinfo=dt.timezone.utc), "2026-07"),
        (dt.datetime(2026, 9, 4, 0, 0, tzinfo=dt.timezone.utc), "2026-08"),
        (dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc), "2025-11"),
        (dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc), "2025-12"),
    ],
)
def test_latest_full_month_with_three_day_lag(now, expected):
    assert latest_full_month(now) == expected


def test_contact_from_env():
    c = resolve_contact({"WIKI_INTEREST_CONTACT": "me@example.org"})
    assert (c.value, c.source) == ("me@example.org", "env")
    assert user_agent(c).startswith(f"wiki-interest/")
    assert "(me@example.org)" in user_agent(c)


def test_contact_falls_back_to_project_url():
    c = resolve_contact({})
    assert (c.value, c.source) == (PROJECT_URL, "project_url")
    assert f"({PROJECT_URL})" in user_agent(c)


def test_cache_dir_precedence(tmp_path):
    env = {"WIKI_INTEREST_CACHE": str(tmp_path / "env")}
    assert load_settings(cache_dir=tmp_path / "opt", environ=env).cache_dir == tmp_path / "opt"
    assert load_settings(environ=env).cache_dir == tmp_path / "env"
    s = load_settings(environ={})
    assert s.cache_path == Path(".wiki-interest-cache") / "cache.sqlite"
    assert s.workdir == Path("wiki-interest-out")


def test_min_interval_env():
    assert load_settings(environ={"WIKI_INTEREST_MIN_INTERVAL": "1.5"}).min_interval == 1.5
    with pytest.raises(InputError):
        load_settings(environ={"WIKI_INTEREST_MIN_INTERVAL": "fast"})

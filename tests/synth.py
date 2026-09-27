"""Synthetic cache content with known answers for analyze tests.

These are our own series written straight into the cache (resolved entries, coverage, daily
views), not imitations of API responses, so they do not replace recorded fixtures.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable

from wiki_interest.cache import Cache
from wiki_interest.config import AUTOMATED_START
from wiki_interest.fetch import AGGREGATE

START = dt.date(2019, 1, 1)
END = dt.date(2024, 12, 31)
SECTION_DAILY = 1_000_000


def days(start: dt.date = START, end: dt.date = END):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def put_series(cache: Cache, project: str, article: str, access: str, agent: str, fn: Callable[[dt.date], float], start: dt.date = START) -> None:
    rows = [(d.isoformat(), int(round(fn(d)))) for d in days(start) if fn(d) > 0]
    cache.put_pageviews(project, article, access, agent, rows, start=start.isoformat(), end=END.isoformat())


def put_article(
    cache: Cache,
    lang: str,
    qid: str,
    title: str,
    user: Callable[[dt.date], float],
    *,
    created: str = "2010-01-01T00:00:00Z",
    redirects: dict[str, Callable[[dt.date], float]] | None = None,
    automated_share: float = 0.01,
    desktop_share: float = 0.4,
) -> None:
    project = f"{lang}.wikipedia"
    redirects = redirects or {}
    entry = {
        "status": "ok", "title": title, "requested_title": None, "qid": qid, "pageid": 1, "created": created,
        "length": 1000, "redirects": sorted(redirects), "former_titles": [], "search_hits": [], "candidates": [],
        "warnings": [], "lang": lang, "item_qid": qid,
    }
    cache.put_resolved({f"qid:{qid}:{lang}": entry, f"title:{lang}:{title}": entry})
    put_series(cache, project, title, "all-access", "user", user)
    put_series(cache, project, title, "all-access", "automated", lambda d: user(d) * automated_share, start=AUTOMATED_START)
    cache.put_pageviews(project, title, "all-access", "automated", [], start=START.isoformat(), end=(AUTOMATED_START - dt.timedelta(days=1)).isoformat(), status="unavailable")
    put_series(cache, project, title, "desktop", "user", lambda d: user(d) * desktop_share)
    for r, fn in redirects.items():
        put_series(cache, project, r, "all-access", "user", fn)


def put_missing(cache: Cache, lang: str, qid: str) -> None:
    cache.put_resolved({f"qid:{qid}:{lang}": {"status": "missing", "title": None, "qid": None, "lang": lang, "redirects": [], "former_titles": []}})


def put_section(cache: Cache, lang: str) -> None:
    project = f"{lang}.wikipedia"
    put_series(cache, project, AGGREGATE, "all-access", "user", lambda d: SECTION_DAILY)
    put_series(cache, project, AGGREGATE, "all-access", "automated", lambda d: SECTION_DAILY * 0.01, start=AUTOMATED_START)
    cache.put_pageviews(project, AGGREGATE, "all-access", "automated", [], start=START.isoformat(), end=(AUTOMATED_START - dt.timedelta(days=1)).isoformat(), status="unavailable")


def yearly(level: float, factors: dict[int, float]) -> Callable[[dt.date], float]:
    """level x factor of the year (years not listed: factor 1)."""
    return lambda d: level * factors.get(d.year, 1.0)


# Target basket (uk): six articles whose 2024 views are half of 2023; groups g1 / g2.
TARGET = {f"Q10{i}": (f"Стаття {i}", 1000.0 * i) for i in range(1, 7)}
CONTROL = {f"Q20{i}": (f"Контроль {i}", 800.0) for i in range(1, 6)}


def build(cache_dir: Path) -> Path:
    path = cache_dir / "cache.sqlite"
    with Cache(path) as cache:
        for lang in ("uk", "pl"):
            put_section(cache, lang)
        for qid, (title, level) in TARGET.items():
            put_article(cache, "uk", qid, title, yearly(level, {2024: 0.5}),
                        redirects={f"{title} (редирект)": yearly(level * 0.1, {2024: 0.5})} if qid == "Q101" else None)
            put_article(cache, "pl", qid, f"Artykuł {qid[-1]}", yearly(level, {2024: 0.8}))
        # created during the base period -> excluded from the window panel as created_after
        put_article(cache, "uk", "Q107", "Нова стаття", yearly(5000.0, {2024: 3.0}), created="2023-06-01T00:00:00Z")
        put_article(cache, "pl", "Q107", "Nowy artykuł", yearly(5000.0, {2024: 3.0}), created="2023-06-01T00:00:00Z")
        # below min_monthly_views -> excluded as low_volume
        put_article(cache, "uk", "Q108", "Мала стаття", lambda d: 0.5)
        put_article(cache, "pl", "Q108", "Mały artykuł", lambda d: 0.5)
        put_missing(cache, "pl", "Q109")
        put_article(cache, "uk", "Q109", "Лише українською", yearly(900.0, {2024: 0.5}))
        for qid, (title, level) in CONTROL.items():
            put_article(cache, "uk", qid, title, yearly(level, {}))
            put_article(cache, "pl", qid, f"Kontrola {qid[-1]}", yearly(level, {}))
    return path


def spec(**over) -> dict:
    target_items = [{"qid": q, "group": "g1" if int(q[-1]) <= 3 else "g2"} for q in TARGET]
    target_items += [{"qid": "Q107"}, {"qid": "Q108"}, {"qid": "Q109"}, {"qid": "Q110", "exclude": "не про тему"}]
    base = {
        "question": "synthetic",
        "langs": ["uk", "pl"],
        "window": {"months": 12, "end": "2024-12"},
        "history_start": "2019-01",
        "baselines": [2021],
        "baskets": [
            {"id": "target", "role": "target", "label": "Ціль", "items": target_items},
            {"id": "control", "role": "control", "label": "Контроль", "items": [{"qid": q} for q in CONTROL]},
        ],
    }
    base.update(over)
    return base

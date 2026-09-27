"""Load the pageview series of an analysis from the cache into pandas. No network.

Daily series are NaN wherever the cache has no confirmed coverage; zeros only inside coverage
with status ok/empty_404. Monthly sums are NaN if any day of the month is NaN.

Per article:
- user: main title user/all-access plus redirects and former titles (user only, see fetch.py);
  a redirect/former-title gap is recorded as a problem (REDIRECTS_SKIPPED or PARTIAL_DATA) and
  counted as zero, a gap of the main title stays NaN and removes the article from that period;
- main_user, automated, desktop: main title only (bot and device diagnostics).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..cache import Cache
from ..dates import day, first_day, iso, last_day
from ..errors import InputError
from ..fetch import AGGREGATE, RESULT_FILE, Series, build_plan, project_of, start_month
from ..schemas import AnalysisSpec

CONFIRMED = ("ok", "empty_404")


@dataclass
class Candidate:
    """One basket item in one language."""

    basket: str
    item: str
    lang: str
    group: str | None
    qid: str | None
    proxy_for: str | None
    status: str  # ok | missing | excluded
    reason: str | None = None
    article: str | None = None  # "lang:title"


@dataclass
class ArticleData:
    key: str
    lang: str
    title: str
    qid: str | None
    created: dt.date | None
    user: pd.Series
    main_user: pd.Series
    automated: pd.Series
    desktop: pd.Series
    monthly_user: pd.Series = field(default=None)  # type: ignore[assignment]


@dataclass
class Dataset:
    start: dt.date
    end: dt.date
    data_as_of: str
    articles: dict[str, ArticleData]
    section_user: dict[str, pd.Series]
    section_automated: dict[str, pd.Series]
    section_monthly: dict[str, pd.Series]
    candidates: list[Candidate]
    problems: list[dict[str, Any]]
    unused_series: list[dict[str, str]]


def monthly(s: pd.Series) -> pd.Series:
    per = s.index.to_period("M")
    sums = s.groupby(per).sum(min_count=1)
    sums[s.isna().groupby(per).any()] = np.nan
    return sums


def period_sum(monthly_series: pd.Series, months: list[pd.Period]) -> float:
    """Sum over the given months; NaN if any month is missing or incomplete."""
    vals = monthly_series.reindex(pd.PeriodIndex(months, freq="M"))
    return float("nan") if vals.isna().any() else float(vals.sum())


def load_daily(cache: Cache, key: tuple[str, str, str, str], start: dt.date, end: dt.date) -> pd.Series:
    idx = pd.date_range(start, end, freq="D")
    values = np.full(len(idx), np.nan)
    for c in cache.coverage(*key):
        if c["status"] not in CONFIRMED:
            continue
        a, b = max(start, day(c["start"])), min(end, day(c["end"]))
        if a <= b:
            values[(a - start).days : (b - start).days + 1] = 0.0
    for d, v in cache.get_pageviews(*key, iso(start), iso(end)):
        i = (day(d) - start).days
        if not np.isnan(values[i]):
            values[i] = v
    return pd.Series(values, index=idx)


def coverage_end_month(cache: Cache, lang: str) -> str | None:
    """Last month fully covered by the project's user aggregate."""
    ends = [day(c["end"]) for c in cache.coverage(project_of(lang), AGGREGATE, "all-access", "user") if c["status"] == "ok"]
    if not ends:
        return None
    last = max(ends)
    if (last + dt.timedelta(days=1)).day != 1:
        last = last.replace(day=1) - dt.timedelta(days=1)
    return f"{last:%Y-%m}"


def analysis_end_month(spec: AnalysisSpec, cache: Cache) -> str:
    """data_as_of from cache coverage (not the clock), so an offline snapshot stays reproducible."""
    if spec.window_end != "latest":
        return spec.window_end
    months = [coverage_end_month(cache, l) for l in spec.langs]
    if any(m is None for m in months):
        missing = [l for l, m in zip(spec.langs, months) if m is None]
        raise InputError(f"no pageviews in the cache for {missing}", hint="Run `fetch --spec` with the same analysis.json first")
    return min(months)  # type: ignore[type-var]


def _gap_problem(cache: Cache, s: Series, gap: tuple[dt.date, dt.date]) -> dict[str, Any]:
    skipped = [(day(c["start"]), day(c["end"])) for c in cache.coverage(*s.key) if c["status"] == "skipped"]
    inside = any(a <= gap[0] and gap[1] <= b for a, b in skipped)
    return {
        "code": "REDIRECTS_SKIPPED" if inside else "PARTIAL_DATA",
        "lang": s.project.split(".")[0],
        "article": s.owner,
        "series": {"article": s.article, "access": s.access, "agent": s.agent, "role": s.role},
        "start": iso(gap[0]),
        "end": iso(gap[1]),
    }


def load_dataset(spec: AnalysisSpec, cache: Cache, workdir: Path | None = None) -> Dataset:
    end_month = analysis_end_month(spec, cache)
    plan = build_plan(spec, cache, None, end_month=end_month)
    if plan.unresolved:
        where = sorted({u["where"] for u in plan.unresolved})
        raise InputError(
            f"{len(plan.unresolved)} basket items are not resolved in the cache: {where[:5]}",
            hint="Run `fetch --spec` with the same analysis.json first (it resolves and downloads)",
        )
    start, end = first_day(start_month(spec, end_month)), last_day(end_month)
    problems: list[dict[str, Any]] = []
    by_owner: dict[str, list[Series]] = {}
    section_user: dict[str, pd.Series] = {}
    section_auto: dict[str, pd.Series] = {}
    for s in plan.series:
        for gap in s.gaps:
            if s.agent == "automated" and s.role == "main":
                continue  # bot diagnostics only; missing automated days just leave shares unknown
            problems.append(_gap_problem(cache, s, gap))
        if s.article == AGGREGATE:
            target = section_user if s.agent == "user" else section_auto
            target[s.owner] = load_daily(cache, s.key, start, end)
        else:
            by_owner.setdefault(s.owner, []).append(s)

    articles: dict[str, ArticleData] = {}
    for art in plan.articles:
        key = f"{art.lang}:{art.title}"
        series = by_owner.get(key, [])
        main = {(s.access, s.agent): s for s in series if s.role == "main"}
        main_user = load_daily(cache, main[("all-access", "user")].key, start, end)
        user = main_user.copy()
        for s in series:
            if s.role in ("redirect", "former_title"):
                extra = load_daily(cache, s.key, start, end)
                in_range = (extra.index.date >= s.start) & (extra.index.date <= s.end)
                user = user + extra.where(in_range, 0.0).fillna(0.0)
        created = art.entry.get("created")
        articles[key] = ArticleData(
            key=key,
            lang=art.lang,
            title=art.title,
            qid=art.entry.get("qid"),
            created=day(created) if created else None,
            user=user,
            main_user=main_user,
            automated=load_daily(cache, main[("all-access", "automated")].key, start, end),
            desktop=load_daily(cache, main[("desktop", "user")].key, start, end),
        )
        articles[key].monthly_user = monthly(user)

    candidates: list[Candidate] = []
    for basket in spec.baskets:
        for item in basket.items:
            langs = spec.langs if item.qid else (item.lang,)
            for lang in langs:
                c = Candidate(basket.id, item.id, lang, item.group, item.qid, item.proxy_for, "ok")
                if item.exclude:
                    c.status, c.reason = "excluded", f"manual: {item.exclude}"
                else:
                    key = f"qid:{item.qid}:{lang}" if item.qid else f"title:{lang}:{item.title}"
                    entry = cache.get_resolved(key) or {}
                    if entry.get("status") == "missing":
                        c.status, c.reason = "missing", f"no article in {lang}.wikipedia"
                    else:
                        c.article = f"{lang}:{entry['title']}"
                        c.qid = c.qid or entry.get("qid")
                candidates.append(c)

    unused: list[dict[str, str]] = []
    result_file = (workdir / RESULT_FILE) if workdir else None
    if result_file and result_file.is_file():
        planned = {s.key for s in plan.series}
        try:
            fetched = json.loads(result_file.read_text(encoding="utf-8")).get("series", [])
        except (OSError, ValueError):
            fetched = []
        for f in fetched:
            key = (f.get("project"), f.get("article"), f.get("access"), f.get("agent"))
            if key not in planned:
                unused.append({"project": key[0], "article": key[1], "access": key[2], "agent": key[3]})

    return Dataset(
        start=start,
        end=end,
        data_as_of=end_month,
        articles=articles,
        section_user=section_user,
        section_automated=section_auto,
        section_monthly={lang: monthly(s) for lang, s in section_user.items()},
        candidates=candidates,
        problems=problems,
        unused_series=unused,
    )

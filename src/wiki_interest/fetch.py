"""`fetch`: daily pageviews for every page of the baskets into the SQLite cache (SPEC §7).

Per article (resolved via the `resolved` cache table):
- main title: user/all-access, automated/all-access, user/desktop (mobile = all - desktop);
- redirects and former titles: user/all-access only. They carry ~1-2% of traffic, and three
  series each would triple the requests for large baskets; bot and device diagnostics of
  spikes therefore use the main title only;
- a former title that is no longer a redirect to the article counts only up to its moved_at day
  (the title may now be a different page, e.g. uk «Марс» became a disambiguation page).
Per language: aggregate user and automated views of the whole project.

Only ranges missing from `coverage` are requested. Days without a record are zero only inside
confirmed coverage. A 404 for a title confirmed by resolve is stored as confirmed zeros
(status empty_404). `automated` before AUTOMATED_START is stored as "unavailable", never zeros.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__
from .cache import Cache
from .config import AUTOMATED_START, EST_SECONDS_PER_REQUEST, PAGEVIEWS_START, latest_full_month
from .dates import add_months, day, first_day, gaps, iso, last_day
from .errors import IncompleteDataError, InputError, RateLimitError, WikiInterestError
from .http import HttpClient, parse_json
from .resolve import Resolver, lookup_article
from .schemas import AnalysisSpec, load_json_file, parse_analysis_spec

log = logging.getLogger(__name__)

PV_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
AGGREGATE = "#aggregate"  # article key for project totals; "#" cannot occur in a page title
RESULT_FILE = "fetch_result.json"
MAX_LISTED = 20  # stdout lists at most this many missing series; the file has all


def project_of(lang: str) -> str:
    return f"{lang}.wikipedia"


def data_as_of(spec: AnalysisSpec) -> str:
    latest = latest_full_month()
    if spec.window_end == "latest":
        return latest
    if spec.window_end > latest:
        raise InputError(
            f"window.end {spec.window_end} is after the last complete month {latest}",
            hint='Use "latest" or an earlier month',
        )
    return spec.window_end


def start_month(spec: AnalysisSpec, end_month: str) -> str:
    """Earliest month needed: history_start, the same months a year before the window, baseline years."""
    prior_window_start = add_months(end_month, -(12 + spec.window_months - 1))
    candidates = [spec.history_start, prior_window_start]
    candidates += [f"{y:04d}-01" for y in spec.baselines]
    return max(min(candidates), f"{PAGEVIEWS_START:%Y-%m}")


@dataclass
class Series:
    project: str
    article: str
    access: str
    agent: str
    start: dt.date
    end: dt.date
    role: str  # main | redirect | former_title | aggregate
    owner: str  # "uk:Нейтронна зоря" or "uk" for aggregates
    gaps: list[tuple[dt.date, dt.date]] = field(default_factory=list)
    unavailable: tuple[dt.date, dt.date] | None = None  # recorded without a request
    unavailable_recorded: bool = True

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.project, self.article, self.access, self.agent)

    def describe(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "article": self.article,
            "access": self.access,
            "agent": self.agent,
            "role": self.role,
            "owner": self.owner,
            "start": iso(self.start),
            "end": iso(self.end),
        }


@dataclass
class Article:
    lang: str
    title: str
    entry: dict[str, Any]
    members: list[str] = field(default_factory=list)  # "basket_id/item_id"


@dataclass
class Plan:
    start: dt.date
    end: dt.date
    data_as_of: str
    articles: list[Article]
    series: list[Series]
    missing_articles: list[dict[str, Any]]
    unresolved: list[dict[str, Any]]

    @property
    def requests_needed(self) -> int:
        return sum(len(s.gaps) for s in self.series)


# -- planning --------------------------------------------------------------------------


def collect_articles(
    spec: AnalysisSpec, cache: Cache, resolver: Resolver | None
) -> tuple[list[Article], list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve basket items to articles. With resolver=None only the cache is read (no network)."""
    articles: dict[tuple[str, str], Article] = {}
    missing: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    def get(lang: str, qid: str | None, title: str | None, where: str) -> dict[str, Any] | None:
        key = f"qid:{qid}:{lang}" if qid else f"title:{lang}:{title}"
        if resolver is None:
            entry = cache.get_resolved(key)
            if entry is None:
                unresolved.append({"where": where, "lang": lang, "qid": qid, "title": title})
                return None
            if entry["status"] == "disambiguation":
                raise InputError(f"{where}: {lang}:{entry['title']} is a disambiguation page", hint="Choose a candidate with resolve", code="disambiguation")
            return entry
        if cache.get_resolved(key) is None:
            log.info("resolve %s %s", lang, qid or title)
        try:
            return lookup_article(resolver, cache, lang, qid=qid, title=title)
        except InputError as exc:
            if exc.code == "article_missing" and qid:
                return {"status": "missing"}
            exc.message = f"{where}: {exc.message}"
            raise

    for basket in spec.baskets:
        for item in basket.items:
            where = f"{basket.id}/{item.id}"
            langs = spec.langs if item.qid else (item.lang,)
            for lang in langs:
                entry = get(lang, item.qid, item.title, where)
                if entry is None:
                    continue
                if entry["status"] == "missing":
                    if item.title:
                        raise InputError(f"{where}: no article {lang}:{item.title}", hint="Run resolve and pick an existing title", code="article_missing")
                    missing.append({"basket": basket.id, "item": item.id, "lang": lang})
                    continue
                art = articles.setdefault((lang, entry["title"]), Article(lang, entry["title"], entry))
                art.members.append(where)
    return list(articles.values()), missing, unresolved


def article_series(art: Article, start: dt.date, end: dt.date) -> list[Series]:
    project, owner = project_of(art.lang), f"{art.lang}:{art.title}"
    out = [
        Series(project, art.title, "all-access", "user", start, end, "main", owner),
        Series(project, art.title, "all-access", "automated", start, end, "main", owner),
        Series(project, art.title, "desktop", "user", start, end, "main", owner),
    ]
    redirects = set(art.entry.get("redirects", []))
    for r in sorted(redirects):
        out.append(Series(project, r, "all-access", "user", start, end, "redirect", owner))
    for f in art.entry.get("former_titles", []):
        if f["title"] in redirects or f["title"] == art.title:
            continue  # still a redirect: already counted over the whole range
        cut = min(end, day(f["moved_at"]))
        if cut >= start:
            out.append(Series(project, f["title"], "all-access", "user", start, cut, "former_title", owner))
    return out


def build_plan(spec: AnalysisSpec, cache: Cache, resolver: Resolver | None) -> Plan:
    end_month = data_as_of(spec)
    start, end = first_day(start_month(spec, end_month)), last_day(end_month)
    articles, missing, unresolved = collect_articles(spec, cache, resolver)

    series: list[Series] = []
    for lang in spec.langs:
        for agent in ("user", "automated"):
            series.append(Series(project_of(lang), AGGREGATE, "all-access", agent, start, end, "aggregate", lang))
    for art in articles:
        series.extend(article_series(art, start, end))

    unique: dict[tuple[str, str, str, str], Series] = {}
    for s in series:
        if s.key in unique:  # same page reached twice (e.g. shared redirect): widest range wins
            u = unique[s.key]
            u.start, u.end = min(u.start, s.start), max(u.end, s.end)
        else:
            unique[s.key] = s

    for s in unique.values():
        covered = [(day(c["start"]), day(c["end"])) for c in cache.coverage(*s.key)]
        fetch_from = s.start
        if s.agent == "automated" and s.start < AUTOMATED_START:
            s.unavailable = (s.start, min(s.end, AUTOMATED_START - dt.timedelta(days=1)))
            s.unavailable_recorded = not gaps(s.unavailable, covered)
            fetch_from = AUTOMATED_START
        if fetch_from <= s.end:
            s.gaps = gaps((fetch_from, s.end), covered)
    return Plan(start, end, end_month, articles, list(unique.values()), missing, unresolved)


# -- execution -------------------------------------------------------------------------


def series_url(s: Series, start: dt.date, end: dt.date) -> str:
    span = f"daily/{start:%Y%m%d}/{end:%Y%m%d}"
    if s.article == AGGREGATE:
        return f"{PV_API}/aggregate/{s.project}/{s.access}/{s.agent}/{span}"
    title = quote(s.article.replace(" ", "_"), safe="")
    return f"{PV_API}/per-article/{s.project}/{s.access}/{s.agent}/{title}/{span}"


def fetch_range(http: HttpClient, s: Series, start: dt.date, end: dt.date) -> tuple[list[tuple[str, int]], str]:
    resp = http.get(series_url(s, start, end), allow_statuses=(200, 404))
    if resp.status_code == 404:
        if s.article == AGGREGATE:
            raise WikiInterestError(f"no aggregate data for {s.project} {start}..{end}", code="no_data")
        # Titles come from resolve, so they exist: 404 means no views in the range.
        return [], "empty_404"
    data = parse_json(resp)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise WikiInterestError(f"unexpected Pageviews response for {s.project} {s.article}", code="bad_response")
    rows = [(f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}-{i['timestamp'][6:8]}", int(i["views"])) for i in items]
    return rows, "ok"


def execute(plan: Plan, http: HttpClient, cache: Cache) -> tuple[list[dict[str, Any]], RateLimitError | None]:
    """Download every gap. Failures do not stop the others, except a rate limit, after which nothing
    more is requested. Returns (missing series ranges, the rate-limit error if one occurred)."""
    missing: list[dict[str, Any]] = []
    total, n = plan.requests_needed, 0
    ordered = sorted(plan.series, key=lambda s: (s.article != AGGREGATE, s.owner, s.role != "main", s.article, s.access, s.agent))
    rate_limited: RateLimitError | None = None
    for s in ordered:
        if s.unavailable and not s.unavailable_recorded:
            u0, u1 = s.unavailable
            cache.put_pageviews(*s.key, [], start=iso(u0), end=iso(u1), status="unavailable")
        for g0, g1 in s.gaps:
            if rate_limited is not None:
                missing.append({**s.describe(), "start": iso(g0), "end": iso(g1), "error": "not attempted: rate limited"})
                continue
            n += 1
            log.info("[%d/%d] %s %s %s/%s %s..%s", n, total, s.project, s.article, s.access, s.agent, g0, g1)
            try:
                rows, status = fetch_range(http, s, g0, g1)
            except RateLimitError as exc:
                rate_limited = exc
                missing.append({**s.describe(), "start": iso(g0), "end": iso(g1), "error": exc.message})
                log.error("rate limited; stopping downloads (cached data is kept)")
                continue
            except WikiInterestError as exc:
                missing.append({**s.describe(), "start": iso(g0), "end": iso(g1), "error": exc.message})
                log.error("failed: %s", exc.message)
                continue
            covered_to = g1
            if s.article == AGGREGATE:
                # Project totals are never zero: a short answer means the API has no data yet.
                last = max((day(d) for d, _ in rows), default=None)
                if last is None or last < g1:
                    covered_to = last if last is not None else g0 - dt.timedelta(days=1)
                    missing.append({
                        **s.describe(),
                        "start": iso(covered_to + dt.timedelta(days=1)),
                        "end": iso(g1),
                        "error": "the API returned no data for these days",
                    })
            if covered_to >= g0:
                cache.put_pageviews(*s.key, [r for r in rows if r[0] <= iso(covered_to)], start=iso(g0), end=iso(covered_to), status=status)
    return missing, rate_limited


# -- command ---------------------------------------------------------------------------


def _write_result(workdir: Path, payload: dict[str, Any]) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / RESULT_FILE
    path.write_text(json.dumps({"tool_version": __version__, **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def cmd_fetch(args: Any, ctx: Any) -> dict[str, Any]:
    spec = parse_analysis_spec(load_json_file(args.spec, "analysis spec"))
    cache: Cache = ctx.cache

    if args.dry_run:
        plan = build_plan(spec, cache, None)
        needed = plan.requests_needed
        cached = sum(1 for s in plan.series if not s.gaps)
        seconds = round(needed * EST_SECONDS_PER_REQUEST)
        out = {
            "dry_run": True,
            "data_as_of": plan.data_as_of,
            "range": {"start": iso(plan.start), "end": iso(plan.end)},
            "series": len(plan.series),
            "series_cached": cached,
            "requests_needed": needed,
            "estimated_seconds": seconds,
            "estimated_minutes": round(seconds / 60, 1),
            "missing_articles": plan.missing_articles,
            "unresolved": plan.unresolved,
        }
        if plan.unresolved:
            out["note"] = (
                f"{len(plan.unresolved)} item/language pairs are not resolved yet; their redirects are unknown, so "
                "requests_needed is a lower bound (each article needs at least 3 requests plus resolve). "
                "Run `resolve` first for an exact estimate."
            )
        return out

    resolver = Resolver(ctx.http, cache)
    plan = build_plan(spec, cache, resolver)
    cached = sum(1 for s in plan.series if not s.gaps)
    needed = plan.requests_needed
    log.info(
        "fetch: %d series, %d already cached, %d requests to make (~%d s)",
        len(plan.series), cached, needed, round(needed * EST_SECONDS_PER_REQUEST),
    )
    resolve_requests = ctx.http.requests_made
    missing, rate_limited = execute(plan, ctx.http, cache)
    common = {
        "data_as_of": plan.data_as_of,
        "range": {"start": iso(plan.start), "end": iso(plan.end)},
    }
    result_file = _write_result(
        ctx.settings.workdir,
        {
            **common,
            "question": spec.question,
            "series": [s.describe() for s in plan.series],
            "missing_series": missing,
            "missing_articles": plan.missing_articles,
            "articles": [{"lang": a.lang, "title": a.title, "qid": a.entry.get("qid"), "members": a.members} for a in plan.articles],
        },
    )
    summary = {
        **common,
        "requests": ctx.http.requests_made,
        "resolve_requests": resolve_requests,
        "cache_hits": cached,
        "series": len(plan.series),
        "missing_series": missing[:MAX_LISTED],
        "missing_series_count": len(missing),
        "missing_articles": plan.missing_articles,
        "result_file": str(result_file),
    }
    if missing and not args.allow_partial:
        details = {"missing_series": missing[:MAX_LISTED], "missing_series_count": len(missing), "result_file": str(result_file)}
        if rate_limited is not None:
            raise RateLimitError(
                f"rate limited after {ctx.http.requests_made} requests; {len(missing)} series ranges not downloaded",
                hint="Wait a few minutes and rerun: only the missing ranges will be requested",
                details=details,
            )
        raise IncompleteDataError(
            f"{len(missing)} series ranges could not be downloaded",
            hint="Rerun to retry only the missing ranges, or pass --allow-partial to continue; "
            "analyze will flag PARTIAL_DATA",
            details=details,
        )
    return summary

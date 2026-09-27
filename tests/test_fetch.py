"""fetch: recorded Pageviews/MediaWiki fixtures replayed through the CLI, plus planner units."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import requests

from conftest import FakeSession, make_response
from replay import load_fixture, replay_session
from wiki_interest.cache import Cache
from wiki_interest.cli import main
from wiki_interest.config import load_settings
from wiki_interest.dates import gaps
from wiki_interest.errors import InputError
from wiki_interest.fetch import AGGREGATE, Article, Plan, Series, article_series, build_plan, execute, start_month
from wiki_interest.http import HttpClient
from wiki_interest.schemas import parse_analysis_spec

D = dt.date


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    """No real waiting: zero interval and no backoff sleeps in CLI-level runs."""
    monkeypatch.setenv("WIKI_INTEREST_MIN_INTERVAL", "0")
    monkeypatch.setattr("wiki_interest.http.time.sleep", lambda s: None)


def write_spec(tmp_path: Path, spec: dict, name: str = "analysis.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return str(path)


def run(capsys, tmp_path, spec, session, *extra):
    code = main(["--cache-dir", str(tmp_path / "c"), "--workdir", str(tmp_path / "out"), "fetch", "--spec", write_spec(tmp_path, spec), *extra], session=session)
    out, err = capsys.readouterr()
    return code, json.loads(out), err


def pageview_urls(session: FakeSession) -> list[str]:
    return [u for u, _ in session.calls if "wikimedia.org" in u]


def warm_neutron(capsys, tmp_path) -> tuple[dict, dict]:
    """Run both recorded steps (fixtures of step 2 exist only on top of step 1). Returns (fixture, step2 spec)."""
    fx = load_fixture("fetch", "neutron_uk")
    for step in fx["input"]:
        code, out, _ = run(capsys, tmp_path, step, replay_session(fx))
        assert code == 0, out
    return fx, fx["input"][1]


def cache_at(tmp_path) -> Cache:
    return Cache(tmp_path / "c" / "cache.sqlite")


# -- recorded scenarios ----------------------------------------------------------------


def test_neutron_full_then_only_missing_month(capsys, tmp_path):
    fx = load_fixture("fetch", "neutron_uk")
    step1, step2 = fx["input"]

    s1 = replay_session(fx)
    code, out, err = run(capsys, tmp_path, step1, s1)
    assert code == 0, out
    assert out["data_as_of"] == "2026-07"
    assert out["range"] == {"start": "2025-07-01", "end": "2026-07-31"}
    assert out["series"] == 7 and out["missing_series"] == [] and out["missing_articles"] == []
    assert len(pageview_urls(s1)) == 7
    assert "[7/7]" in err and "Нейтронна зірка" in err  # progress on stderr

    s2 = replay_session(fx)
    code, out, _ = run(capsys, tmp_path, step2, s2)
    assert code == 0 and out["data_as_of"] == "2026-08"
    urls = pageview_urls(s2)
    assert len(urls) == 7 and all(u.endswith("/daily/20260801/20260831") for u in urls)
    assert out["resolve_requests"] == 0  # resolve results came from the cache

    s3 = replay_session(fx)
    code, out, _ = run(capsys, tmp_path, step2, s3)
    assert code == 0 and out["requests"] == 0 and out["cache_hits"] == 7 and s3.calls == []

    with cache_at(tmp_path) as cache:
        cov = cache.coverage("uk.wikipedia", "Нейтронна зоря", "all-access", "user")
        assert [(c["start"], c["end"], c["status"]) for c in cov] == [
            ("2025-07-01", "2026-07-31", "ok"),
            ("2026-08-01", "2026-08-31", "ok"),
        ]
        stored = sum(v for _, v in cache.get_pageviews("uk.wikipedia", "Нейтронна зоря", "all-access", "user", "2026-08-01", "2026-08-31"))
    url = next(u for u in fx["responses"] if "/all-access/user/%D0%9D%D0%B5%D0%B9%D1%82%D1%80%D0%BE%D0%BD%D0%BD%D0%B0_%D0%B7%D0%BE" in u and u.endswith("20260801/20260831"))
    assert stored == sum(i["views"] for i in fx["responses"][url]["json"]["items"]) > 0


def test_redirects_get_user_series_only(capsys, tmp_path):
    warm_neutron(capsys, tmp_path)
    result = json.loads((tmp_path / "out" / "fetch_result.json").read_text(encoding="utf-8"))
    by_article: dict[str, set] = {}
    for s in result["series"]:
        by_article.setdefault(s["article"], set()).add((s["access"], s["agent"], s["role"]))
    assert by_article["Нейтронна зоря"] == {("all-access", "user", "main"), ("all-access", "automated", "main"), ("desktop", "user", "main")}
    assert by_article["Нейтронна зірка"] == {("all-access", "user", "redirect")}
    assert by_article["Нейтронні зорі"] == {("all-access", "user", "redirect")}
    assert by_article[AGGREGATE] == {("all-access", "user", "aggregate"), ("all-access", "automated", "aggregate")}


def test_missing_article_is_listed_and_proxy_fetched(capsys, tmp_path):
    fx = load_fixture("fetch", "fasting_pl_cs")
    code, out, _ = run(capsys, tmp_path, fx["input"][0], replay_session(fx))
    assert code == 0
    assert out["missing_articles"] == [{"basket": "target", "item": "Q1666254", "lang": "pl"}]
    result = json.loads(Path(out["result_file"]).read_text(encoding="utf-8"))
    titles = {(a["lang"], a["title"]) for a in result["articles"]}
    assert titles == {("cs", "Přerušovaný půst"), ("pl", "Głodówka lecznicza")}
    redirect = [s for s in result["series"] if s["article"] == "Głodówka oczyszczająca"]
    assert [(s["access"], s["agent"]) for s in redirect] == [("all-access", "user")]


def test_dry_run_makes_no_requests(capsys, tmp_path):
    fx = load_fixture("fetch", "neutron_uk")
    step1, step2 = fx["input"]
    offline = FakeSession(lambda u, p: pytest.fail(f"request during dry run: {u}"))

    code, out, _ = run(capsys, tmp_path, step2, offline, "--dry-run")
    assert code == 0 and out["dry_run"] is True
    assert out["unresolved"] and "lower bound" in out["note"]
    assert out["requests_needed"] == 2  # only the aggregates are known before resolve

    run(capsys, tmp_path, step1, replay_session(fx))
    code, out, _ = run(capsys, tmp_path, step2, offline, "--dry-run")
    assert code == 0 and out["unresolved"] == [] and "note" not in out
    assert out["series"] == 7 and out["series_cached"] == 0 and out["requests_needed"] == 7
    assert out["estimated_seconds"] == round(7 * 0.6)


def test_network_failure_exit_5_then_allow_partial_then_resume(capsys, tmp_path):
    fx = load_fixture("fetch", "neutron_uk")
    step1, spec = fx["input"]
    code, _, _ = run(capsys, tmp_path, step1, replay_session(fx))
    assert code == 0
    spec = {**spec, "window": {"months": 1, "end": "2026-08"}}
    replay = replay_session(fx)

    def flaky(url, params):
        if "wikimedia.org" in url and "desktop" in url:
            raise requests.exceptions.ConnectionError("proxy refused")
        return replay._responder(url, params)

    code, out, _ = run(capsys, tmp_path, spec, FakeSession(flaky))
    assert code == 5 and out["ok"] is False and out["error"]["code"] == "incomplete_data"
    missing = out["error"]["details"]["missing_series"]
    assert len(missing) == 1 and missing[0]["access"] == "desktop" and "wikimedia.org" in missing[0]["error"]

    code, out, _ = run(capsys, tmp_path, spec, FakeSession(flaky), "--allow-partial")
    assert code == 0 and out["missing_series_count"] == 1

    healthy = replay_session(fx)
    code, out, _ = run(capsys, tmp_path, spec, healthy)
    assert code == 0 and out["missing_series"] == []
    assert len(pageview_urls(healthy)) == 1 and "/desktop/" in pageview_urls(healthy)[0]


def test_rate_limit_stops_downloads_exit_4(capsys, tmp_path):
    fx = load_fixture("fetch", "neutron_uk")
    replay = replay_session(fx)

    def limited(url, params):
        if "wikimedia.org" in url:
            return make_response(429, {})
        return replay._responder(url, params)

    session = FakeSession(limited)
    code, out, _ = run(capsys, tmp_path, fx["input"][1], session)
    assert code == 4 and out["error"]["code"] == "rate_limited"
    assert len(pageview_urls(session)) == 6  # one series retried 6 times, then nothing more
    details = out["error"]["details"]
    assert details["missing_series_count"] == 7
    assert sum("not attempted" in m["error"] for m in details["missing_series"]) == 6


def test_404_for_resolved_title_is_confirmed_zero(tmp_path):
    fx = load_fixture("raw", "pageviews_404")
    settings = load_settings(cache_dir=tmp_path / "c")
    s = Series("uk.wikipedia", "Нейтронні зорі", "all-access", "user", D(2026, 8, 3), D(2026, 8, 4), "redirect", "uk:Нейтронна зоря")
    s.gaps = [(D(2026, 8, 3), D(2026, 8, 4))]
    plan = Plan(s.start, s.end, "2026-08", [], [s], [], [])
    with Cache(settings.cache_path) as cache:
        missing, limited = execute(plan, HttpClient(settings, replay_session(fx), cache, sleep=lambda x: None), cache)
        assert missing == [] and limited is None
        cov = cache.coverage(*s.key)
        assert [(c["start"], c["end"], c["status"]) for c in cov] == [("2026-08-03", "2026-08-04", "empty_404")]
        assert cache.get_pageviews(*s.key, "2026-08-01", "2026-08-31") == []


def test_short_aggregate_answer_is_incomplete(tmp_path):
    fx = load_fixture("fetch", "neutron_uk")
    url = next(u for u in fx["responses"] if "/aggregate/uk.wikipedia/all-access/user/daily/20260801/20260831" in u)
    body = json.loads(json.dumps(fx["responses"][url]["json"]))
    body["items"] = body["items"][:20]  # real data, cut after 2026-08-20
    settings = load_settings(cache_dir=tmp_path / "c")
    s = Series("uk.wikipedia", AGGREGATE, "all-access", "user", D(2026, 8, 1), D(2026, 8, 31), "aggregate", "uk")
    s.gaps = [(s.start, s.end)]
    with Cache(settings.cache_path) as cache:
        http = HttpClient(settings, FakeSession([make_response(200, body)]), cache, sleep=lambda x: None)
        missing, _ = execute(Plan(s.start, s.end, "2026-08", [], [s], [], []), http, cache)
        assert [(m["start"], m["end"]) for m in missing] == [("2026-08-21", "2026-08-31")]
        cov = cache.coverage(*s.key)
        assert [(c["start"], c["end"]) for c in cov] == [("2026-08-01", "2026-08-20")]


# -- planning --------------------------------------------------------------------------


def neutron_resolved_cache(tmp_path, capsys) -> Path:
    warm_neutron(capsys, tmp_path)
    return tmp_path / "c" / "cache.sqlite"


def spec_with(**over):
    base = {
        "question": "q",
        "langs": ["uk"],
        "window": {"months": 12, "end": "2026-08"},
        "baskets": [{"id": "target", "role": "target", "label": "x", "items": [{"lang": "uk", "title": "Нейтронна зоря"}]}],
    }
    base.update(over)
    return parse_analysis_spec(base)


def test_automated_before_may_2020_is_unavailable_not_requested(tmp_path, capsys):
    path = neutron_resolved_cache(tmp_path, capsys)
    with Cache(path) as cache:
        plan = build_plan(spec_with(history_start="2019-01"), cache, None)
        auto = [s for s in plan.series if s.agent == "automated"]
        assert len(auto) == 2
        for s in auto:
            assert s.unavailable == (D(2019, 1, 1), D(2020, 4, 30))
            assert s.gaps == [(D(2020, 5, 1), D(2025, 6, 30))]
        user = next(s for s in plan.series if s.article == "Нейтронна зоря" and s.agent == "user" and s.access == "all-access")
        assert user.gaps == [(D(2019, 1, 1), D(2025, 6, 30))]

        # Recording "unavailable" needs no request.
        for s in plan.series:
            s.gaps = []
        settings = load_settings(cache_dir=path.parent)
        offline = FakeSession(lambda u, p: pytest.fail("no request expected"))
        execute(plan, HttpClient(settings, offline, cache), cache)
        cov = cache.coverage("uk.wikipedia", "Нейтронна зоря", "all-access", "automated")
        assert ("2019-01-01", "2020-04-30", "unavailable") in [(c["start"], c["end"], c["status"]) for c in cov]
        assert cache.get_pageviews("uk.wikipedia", "Нейтронна зоря", "all-access", "automated", "2019-01-01", "2020-04-30") == []
        again = build_plan(spec_with(history_start="2019-01"), cache, None)
        assert all(s.unavailable_recorded for s in again.series if s.unavailable)


def test_former_title_cut_at_moved_at_unless_redirect():
    entry = {
        "redirects": ["Нейтронна зірка"],
        "former_titles": [
            {"title": "Марс", "moved_at": "2021-11-23T10:56:06Z", "is_redirect": False},
            {"title": "Нейтронна зірка", "moved_at": "2021-03-30T13:53:13Z", "is_redirect": True},
            {"title": "Стара", "moved_at": "2014-01-01T00:00:00Z", "is_redirect": False},
        ],
    }
    series = article_series(Article("uk", "Стаття", entry), D(2015, 7, 1), D(2026, 8, 31))
    former = [(s.article, s.role, s.end) for s in series if s.role != "main"]
    assert former == [
        ("Нейтронна зірка", "redirect", D(2026, 8, 31)),
        ("Марс", "former_title", D(2021, 11, 23)),
    ]
    assert all((s.access, s.agent) == ("all-access", "user") for s in series if s.role != "main")


def test_title_item_that_does_not_exist_is_an_input_error(tmp_path, capsys):
    path = neutron_resolved_cache(tmp_path, capsys)
    with Cache(path) as cache:
        cache.put_resolved({"title:uk:Нема": {"status": "missing", "title": None, "lang": "uk"}})
        spec = spec_with(baskets=[{"id": "target", "role": "target", "label": "x", "items": [{"lang": "uk", "title": "Нема"}]}])
        from wiki_interest.resolve import Resolver

        resolver = Resolver(HttpClient(load_settings(cache_dir=path.parent), FakeSession([])), cache)
        with pytest.raises(InputError) as ei:
            build_plan(spec, cache, resolver)
    assert ei.value.exit_code == 2 and "target/uk:Нема" in ei.value.message


def test_window_end_after_latest_month_rejected(capsys, tmp_path):
    spec = {
        "question": "q", "langs": ["uk"], "window": {"months": 12, "end": "2099-01"},
        "baskets": [{"id": "target", "role": "target", "label": "x", "items": [{"qid": "Q4202"}]}],
    }
    code, out, _ = run(capsys, tmp_path, spec, FakeSession([]), "--dry-run")
    assert code == 2 and "2099-01" in out["error"]["message"]


@pytest.mark.parametrize(
    "months, history, baselines, expected",
    [
        (12, "2025-06", [], "2024-09"),  # same 12 months a year earlier
        (1, "2025-08", [], "2025-08"),
        (1, "2026-01", [], "2025-08"),
        (6, "2026-01", [2019], "2019-01"),
        (12, "2015-07", [], "2015-07"),
    ],
)
def test_start_month(months, history, baselines, expected):
    spec = spec_with(window={"months": months, "end": "2026-08"}, history_start=history, baselines=baselines)
    assert start_month(spec, "2026-08") == expected


def test_gaps():
    want = (D(2020, 1, 1), D(2020, 1, 31))
    assert gaps(want, []) == [want]
    assert gaps(want, [(D(2019, 1, 1), D(2021, 1, 1))]) == []
    assert gaps(want, [(D(2020, 1, 5), D(2020, 1, 10)), (D(2020, 1, 20), D(2020, 2, 10))]) == [
        (D(2020, 1, 1), D(2020, 1, 4)),
        (D(2020, 1, 11), D(2020, 1, 19)),
    ]
    assert gaps(want, [(D(2020, 1, 1), D(2020, 1, 15)), (D(2020, 1, 16), D(2020, 1, 31))]) == []


@pytest.mark.parametrize(
    "patch, fragment",
    [
        ({"langs": []}, '"langs"'),
        ({"window": {"months": 0}}, "window.months"),
        ({"window": {"end": "2026-13"}}, "window.end"),
        ({"history_start": "2014-01"}, "before 2015-07"),
        ({"baselines": ["2019"]}, "baselines"),
        ({"baskets": [{"id": "Target", "role": "target", "label": "x", "items": [{"qid": "Q1"}]}]}, "baskets[0].id"),
        ({"baskets": [{"id": "t", "role": "main", "label": "x", "items": [{"qid": "Q1"}]}]}, "role"),
        ({"baskets": [{"id": "t", "role": "context", "label": "x", "items": [{"qid": "Q1"}]}]}, 'role "target"'),
        ({"baskets": [{"id": "t", "role": "target", "label": "x", "items": [{"lang": "pl", "title": "x"}]}]}, "not in"),
        ({"baskets": [{"id": "t", "role": "target", "label": "x", "items": [{"qid": "Q1", "proxy_for": "Q2"}]}]}, "unexpected keys"),
        ({"extra": 1}, "unexpected keys"),
    ],
)
def test_analysis_spec_validation(patch, fragment):
    base = {
        "question": "q",
        "langs": ["uk"],
        "baskets": [{"id": "target", "role": "target", "label": "x", "items": [{"qid": "Q1"}]}],
    }
    base.update(patch)
    with pytest.raises(InputError) as ei:
        parse_analysis_spec(base)
    assert fragment in ei.value.message

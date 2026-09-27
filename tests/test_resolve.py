"""resolve: regression cases from SPEC §6 on recorded API fixtures, plus unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FakeSession
from replay import load_fixture, replay_session
from wiki_interest.cache import Cache
from wiki_interest.cli import main
from wiki_interest.errors import InputError
from wiki_interest.http import HttpClient
from wiki_interest.resolve import Resolver, base_title, choose_candidate, lookup_article
from wiki_interest.schemas import parse_resolve_request


def run_case(name, settings, cache=None):
    fx = load_fixture("resolve", name)
    session = replay_session(fx)
    http = HttpClient(settings, session, cache, sleep=lambda s: None)
    result = Resolver(http, cache).run(parse_resolve_request(fx["input"]))
    return {r["id"]: r for r in result["items"]}, result, session


def no_network() -> FakeSession:
    def fail(url, params):
        raise AssertionError(f"unexpected network request: {url}")

    return FakeSession(fail)


# -- regression cases (SPEC §6) --------------------------------------------------------


def test_uk_mars_is_disambiguation_with_planet_candidate(settings):
    items, _, _ = run_case("mars_uk", settings)
    mars = items["uk:Марс"]
    assert mars["status"] == "needs_choice"
    entry = mars["langs"]["uk"]
    assert entry["status"] == "disambiguation"
    assert entry["title"] == "Марс"
    titles = [c["title"] for c in entry["candidates"]]
    assert titles[0] == "Марс (планета)"
    assert entry["candidates"][0]["qid"] == "Q111"
    assert "Марс (міфологія)" in titles


def test_uk_mars_planet_former_title_is_not_a_redirect(settings):
    items, _, _ = run_case("mars_uk", settings)
    planet = items["uk:Марс (планета)"]
    assert planet["status"] == "resolved" and planet["qid"] == "Q111"
    entry = planet["langs"]["uk"]
    assert entry["status"] == "ok"
    # «Марс» was the planet until the 2015 move and is now a disambiguation page:
    # fetch must count it only up to moved_at.
    assert entry["former_titles"] == [{"title": "Марс", "moved_at": "2015-12-14T13:05:02Z", "is_redirect": False}]
    assert entry["created"] and entry["length"] > 0


def test_uk_mars_query_is_not_auto_selected(settings):
    items, _, _ = run_case("mars_uk", settings)
    q = items["query:uk:Марс"]
    assert q["status"] == "needs_choice" and q["needs_choice"] is True
    assert q["qid"] is None and q["langs"] == {}
    assert [c["qid"] for c in q["candidates"]][:2] == ["Q111", "Q112"]
    assert len(q["candidates"]) == 5


def test_pl_intermittent_fasting_missing_with_non_equivalent_hits(settings):
    items, result, _ = run_case("fasting_pl_cs", settings)
    rec = items["Q1666254"]
    pl, cs = rec["langs"]["pl"], rec["langs"]["cs"]
    assert pl["status"] == "missing" and pl["title"] is None
    assert 0 < len(pl["search_hits"]) <= 5
    assert all(h["not_equivalent"] is True for h in pl["search_hits"])
    assert "Głodówka lecznicza" in [h["title"] for h in pl["search_hits"]]
    assert cs["status"] == "ok" and cs["title"] == "Přerušovaný půst" and cs["qid"] == "Q1666254"
    row = next(r for r in result["coverage"]["rows"] if r["id"] == "Q1666254")
    assert result["coverage"]["langs"] == ["pl", "cs"] and row["cells"] == ["missing", "ok"]


def test_query_auto_selected_keeps_candidates(settings):
    items, _, _ = run_case("fasting_pl_cs", settings)
    q = items["query:uk:інтервальне голодування"]
    assert q["auto_selected"] is True and q["qid"] == "Q1666254"
    assert q["candidates"] and q["candidates"][0]["qid"] == "Q1666254"
    assert q["langs"]["pl"]["status"] == "missing"


def test_es_reglas_del_ajedrez_redirect_to_leyes(settings):
    items, _, _ = run_case("chess_rules_es", settings)
    rec = items["es:Reglas del ajedrez"]
    es = rec["langs"]["es"]
    assert es["status"] == "redirect_resolved"
    assert es["requested_title"] == "Reglas del ajedrez"
    assert es["title"] == "Leyes del ajedrez"
    assert rec["qid"] == es["qid"] == "Q3392263"
    assert "Reglas del ajedrez" in es["redirects"]
    # Other languages are matched through the QID of the real article.
    assert rec["langs"]["pt"]["status"] == "ok" and rec["langs"]["pt"]["title"] == "Leis do xadrez"
    # de has no rules article: explicit "missing", never a silent substitute (baseline D).
    de = rec["langs"]["de"]
    assert de["status"] == "missing" and all(h["not_equivalent"] for h in de["search_hits"])


def test_uk_neutron_star_rename_2021(settings):
    items, _, _ = run_case("neutron_star_uk", settings)
    entry = items["uk:Нейтронна зоря"]["langs"]["uk"]
    assert entry["status"] == "ok" and entry["qid"] == "Q4202"
    former = {f["title"]: f for f in entry["former_titles"]}
    assert former["Нейтронна зірка"]["moved_at"].startswith("2021-03-30")
    assert former["Нейтронна зірка"]["is_redirect"] is True
    assert "Нейтронна зірка" in entry["redirects"]


def test_title_with_apostrophe(settings):
    items, _, _ = run_case("neutron_star_uk", settings)
    entry = items["uk:Сузір'я"]["langs"]["uk"]
    assert entry["status"] == "ok" and entry["title"] == "Сузір'я"


def test_unknown_qid_is_reported_not_dropped(settings):
    items, result, _ = run_case("unknown_qid", settings)
    rec = items["Q999999999999"]
    assert rec["status"] == "not_found" and "does not exist" in rec["error"]
    assert result["coverage"]["rows"][0]["cells"] == [None]


# -- cache as the source of truth ------------------------------------------------------


def test_second_run_is_served_from_http_cache(settings):
    with Cache(settings.cache_path) as cache:
        _, first, s1 = run_case("chess_rules_es", settings, cache)
        fx = load_fixture("resolve", "chess_rules_es")
        http = HttpClient(settings, no_network(), cache, sleep=lambda s: None)
        second = Resolver(http, cache).run(parse_resolve_request(fx["input"]))
    assert second == first
    assert http.requests_made == 0 and http.cache_hits > 0


def test_lookup_article_reads_resolved_cache_without_network(settings):
    with Cache(settings.cache_path) as cache:
        run_case("chess_rules_es", settings, cache)
        run_case("fasting_pl_cs", settings, cache)
        run_case("mars_uk", settings, cache)
        resolver = Resolver(HttpClient(settings, no_network(), cache), cache)
        by_qid = lookup_article(resolver, cache, "es", qid="Q3392263")
        by_old_title = lookup_article(resolver, cache, "es", title="Reglas del ajedrez")
        assert by_qid["title"] == by_old_title["title"] == "Leyes del ajedrez"
        assert lookup_article(resolver, cache, "cs", qid="Q1666254")["title"] == "Přerušovaný půst"
        with pytest.raises(InputError) as ei:
            lookup_article(resolver, cache, "pl", qid="Q1666254")
        assert ei.value.code == "article_missing" and ei.value.exit_code == 2
        with pytest.raises(InputError) as ei:
            lookup_article(resolver, cache, "uk", title="Марс")
        assert ei.value.code == "disambiguation"


def test_lookup_article_resolves_on_cache_miss(settings):
    fx = load_fixture("resolve", "unknown_qid")
    session = replay_session(fx)
    with Cache(settings.cache_path) as cache:
        resolver = Resolver(HttpClient(settings, session, cache, sleep=lambda s: None), cache)
        with pytest.raises(InputError) as ei:
            lookup_article(resolver, cache, "uk", qid="Q999999999999")
    assert len(session.calls) == 1  # resolved on the fly, not read from a stale file
    assert ei.value.exit_code == 2 and "not_found" in ei.value.message


# -- CLI -------------------------------------------------------------------------------


def test_cli_resolve_writes_result_file_and_compact_stdout(capsys, tmp_path):
    fx = load_fixture("resolve", "mars_uk")
    spec = tmp_path / "resolve.json"
    spec.write_text(json.dumps(fx["input"], ensure_ascii=False), encoding="utf-8")
    code = main(["--workdir", str(tmp_path / "out"), "resolve", "--input", str(spec)], session=replay_session(fx))
    out, _ = capsys.readouterr()
    assert code == 0
    assert len(out.encode("utf-8")) < 3000
    payload = json.loads(out)
    assert payload["ok"] is True and payload["tool_version"]
    assert payload["attention"]
    full = json.loads(Path(payload["result_file"]).read_text(encoding="utf-8"))
    assert {i["id"] for i in full["items"]} == {"uk:Марс", "uk:Марс (планета)", "query:uk:Марс"}
    entry = next(i for i in full["items"] if i["id"] == "uk:Марс (планета)")["langs"]["uk"]
    for key in ("status", "title", "qid", "created", "length", "redirects", "former_titles", "search_hits"):
        assert key in entry


def test_cli_resolve_invalid_input_exit_2(capsys, tmp_path):
    spec = tmp_path / "bad.json"
    spec.write_text('{"items": [{"qid": "Mars"}], "langs": ["uk"]}', encoding="utf-8")
    code = main(["resolve", "--input", str(spec)], session=no_network())
    out = json.loads(capsys.readouterr()[0])
    assert code == 2 and out["error"]["code"] == "invalid_input" and "Q1666254" in out["error"]["hint"]


# -- units -----------------------------------------------------------------------------


def test_choose_candidate_rules():
    one = [{"label": "X", "match": "X"}]
    assert choose_candidate("anything", one) == 0
    assert choose_candidate("q", []) is None
    two_exact = [{"label": "Марс", "match": "Марс"}, {"label": "Марс", "match": "Марс"}]
    assert choose_candidate("марс", two_exact) is None
    first_only = [{"label": "Chess", "match": "chess"}, {"label": "Chess960", "match": "Chess960"}]
    assert choose_candidate("Chess", first_only) == 0
    second_only = [{"label": "Chess960", "match": "Chess960"}, {"label": "Chess", "match": "chess"}]
    assert choose_candidate("chess", second_only) is None
    alias = [{"label": "Intermittent fasting", "match": "IF"}, {"label": "IF", "match": "IF"}]
    assert choose_candidate("IF", alias) is None


def test_base_title():
    assert base_title("Марс (планета)") == "Марс"
    assert base_title("Leyes del ajedrez") == "Leyes del ajedrez"


@pytest.mark.parametrize(
    "data, fragment",
    [
        ([], "JSON object"),
        ({"items": []}, "non-empty"),
        ({"items": [{"qid": "Q1"}]}, '"langs" is empty'),
        ({"items": [{"qid": "Q1", "title": "x"}], "langs": ["uk"]}, "unexpected keys"),
        ({"items": [{"lang": "UK", "title": "x"}], "langs": []}, "invalid language"),
        ({"items": [{"query": "  "}], "langs": ["uk"]}, "non-empty string"),
        ({"items": [{"qid": "Q1"}], "langs": ["uk"], "extra": 1}, "unexpected keys"),
    ],
)
def test_resolve_input_validation(data, fragment):
    with pytest.raises(InputError) as ei:
        parse_resolve_request(data)
    assert fragment in ei.value.message
    assert ei.value.exit_code == 2


def test_title_only_input_needs_no_langs():
    req = parse_resolve_request({"items": [{"lang": "es", "title": "Reglas del ajedrez"}]})
    assert req.langs == [] and req.items[0].id == "es:Reglas del ajedrez"


def test_wikidata_labels_pass_through_verbatim(settings):
    """Labels are copied from Wikidata unchanged: pt label of Q3392263 is «leis do xadrez» with a space."""
    from wiki_interest.wikidata import Wikidata

    fx = load_fixture("resolve", "chess_rules_es")
    http = HttpClient(settings, replay_session(fx), None, sleep=lambda s: None)
    ent = Wikidata(http).entities(["Q3392263"], ["de", "es", "pt"])["Q3392263"]
    assert ent["labels"]["pt"] == "leis do xadrez"
    assert ent["labels"]["es"] == "Leyes del ajedrez"
    assert ent["sitelinks"]["pt"] == "Leis do xadrez"

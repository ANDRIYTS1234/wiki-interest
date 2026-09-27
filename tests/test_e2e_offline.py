"""Offline end-to-end: analyze -> report on the examples/B-fasting cache snapshot, no network."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from conftest import FakeSession
from wiki_interest.cli import main

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "B-fasting"


def no_network(url, params):
    raise AssertionError(f"network call in offline e2e: {url}")


def run(capsys, argv, session) -> dict:
    code = main(argv, session=session)
    out = json.loads(capsys.readouterr().out)
    assert code == 0, out
    return out


@pytest.mark.parametrize("report_lang", ["uk", "en"])
def test_analyze_report_offline(tmp_path, capsys, monkeypatch, report_lang):
    monkeypatch.setattr("requests.Session.request", lambda *a, **k: no_network(a[1:3], None))
    cache = tmp_path / "cache"
    shutil.copytree(EXAMPLE / "cache", cache)
    work = tmp_path / "work"
    session = FakeSession(no_network)
    common = ["--cache-dir", str(cache), "--workdir", str(work)]

    analyzed = run(capsys, [*common, "analyze", "--spec", str(EXAMPLE / "analysis.json")], session)
    metrics = Path(analyzed["metrics_file"])
    first = metrics.read_bytes()
    assert analyzed["data_as_of"] == "2026-08"
    assert "target.pl.window.change_norm" in analyzed["placeholders"]

    run(capsys, [*common, "analyze", "--spec", str(EXAMPLE / "analysis.json")], session)
    assert metrics.read_bytes() == first

    pdf = work / "report.pdf"
    reported = run(
        capsys,
        [*common, "report", "--metrics", str(metrics), "--narrative", str(EXAMPLE / "narrative.json"),
         "--out", str(pdf), "--report-lang", report_lang],
        session,
    )
    assert session.calls == []
    assert reported["pages"] == 1
    assert len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf.read_bytes())) == 1
    assert Path(reported["chart"]).is_file()
    assert "Głodówka lecznicza" in Path(reported["appendix"]).read_text(encoding="utf-8")


def _analyzed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("requests.Session.request", lambda *a, **k: no_network(a[1:3], None))
    cache = tmp_path / "cache"
    shutil.copytree(EXAMPLE / "cache", cache)
    common = ["--cache-dir", str(cache), "--workdir", str(tmp_path / "work")]
    out = run(capsys, [*common, "analyze", "--spec", str(EXAMPLE / "analysis.json")], FakeSession(no_network))
    return common, out


def test_languages_without_common_articles_are_called_out(tmp_path, capsys, monkeypatch):
    """Haiku compared the Polish stand-in with the Czech article when analyze only said
    "no_common_articles": the output must say plainly not to, and why."""
    _, out = _analyzed(tmp_path, capsys, monkeypatch)
    note = next(a for a in out["attention"] if "pl_vs_cs" in a)
    assert "DO NOT COMPARE DIRECTLY" in note
    assert "Głodówka lecznicza" in note and "Q1666254" in note  # the stand-in and the missing item
    w = json.loads(Path(out["metrics_file"]).read_text(encoding="utf-8"))["compare"]["target"]["pl_vs_cs"]["window"]
    assert w["comparable"] is False and w["reason"] == "no_common_articles"
    assert w["detail"] == {"missing": {"pl": ["Q1666254"]}, "proxies": {"pl": ["Głodówka lecznicza"]}}


def test_every_flag_and_incomparability_is_in_the_pdf(tmp_path, capsys, monkeypatch):
    """Haiku left some flags out of the PDF: they are now printed whatever the narrative says."""
    from reportlab.platypus import ListFlowable, Paragraph

    from wiki_interest.report.flag_text import FLAG_TEXT
    from wiki_interest.report.narrative import render_narrative, validate_narrative
    from wiki_interest.report.pdf import build_story

    _, out = _analyzed(tmp_path, capsys, monkeypatch)
    metrics = json.loads(Path(out["metrics_file"]).read_text(encoding="utf-8"))
    narrative = json.loads((EXAMPLE / "narrative.json").read_text(encoding="utf-8"))
    narrative["caveats"] = []  # the agent wrote none
    rendered = render_narrative(validate_narrative(narrative), metrics, "uk")
    chart = tmp_path / "c.png"
    from wiki_interest.report.charts import render_chart

    render_chart(metrics, chart, "uk")
    texts = []
    for item in build_story(metrics, rendered, chart, "uk"):
        if isinstance(item, Paragraph):
            texts.append(item.getPlainText())
        elif isinstance(item, ListFlowable):
            texts += [li._flowables[0].getPlainText() for li in item._flowables]
    joined = "\n".join(texts)
    codes = {f["code"] for f in metrics["flags"]}
    assert codes >= {"ARTICLE_MISSING", "PROXY_USED", "PANEL_SMALL"}
    for code in codes:
        assert FLAG_TEXT[code]["uk"] in joined, code
    assert "Мови pl і cs напряму не порівнюються" in joined


def test_follow_up_report_overwrites_the_same_file(tmp_path, capsys, monkeypatch):
    common, _ = _analyzed(tmp_path, capsys, monkeypatch)
    argv = [*common, "report", "--narrative", str(EXAMPLE / "narrative.json")]  # default --metrics and --out
    first = run(capsys, argv, FakeSession(no_network))
    second = run(capsys, argv, FakeSession(no_network))
    work = tmp_path / "work"
    assert Path(first["pdf"]) == Path(second["pdf"]) == work / "report.pdf"
    assert first["replaced"] is False and second["replaced"] is True
    assert sorted(p.name for p in work.glob("*.pdf")) == ["report.pdf"]


def test_failed_rerun_keeps_the_previous_report(tmp_path, capsys, monkeypatch):
    common, _ = _analyzed(tmp_path, capsys, monkeypatch)
    run(capsys, [*common, "report", "--narrative", str(EXAMPLE / "narrative.json")], FakeSession(no_network))
    pdf = tmp_path / "work" / "report.pdf"
    before = pdf.read_bytes()
    long = json.loads((EXAMPLE / "narrative.json").read_text(encoding="utf-8"))
    long["findings"] = [("Дуже довгий висновок без чисел. " * 9)[:300]] * 4
    long["caveats"] = [("Дуже довге застереження без чисел. " * 7)[:250]] * 6
    (tmp_path / "long.json").write_text(json.dumps(long, ensure_ascii=False), encoding="utf-8")
    code = main([*common, "report", "--narrative", str(tmp_path / "long.json")], session=FakeSession(no_network))
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["error"]["code"] == "report_too_long"
    assert "flag lines" in out["error"]["hint"] and "automatic" in out["error"]["hint"]
    assert pdf.read_bytes() == before


def _metrics(tmp_path, capsys, monkeypatch):
    common, out = _analyzed(tmp_path, capsys, monkeypatch)
    return common, json.loads(Path(out["metrics_file"]).read_text(encoding="utf-8"))


def test_flag_places_are_basket_labels_or_all_baskets(tmp_path, capsys, monkeypatch):
    from wiki_interest.report.flag_text import FLAG_TEXT, flag_lines

    _, m = _metrics(tmp_path, capsys, monkeypatch)
    labels = {b: i["label"] for b, i in m["basket_info"].items()}
    lines = flag_lines(m["flags"], "uk", labels, m["spec"]["langs"])
    joined = "\n".join(lines)
    assert "target/" not in joined and "window" not in joined and "baseline:" not in joined  # no technical paths
    # example B has one basket: a flag on it reads "усі кошики", a pl-only flag adds the language
    missing = next(l for l in lines if l.startswith(FLAG_TEXT["ARTICLE_MISSING"]["uk"]))
    assert missing.endswith("(усі кошики — pl)")
    # two baskets, flag on one: its label, not its id
    two = {"target": "Астрономія", "control": "Інші науки"}
    flags = [{"code": "LOW_VOLUME", "basket": "control", "lang": "uk"}]
    assert flag_lines(flags, "uk", two, ["uk"]) == [f"{FLAG_TEXT['LOW_VOLUME']['uk']} (Інші науки)"]


def test_badges_show_basket_labels(tmp_path, capsys, monkeypatch):
    from reportlab.platypus import Table

    from wiki_interest.report.pdf import _confidence_badge, _styles

    _, m = _metrics(tmp_path, capsys, monkeypatch)
    badge = _confidence_badge(m["baskets"], m["spec"]["langs"], "uk", _styles("uk"), m["basket_info"])
    texts = [cell._cellvalues[0][0].getPlainText() for row in badge._cellvalues for cell in row if isinstance(cell, Table)]
    label = m["basket_info"]["target"]["label"]
    assert texts and all(t.startswith(label) for t in texts) and not any(t.startswith("target") for t in texts)


def test_caveat_repeating_an_automatic_line_is_dropped_and_reported(tmp_path, capsys, monkeypatch):
    common, _ = _analyzed(tmp_path, capsys, monkeypatch)
    n = json.loads((EXAMPLE / "narrative.json").read_text(encoding="utf-8"))
    own = n["caveats"][0]
    n["caveats"] = ["Cannot compare Polish and Czech data directly.", own]
    (tmp_path / "n.json").write_text(json.dumps(n, ensure_ascii=False), encoding="utf-8")
    out = run(capsys, [*common, "report", "--narrative", str(tmp_path / "n.json")], FakeSession(no_network))
    assert out["caveats_dropped"] == [{"caveat": "Cannot compare Polish and Czech data directly.", "repeats": "NOT_COMPARABLE"}]


def test_caveats_block_at_most_a_quarter_page(tmp_path, capsys, monkeypatch):
    common, _ = _analyzed(tmp_path, capsys, monkeypatch)
    n = json.loads((EXAMPLE / "narrative.json").read_text(encoding="utf-8"))
    n["caveats"] = [("Власне застереження агента без чисел, яке дуже довго пояснює одне й те саме. " * 4)[:250]] * 6
    (tmp_path / "n.json").write_text(json.dumps(n, ensure_ascii=False), encoding="utf-8")
    code = main([*common, "report", "--narrative", str(tmp_path / "n.json")], session=FakeSession(no_network))
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["error"]["code"] == "report_too_long" and "quarter" in out["error"]["message"]


def _render_error(m, text):
    from wiki_interest.errors import InputError
    from wiki_interest.report.narrative import render_narrative

    n = {"title": "T", "answer": text, "findings": ["f"], "recommendation": "r", "next_steps": [], "caveats": []}
    with pytest.raises(InputError) as ei:
        render_narrative(n, m, "en")
    return ei.value


def test_validator_hints_fix_haikus_mistakes_in_one_try(tmp_path, capsys, monkeypatch):
    """Haiku failed 12 of 14 report calls on scenario B guessing placeholders; each hint now gives
    the placeholder to use and the corrected sentence."""
    _, m = _metrics(tmp_path, capsys, monkeypatch)
    # the actual mistake from the run: "in 24 months" (the window length)
    e = _render_error(m, "Interest dropped in 24 months.")
    assert e.code == "bare_number" and "Use {spec.window.months:int}" in e.hint
    assert "Corrected: «Interest dropped in {spec.window.months:int} months.»" in e.hint
    # a typed percentage that is a metric: the headline placeholder is offered first
    pl = m["baskets"]["target"]["pl"]["window"]["change_norm"]
    typed = f"{round(pl * 100):d}%"
    e = _render_error(m, f"The stand-in fell {typed} in pl.")
    assert e.hint.startswith("Use {target.pl.window.change_norm:pct}. Corrected: «The stand-in fell {target.pl.window.change_norm:pct} in pl.»")
    # a guessed path: the closest real one
    e = _render_error(m, "Index {target.cs.window.index_norms:x}.")
    assert e.code == "unknown_placeholder" and e.hint.startswith("Use {target.cs.window.index_norm:x}.")
    # a wrong format: same path, right format
    e = _render_error(m, "Index {target.cs.window.index_norm:pct}.")
    assert e.hint.startswith("Use {target.cs.window.index_norm:x}. Corrected: «Index {target.cs.window.index_norm:x}.»")
    # a number with no metric behind it
    e = _render_error(m, "About 7 articles.")
    assert "No metric has this value" in e.hint


def test_schema_errors_show_a_minimal_valid_example(tmp_path):
    from wiki_interest.errors import InputError
    from wiki_interest.report.narrative import validate_narrative
    from wiki_interest.schemas import parse_analysis_spec

    with pytest.raises(InputError) as ei:
        validate_narrative({"title": "T", "answer": "A", "findings": ["f"], "recommendation": "r", "next_steps": [{"step": "x"}]})
    assert '"next_steps": ["first sentence", "second sentence"]' in ei.value.hint and "Minimal narrative.json" in ei.value.hint
    with pytest.raises(InputError) as ei:
        parse_analysis_spec({"langs": ["pl"], "baskets": []})
    assert ei.value.hint.startswith("Minimal analysis.json")


def test_out_pointing_at_a_folder_is_an_input_error(tmp_path, capsys, monkeypatch):
    common, _ = _analyzed(tmp_path, capsys, monkeypatch)
    (tmp_path / "out").mkdir()
    code = main([*common, "report", "--narrative", str(EXAMPLE / "narrative.json"), "--out", str(tmp_path / "out")],
                session=FakeSession(no_network))
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["error"]["code"] == "invalid_input" and "report.pdf" in out["error"]["hint"]

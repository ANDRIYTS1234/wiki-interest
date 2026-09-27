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
    assert "automatic flag lines" in out["error"]["hint"]
    assert pdf.read_bytes() == before

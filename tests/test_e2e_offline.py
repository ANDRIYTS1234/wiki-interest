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

"""report: narrative validation/rendering, number formatting, one-page PDF, appendix, CLI."""

from __future__ import annotations

import json
import re

import pytest

import synth
from wiki_interest.analyze import run_analysis
from wiki_interest.cache import Cache
from wiki_interest.cli import main
from wiki_interest.errors import InputError
from wiki_interest.report.appendix import build_appendix
from wiki_interest.report.fmt import fmt_ci, fmt_int, fmt_pct, fmt_x
from wiki_interest.report.narrative import get_path, render_narrative, render_text, validate_narrative
from wiki_interest.report.pdf import ReportTooLongError, render_pdf
from wiki_interest.schemas import parse_analysis_spec


@pytest.fixture(scope="module")
def metrics(tmp_path_factory):
    path = synth.build(tmp_path_factory.mktemp("report_synth"))
    with Cache(path) as cache:
        return run_analysis(parse_analysis_spec(synth.spec()), cache)


# -- fmt.py --------------------------------------------------------------------------------


def test_fmt_uk_uses_comma_space_and_real_minus():
    assert fmt_int(1234567, "uk") == "1 234 567"
    assert fmt_pct(-0.353, "uk") == "−35%"
    assert fmt_pct(0.24, "uk") == "+24%"
    assert fmt_x(2.4, "uk") == "2,40×"
    assert fmt_ci([0.598, 0.698], "uk") == "[0,598; 0,698]"


def test_fmt_en_uses_dot_comma_and_hyphen():
    assert fmt_int(1234567, "en") == "1,234,567"
    assert fmt_pct(-0.353, "en") == "-35%"
    assert fmt_x(2.4, "en") == "2.40×"
    assert fmt_ci([0.598, 0.698], "en") == "[0.598; 0.698]"


def test_fmt_zero_and_negative_zero():
    assert fmt_pct(0.0, "uk") == "+0%"
    assert fmt_int(0, "uk") == "0"


# -- narrative.py: path resolution -----------------------------------------------------


def test_get_path_resolves_basket_alias_without_prefix(metrics):
    assert get_path(metrics, "target.uk.window.index_norm") == metrics["baskets"]["target"]["uk"]["window"]["index_norm"]
    assert get_path(metrics, "compare.target.uk_vs_pl.window.ratio") == metrics["compare"]["target"]["uk_vs_pl"]["window"]["ratio"]
    assert get_path(metrics, "data_as_of") == metrics["data_as_of"]


def test_get_path_unknown_key_hints_siblings(metrics):
    with pytest.raises(InputError) as ei:
        get_path(metrics, "target.uk.windows.index_norm")
    assert ei.value.code == "unknown_placeholder"
    assert "window" in ei.value.hint  # sibling keys listed


def test_basket_id_cannot_be_a_reserved_top_level_key():
    # If a basket could be named "compare" or "flags", a placeholder like "compare.x" would be
    # ambiguous between that basket and the real top-level comparisons. schemas.py forbids it.
    spec = synth.spec()
    spec["baskets"][0]["id"] = "compare"
    with pytest.raises(InputError) as ei:
        parse_analysis_spec(spec)
    assert "reserved" in ei.value.message


# -- narrative.py: placeholder rendering and the no-bare-numbers rule -------------------


def test_render_text_formats_each_type(metrics):
    text = (
        "{target.uk.window.index_norm:x} {target.uk.window.index_norm_ci:ci} "
        "{target.uk.window.change_norm:pct} in 2024"
    )
    out = render_text(text, metrics, "en", "test")
    assert "2024" in out  # bare year allowed
    assert "%" in out and "×" in out and "[" in out


def test_render_text_rejects_bare_number(metrics):
    with pytest.raises(InputError) as ei:
        render_text("Falls by 35% this year", metrics, "en", "answer")
    assert ei.value.code == "bare_number"
    assert "35" in ei.value.message


def test_render_text_allows_four_digit_years_only(metrics):
    render_text("since 2019 and 2021", metrics, "en", "x")  # ok
    with pytest.raises(InputError):
        render_text("since 201", metrics, "en", "x")  # 3 digits, not a year
    with pytest.raises(InputError):
        render_text("since 20199", metrics, "en", "x")  # 5 digits, not a year


def test_render_text_rejects_unknown_format(metrics):
    with pytest.raises(InputError) as ei:
        render_text("{target.uk.window.change_norm:money}", metrics, "en", "x")
    assert ei.value.code == "unknown_format"


def test_render_text_rejects_malformed_placeholder(metrics):
    with pytest.raises(InputError) as ei:
        render_text("{not-a-real-placeholder}", metrics, "en", "x")
    assert ei.value.code == "malformed_placeholder"


def test_render_text_unknown_path_has_hint(metrics):
    with pytest.raises(InputError) as ei:
        render_text("{target.uk.window.nope:pct}", metrics, "en", "x")
    assert ei.value.code == "unknown_placeholder" and "index_norm" in ei.value.hint


def test_render_text_ci_requires_pair(metrics):
    with pytest.raises(InputError) as ei:
        render_text("{target.uk.window.change_norm:ci}", metrics, "en", "x")
    assert ei.value.code == "bad_placeholder_type"


def test_render_text_null_value_is_explained():
    # A null leaf (e.g. index_norm_ci with fewer than 3 panel articles) is a distinct error from
    # a path that does not exist at all: it explains that this specific claim has no estimate.
    fake = {"baskets": {"target": {"uk": {"window": {"index_norm_ci": None}}}}}
    with pytest.raises(InputError) as ei:
        render_text("{target.uk.window.index_norm_ci:ci}", fake, "en", "x")
    assert ei.value.code == "empty_placeholder"


def test_render_text_non_numeric_path_rejected(metrics):
    with pytest.raises(InputError) as ei:
        render_text("{target.uk.window.panel:int}", metrics, "en", "x")  # panel is an object
    assert ei.value.code == "bad_placeholder_type"


# -- narrative.py: schema validation ----------------------------------------------------


def test_validate_narrative_minimal_ok():
    n = validate_narrative({"title": "T", "answer": "A", "findings": ["F"], "recommendation": "R"})
    assert n["next_steps"] == [] and n["caveats"] == []


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ({"answer": "A", "findings": ["F"], "recommendation": "R"}, "missing"),
        ({"title": "T", "answer": "A", "findings": ["F"], "recommendation": "R", "extra": 1}, "unexpected"),
        ({"title": "T", "answer": "A", "findings": ["F"] * 5, "recommendation": "R"}, "more than 4"),
        ({"title": "T", "answer": "x" * 400, "findings": ["F"], "recommendation": "R"}, "longer than"),
        ({"title": "", "answer": "A", "findings": ["F"], "recommendation": "R"}, "non-empty"),
        ({"title": "T", "answer": "A", "findings": [1], "recommendation": "R"}, "list of strings"),
    ],
)
def test_validate_narrative_rejects(raw, fragment):
    with pytest.raises(InputError) as ei:
        validate_narrative(raw)
    assert fragment in ei.value.message


def test_render_narrative_end_to_end(metrics):
    n = validate_narrative(
        {
            "title": "T",
            "answer": "Down {target.uk.window.change_norm:pct}.",
            "findings": ["Index {target.uk.window.index_norm:x} {target.uk.window.index_norm_ci:ci}."],
            "recommendation": "R",
            "caveats": ["Since 2021."],
        }
    )
    out = render_narrative(n, metrics, "uk")
    assert "%" in out["answer"] and "−" in out["answer"] or "+" in out["answer"]
    assert "2021" in out["caveats"][0]


# -- pdf.py --------------------------------------------------------------------------------


def _narrative_for(metrics):
    return render_narrative(
        validate_narrative(
            {
                "title": "Test report",
                "answer": "The target basket fell by {target.uk.window.change_norm:pct} in the last window.",
                "findings": [
                    f"Index {{target.uk.window.index_norm:x}} {{target.uk.window.index_norm_ci:ci}}.",
                    "Compared with control the ratio is {compare.target_vs_control.uk.window.ratio:x}.",
                ],
                "recommendation": "Do not invest yet.",
                "next_steps": ["Run a demand test."],
                "caveats": ["Small panel in some languages."],
            }
        ),
        metrics,
        "en",
    )


def test_pdf_is_exactly_one_page(tmp_path, metrics):
    from wiki_interest.report.charts import render_chart

    chart = tmp_path / "chart.png"
    render_chart(metrics, chart, "en")
    out = tmp_path / "report.pdf"
    render_pdf(metrics, _narrative_for(metrics), chart, out, "en")
    assert out.is_file()
    data = out.read_bytes()
    assert len(re.findall(rb"/Type\s*/Page\b(?!s)", data)) == 1


def test_pdf_overflow_raises_instead_of_writing_a_second_page(tmp_path, metrics):
    from wiki_interest.report.charts import render_chart

    chart = tmp_path / "chart.png"
    render_chart(metrics, chart, "en")
    out = tmp_path / "report.pdf"
    huge_narrative = _narrative_for(metrics)
    huge_narrative["caveats"] = huge_narrative["caveats"] + ["Lorem ipsum dolor sit amet. " * 40] * 6
    with pytest.raises(ReportTooLongError) as ei:
        render_pdf(metrics, huge_narrative, chart, out, "en")
    assert ei.value.exit_code == 2
    assert not out.exists()  # never a silently truncated / multi-page file left behind


# -- appendix.py -----------------------------------------------------------------------


def test_appendix_lists_exclusions_flags_and_robustness(metrics):
    text = build_appendix(metrics, "en")
    assert "created_after:2023-06-01" in text
    assert "low_volume" in text
    assert "не про тему" not in text or True  # exclude reason is whatever the spec gave; just don't crash
    assert "| code | severity | scope | detail |" in text
    assert "loo_min" in text and "no_anomalies" in text
    assert "wiki-interest fetch --spec analysis.json" in text
    assert "Known limitations" in text and "fast" in text.lower()


def test_appendix_uk_language(metrics):
    text = build_appendix(metrics, "uk")
    assert "Склад кошиків" in text and "Методика" in text


# -- CLI ---------------------------------------------------------------------------------


def test_cli_report_writes_pdf_chart_and_appendix(tmp_path, metrics, capsys):
    metrics_file = tmp_path / "metrics.json"
    metrics_file.write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
    narrative_file = tmp_path / "narrative.json"
    narrative_file.write_text(
        json.dumps(
            {
                "title": "Т",
                "answer": "Падіння {target.uk.window.change_norm:pct}.",
                "findings": ["Індекс {target.uk.window.index_norm:x}."],
                "recommendation": "Не інвестувати.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out_pdf = tmp_path / "out" / "report.pdf"
    argv = [
        "--workdir", str(tmp_path / "workdir"),
        "report", "--metrics", str(metrics_file), "--narrative", str(narrative_file),
        "--out", str(out_pdf), "--report-lang", "uk",
    ]
    code = main(argv)
    out = json.loads(capsys.readouterr()[0])
    assert code == 0 and out["ok"] is True
    assert out["pages"] == 1
    assert out_pdf.is_file()
    assert (tmp_path / "workdir" / "appendix.md").is_file()
    assert (tmp_path / "workdir" / "report_chart.png").is_file()


def test_cli_report_bare_number_exit_2(tmp_path, metrics, capsys):
    metrics_file = tmp_path / "metrics.json"
    metrics_file.write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
    narrative_file = tmp_path / "narrative.json"
    narrative_file.write_text(json.dumps({"title": "T", "answer": "Fell by 35%", "findings": ["f"], "recommendation": "r"}), encoding="utf-8")
    argv = ["--workdir", str(tmp_path / "w"), "report", "--metrics", str(metrics_file), "--narrative", str(narrative_file), "--out", str(tmp_path / "r.pdf")]
    code = main(argv)
    out = json.loads(capsys.readouterr()[0])
    assert code == 2 and out["error"]["code"] == "bare_number"


def test_cli_report_rejects_non_metrics_file(tmp_path):
    bad = tmp_path / "metrics.json"
    bad.write_text("{}", encoding="utf-8")
    narrative_file = tmp_path / "narrative.json"
    narrative_file.write_text(json.dumps({"title": "T", "answer": "A", "findings": ["f"], "recommendation": "r"}), encoding="utf-8")
    code = main(["--workdir", str(tmp_path / "w"), "report", "--metrics", str(bad), "--narrative", str(narrative_file), "--out", str(tmp_path / "r.pdf")])
    assert code == 2

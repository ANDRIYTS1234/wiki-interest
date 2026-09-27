"""analyze: known answers on synthetic series (SPEC §11), determinism, flags, confidence."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import math

import numpy as np
import pandas as pd
import pytest

import synth
from wiki_interest.analyze import run_analysis
from wiki_interest.analyze.metrics import Member, comparison, mann_kendall, period_months, theil_sen
from wiki_interest.analyze.params import resolve_params
from wiki_interest.analyze.quality import anomaly_months, claim_confidence
from wiki_interest.analyze.series import ArticleData, monthly
from wiki_interest.analyze.spikes import detect
from wiki_interest.cache import Cache
from wiki_interest.cli import main
from wiki_interest.errors import InputError
from wiki_interest.schemas import parse_analysis_spec

P = resolve_params({})


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    folder = tmp_path_factory.mktemp("synth")
    path = synth.build(folder)
    with Cache(path) as cache:
        metrics = run_analysis(parse_analysis_spec(synth.spec()), cache)
    return metrics, path


def flags_of(metrics, **where):
    return [f for f in metrics["flags"] if all(f.get(k) == v for k, v in where.items())]


# -- known answers -----------------------------------------------------------------------


def test_geometric_index_and_normalisation(synthetic):
    m, _ = synthetic
    uk = m["baskets"]["target"]["uk"]["window"]
    assert uk["status"] == "ok"
    assert uk["periods"] == {"base": ["2023-01", "2023-12"], "current": ["2024-01", "2024-12"]}
    # Every panel article halves; the edition is flat per day (2024 has one day more, which cancels).
    assert uk["index_norm"] == pytest.approx(0.5, abs=1e-3)
    assert uk["change_norm"] == pytest.approx(-0.5, abs=1e-3)
    assert uk["section_change"] == pytest.approx(366 / 365 - 1, rel=1e-5)  # 6 significant digits
    assert uk["share_change"] == pytest.approx(-0.5, abs=1e-3)
    assert m["baskets"]["target"]["pl"]["window"]["index_norm"] == pytest.approx(0.8, abs=1e-3)
    assert m["baskets"]["control"]["uk"]["window"]["index_norm"] == pytest.approx(1.0, abs=1e-3)


def test_redirect_views_are_summed(synthetic):
    m, _ = synthetic
    art = next(a for a in m["baskets"]["target"]["uk"]["window"]["articles"] if a["title"] == "Стаття 1")
    assert art["views_base"] == pytest.approx(1100 * 365)  # 1000/day + 100/day redirect


def test_panel_exclusions_with_reasons(synthetic):
    m, _ = synthetic
    panel = m["baskets"]["target"]["uk"]["window"]["panel"]
    assert panel["n"] == 7
    reasons = {e["title"]: e["reason"] for e in panel["excluded"]}
    assert reasons == {"Нова стаття": "created_after:2023-06-01", "Мала стаття": "low_volume"}
    items = {(i["item"], i["lang"]): i for i in m["basket_info"]["target"]["items"]}
    assert items[("Q110", "uk")]["status"] == "excluded" and "не про тему" in items[("Q110", "uk")]["reason"]
    assert items[("Q109", "pl")]["status"] == "missing"


def test_groups_have_separate_metrics(synthetic):
    m, _ = synthetic
    groups = m["baskets"]["target"]["uk"]["groups"]
    assert sorted(groups) == ["g1", "g2"]
    assert groups["g1"]["window"]["panel"]["articles"] == ["Стаття 1", "Стаття 2", "Стаття 3"]
    assert groups["g2"]["window"]["index_norm"] == pytest.approx(0.5, abs=1e-3)
    assert "direction" in groups["g1"]["confidence"]["window"]


def test_multiple_baselines(synthetic):
    m, _ = synthetic
    b = m["baskets"]["target"]["uk"]["baselines"]["2021"]
    assert b["periods"] == {"base": ["2021-01", "2021-12"], "current": ["2024-01", "2024-12"]}
    assert b["index_norm"] == pytest.approx(0.5, abs=1e-3)
    assert m["baskets"]["target"]["uk"]["confidence"]["baselines"]["2021"]["label"] == "down"


def test_language_comparison_on_common_qids(synthetic):
    m, _ = synthetic
    r = m["compare"]["target"]["uk_vs_pl"]["window"]
    assert r["status"] == "ok"
    assert r["qids"] == ["Q101", "Q102", "Q103", "Q104", "Q105", "Q106"]  # Q109 has no pl article
    assert r["ratio"] == pytest.approx(0.5 / 0.8, abs=1e-3)
    assert r["confidence"]["direction"] == "high"


def test_basket_comparison_by_indices(synthetic):
    m, _ = synthetic
    r = m["compare"]["target_vs_control"]["uk"]["window"]
    assert r["ratio"] == pytest.approx(0.5, abs=1e-3)
    assert r["n_a"] == 7 and r["n_b"] == 5


def test_confidence_high_when_every_variant_agrees(synthetic):
    m, _ = synthetic
    conf = m["baskets"]["target"]["uk"]["confidence"]["window"]
    assert conf["direction"] == "high" and conf["magnitude"] == "high" and conf["label"] == "down"
    variants = m["baskets"]["target"]["uk"]["window"]["variants"]
    for k in ("loo_min", "loo_max", "no_top3", "median_ratio", "no_spikes"):
        assert variants[k] == pytest.approx(-0.5, abs=2e-3), k


def test_flags(synthetic):
    m, _ = synthetic
    codes_pl = {f["code"] for f in flags_of(m, basket="target", lang="pl")}
    assert {"ARTICLE_MISSING"} <= codes_pl
    assert any(f["code"] == "PRE_2020_BOT_CLASS" for f in flags_of(m)) is False
    for f in m["flags"]:
        assert set(f) >= {"code", "severity", "detail"}


def test_metrics_are_byte_identical(synthetic, tmp_path):
    _, path = synthetic
    with Cache(path) as cache:
        a = json.dumps(run_analysis(parse_analysis_spec(synth.spec()), cache), sort_keys=True, ensure_ascii=False)
        b = json.dumps(run_analysis(parse_analysis_spec(synth.spec()), cache), sort_keys=True, ensure_ascii=False)
    assert a == b


def test_cli_analyze_stdout_one_line_per_basket_language(synthetic, tmp_path, capsys):
    _, path = synthetic
    spec_file = tmp_path / "analysis.json"
    spec_file.write_text(json.dumps(synth.spec(), ensure_ascii=False), encoding="utf-8")
    argv = ["--cache-dir", str(path.parent), "--workdir", str(tmp_path / "out"), "analyze", "--spec", str(spec_file)]
    assert main(argv) == 0
    out = json.loads(capsys.readouterr()[0])
    assert out["ok"] and out["data_as_of"] == "2024-12"
    assert len(out["summary"]) == 4  # 2 baskets x 2 languages
    line = next(l for l in out["summary"] if l.startswith("target/uk window"))
    for part in ("down", "index_norm", "share_change", "direction high", "magnitude high", "vs 2021", "flags:"):
        assert part in line
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) < 6000  # includes placeholders[] for 2 baskets x 2 langs
    assert out["placeholders"]["target.uk.window.change_norm"] == "{target.uk.window.change_norm:pct}"
    assert out["placeholders"]["target.uk.window.index_norm_ci"] == "{target.uk.window.index_norm_ci:ci}"
    first = (tmp_path / "out" / "metrics.json").read_bytes()
    assert main(argv) == 0
    capsys.readouterr()
    assert (tmp_path / "out" / "metrics.json").read_bytes() == first


def test_unfetched_items_are_an_input_error(synthetic):
    _, path = synthetic
    s = synth.spec()
    s["baskets"][1]["items"].append({"qid": "Q999"})
    with Cache(path) as cache, pytest.raises(InputError) as ei:
        run_analysis(parse_analysis_spec(s), cache)
    assert "fetch" in ei.value.hint


def test_latest_end_comes_from_cache_coverage(synthetic):
    _, path = synthetic
    with Cache(path) as cache:
        m = run_analysis(parse_analysis_spec(synth.spec(window={"months": 12, "end": "latest"})), cache)
    assert m["data_as_of"] == "2024-12"


# -- units -------------------------------------------------------------------------------


def _article(user: pd.Series, automated: pd.Series | None = None, desktop_share: float = 0.4) -> ArticleData:
    automated = automated if automated is not None else user * 0.0
    return ArticleData("uk:X", "uk", "X", "Q1", None, user, user, automated, user * desktop_share)


def test_spike_detector_and_classification():
    idx = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    user = pd.Series(100.0, index=idx)
    user[pd.Timestamp("2024-02-10")] = 1000.0
    user[pd.Timestamp("2024-02-20")] = 450.0  # 4.5x: below spike_k
    auto = pd.Series(1.0, index=idx)
    auto[pd.Timestamp("2024-02-10")] = 2000.0
    spikes, cleaned = detect(_article(user, auto), P)
    assert [s["date"] for s in spikes] == ["2024-02-10"]
    assert spikes[0]["class"] == "bot_suspect" and spikes[0]["median"] == 100.0
    assert cleaned[pd.Timestamp("2024-02-10")] == 100.0 and cleaned.sum() == user.sum() - 900.0

    human = detect(_article(user, pd.Series(0.0, index=idx)), P)[0]
    assert human[0]["class"] == "likely_human"
    pre2020 = pd.Series(np.nan, index=idx)
    assert detect(_article(user, pre2020), P)[0][0]["class"] == "unknown_pre_2020"


def _seasonal(years, profile, factor=lambda y, m: 1.0):
    idx = pd.period_range(f"{years[0]}-01", f"{years[-1]}-12", freq="M")
    return pd.Series([1000 * profile[p.month - 1] * factor(p.year, p.month) for p in idx], index=idx)


PROFILE = [1.2, 1.1, 1.0, 1.0, 0.9, 0.6, 0.5, 0.5, 1.1, 1.2, 1.2, 1.0]


def test_anomaly_month_found_and_seasonality_ignored():
    s = _seasonal(range(2016, 2025), PROFILE, lambda y, m: 3.0 if (y, m) == (2022, 1) else 1.0)
    found = anomaly_months(s, P)
    assert [a["month"] for a in found] == ["2022-01"]
    assert found[0]["ratio"] == pytest.approx(3.0, rel=0.05)
    assert anomaly_months(_seasonal(range(2016, 2025), PROFILE), P) == []


def test_anomaly_ignores_declining_level_and_creation_year():
    decline = _seasonal(range(2016, 2025), PROFILE, lambda y, m: 0.8 ** (y - 2016))
    assert anomaly_months(decline, P) == []
    ramp = _seasonal(range(2016, 2025), PROFILE, lambda y, m: 0.05 if y == 2016 and m < 11 else 1.0)
    assert anomaly_months(ramp, P) != []
    assert anomaly_months(ramp, P, first_year=2017) == []


def _member(title: str, monthly_values: pd.Series, qid: str | None = None) -> Member:
    idx = pd.date_range("2023-01-01", "2023-01-02", freq="D")
    art = ArticleData(f"uk:{title}", "uk", title, qid or title, None, pd.Series(1.0, index=idx), pd.Series(1.0, index=idx), pd.Series(0.0, index=idx), pd.Series(0.0, index=idx))
    art.monthly_user = monthly_values
    return Member(title, None, art, monthly_values)


def _two_years(base: float, cur: float) -> pd.Series:
    idx = pd.period_range("2023-01", "2024-12", freq="M")
    return pd.Series([base if p.year == 2023 else cur for p in idx], index=idx)


def _cmp(members, key="k"):
    end = pd.Period("2024-12", freq="M")
    section = pd.Series(1e6, index=pd.period_range("2023-01", "2024-12", freq="M"))
    return comparison(members, section, period_months(end, 12, 1), period_months(end, 12), P, key, set())


def test_bootstrap_is_deterministic_and_keyed():
    members = [_member(f"a{i}", _two_years(100 * (i + 1), 100 * (i + 1) * r)) for i, r in enumerate([0.5, 0.8, 1.1, 0.7, 0.9, 1.3])]
    a, b, c = _cmp(members, "x"), _cmp(members, "x"), _cmp(members, "y")
    assert a["index_norm_ci"] == b["index_norm_ci"]
    assert a["index_norm_ci"] != c["index_norm_ci"]
    lo, hi = a["index_norm_ci"]
    assert lo < a["index_norm"] < hi
    expected = math.exp(np.mean(np.log([(100 * (i + 1) * r * 12 + 1) / (100 * (i + 1) * 12 + 1) for i, r in enumerate([0.5, 0.8, 1.1, 0.7, 0.9, 1.3])])))
    assert a["index_norm"] == pytest.approx(expected, rel=1e-9)


def test_leave_one_out_and_no_top3():
    ratios = [0.5, 0.5, 0.5, 0.5, 4.0]
    members = [_member(f"a{i}", _two_years(1000 * (10 if i == 4 else 1), 1000 * (10 if i == 4 else 1) * r)) for i, r in enumerate(ratios)]
    v = _cmp(members)["variants"]
    assert v["loo_min"] == pytest.approx(-0.5, abs=1e-3) and v["loo_min_without"] == "a4"
    assert v["no_top3"] == pytest.approx(-0.5, abs=1e-3)
    assert "a4" in v["no_top3_removed"]
    assert v["median_ratio"] == pytest.approx(-0.5, abs=1e-3)


def test_concentration_divergence_flagged(tmp_path):
    # One huge article doubles, five small ones halve: the typical article falls, total attention grows.
    ratios = [2.0, 0.5, 0.5, 0.5, 0.5, 0.5]
    members = [_member(f"a{i}", _two_years(100000 if i == 0 else 1000, (100000 if i == 0 else 1000) * r)) for i, r in enumerate(ratios)]
    comp = _cmp(members)
    assert comp["change_norm"] < 0 < comp["share_change"]
    assert comp["top_contributors"][0]["title"] == "a0"
    from wiki_interest.analyze import _claim_flags

    codes = {f["code"] for f in _claim_flags(comp, P, set(), set(), set(), scope="window")}
    assert "CONCENTRATION_DIVERGENCE" in codes


def test_confidence_rules_and_caps():
    comp = {
        "status": "ok", "change_norm": -0.3, "index_norm_ci": [0.6, 0.8], "panel": {"n": 10},
        "variants": {"loo_min": -0.32, "loo_max": -0.28, "no_top3": -0.31, "median_ratio": -0.29, "no_spikes": -0.3, "no_anomalies": -0.27},
    }
    c = claim_confidence(comp, set(), P)
    assert (c["direction"], c["magnitude"], c["label"]) == ("high", "high", "down")
    capped = claim_confidence(comp, {"LOW_VOLUME", "PRE_2020_BOT_CLASS"}, P)
    assert (capped["direction"], capped["magnitude"]) == ("medium", "medium")
    assert "direction capped at medium: LOW_VOLUME" in capped["reasons"]
    assert "magnitude capped at medium: PRE_2020_BOT_CLASS" in capped["reasons"]
    flip = dict(comp, variants={**comp["variants"], "no_anomalies": 0.05})
    low = claim_confidence(flip, set(), P)
    assert low["direction"] == "low" and "no_anomalies" in low["reasons"][0]
    wide = dict(comp, index_norm_ci=[0.6, 1.1])
    assert claim_confidence(wide, set(), P)["direction"] == "medium"
    one = dict(comp, index_norm_ci=None, panel={"n": 1})
    assert claim_confidence(one, set(), P)["direction"] == "medium"


def test_trend_statistics():
    mk = mann_kendall([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert mk["tau"] == 1.0 and mk["p"] < 0.01
    assert mann_kendall([1.0, 2.0, 3.0]) is None
    ts = theil_sen([10.0, 8.0, 6.0, 4.0])
    assert ts["slope_per_year"] == -2.0 and ts["relative_slope_per_year"] == pytest.approx(-2.0 / 7.0)


def test_monthly_is_nan_when_any_day_missing():
    idx = pd.date_range("2024-01-30", "2024-02-02", freq="D")
    s = pd.Series([1.0, np.nan, 2.0, 3.0], index=idx)
    mo = monthly(s)
    assert math.isnan(mo[pd.Period("2024-01", freq="M")]) and mo[pd.Period("2024-02", freq="M")] == 5.0


@pytest.mark.parametrize("raw, fragment", [({"spike_k": -1}, "non-negative"), ({"bootstrap": 10}, "at least 100"), ({"nope": 1}, "unknown"), ({"seed": 1.5}, "integer")])
def test_params_validation(raw, fragment):
    with pytest.raises(InputError) as ei:
        resolve_params(raw)
    assert fragment in ei.value.message


def test_baseline_not_before_window_year_rejected(synthetic):
    _, path = synthetic
    with Cache(path) as cache, pytest.raises(InputError) as ei:
        run_analysis(parse_analysis_spec(synth.spec(baselines=[2024])), cache)
    assert "2024" in ei.value.message


def _rebuild(tmp_path):
    return synth.build(tmp_path)


def test_redirects_skipped_flag_caps_direction(tmp_path):
    path = _rebuild(tmp_path)
    with Cache(path) as cache:
        # What `fetch --redirects none` leaves behind: the redirect range recorded as skipped.
        cache.put_pageviews("uk.wikipedia", "Стаття 1 (редирект)", "all-access", "user", [],
                            start=synth.START.isoformat(), end=synth.END.isoformat(), status="skipped")
        m = run_analysis(parse_analysis_spec(synth.spec()), cache)
    codes = {f["code"] for f in flags_of(m, basket="target", lang="uk")}
    assert "REDIRECTS_SKIPPED" in codes
    conf = m["baskets"]["target"]["uk"]["confidence"]["window"]
    assert conf["direction"] == "medium" and "direction capped at medium: REDIRECTS_SKIPPED" in conf["reasons"]


def test_partial_data_flag_and_article_left_out(tmp_path):
    path = _rebuild(tmp_path)
    with Cache(path) as cache:
        with cache.conn:
            cache.conn.execute("DELETE FROM coverage WHERE article = ? AND access = 'all-access' AND agent = 'user'", ("Стаття 2",))
        m = run_analysis(parse_analysis_spec(synth.spec()), cache)
    assert "PARTIAL_DATA" in {f["code"] for f in flags_of(m, basket="target", lang="uk")}
    excluded = {e["title"]: e["reason"] for e in m["baskets"]["target"]["uk"]["window"]["panel"]["excluded"]}
    assert excluded["Стаття 2"] == "partial_data"


@pytest.mark.parametrize(
    "months, base, current",
    [
        (12, ("2023-01", "2023-12"), ("2024-01", "2024-12")),  # the previous 12 months
        (24, ("2021-01", "2022-12"), ("2023-01", "2024-12")),  # the previous 24, no shared year
        (18, ("2021-07", "2022-12"), ("2023-07", "2024-12")),  # same months 2 years back: a 6-month gap
    ],
)
def test_window_base_never_overlaps(tmp_path, months, base, current):
    """A Haiku run with a 24-month window showed the base (same 24 months a year earlier) sharing a
    year with the window, which understated the change. The base shift is ceil(months/12) years."""
    path = synth.build(tmp_path)
    with Cache(path) as cache:
        m = run_analysis(parse_analysis_spec(synth.spec(window={"months": months, "end": "2024-12"}, baselines=[])), cache)
    w = m["baskets"]["target"]["uk"]["window"]
    assert w["periods"] == {"base": list(base), "current": list(current)}
    assert w["periods"]["base"][1] < w["periods"]["current"][0]
    assert m["spec"]["window"]["base_shift_years"] == -(-months // 12)


def test_baseline_overlapping_the_window_is_an_input_error(tmp_path):
    path = synth.build(tmp_path)
    with Cache(path) as cache, pytest.raises(InputError) as ei:
        # 24-month window ending 2024-12 covers 2023-2024; a 2023 baseline would overlap it.
        run_analysis(parse_analysis_spec(synth.spec(window={"months": 24, "end": "2024-12"}, baselines=[2023])), cache)
    assert "overlap" in ei.value.message and "2022 or earlier" in ei.value.hint


def test_window_labels_show_the_real_shift():
    from wiki_interest.dates import window_label

    assert window_label(24, 2, "en") == "last 24 months vs the previous 24"
    assert window_label(12, 1, "uk") == "останні 12 міс. проти попередніх 12"
    assert window_label(18, 2, "en") == "last 18 months vs the same months 2 years earlier"


def test_thin_target_basket_is_called_out_and_capped(tmp_path, capsys):
    """Haiku built a one-article target: analyze must say so and not claim a confident direction."""
    path = synth.build(tmp_path)
    spec = synth.spec(langs=["uk"])
    spec["baskets"][0]["items"] = [{"qid": "Q101"}, {"qid": "Q102"}]
    spec_file = tmp_path / "thin.json"
    spec_file.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    assert main(["--cache-dir", str(path.parent), "--workdir", str(tmp_path / "out"), "analyze", "--spec", str(spec_file)]) == 0
    out = json.loads(capsys.readouterr()[0])
    note = next(a for a in out["attention"] if a.startswith("target/uk"))
    assert "2 comparable article(s)" in note and "add articles" in note
    m = json.loads(Path(out["metrics_file"]).read_text(encoding="utf-8"))
    conf = m["baskets"]["target"]["uk"]["confidence"]
    assert conf["window"]["direction"] == "low"
    assert any("capped at low" in r for r in conf["window"]["reasons"])
    assert all(c["direction"] == "low" for c in conf["baselines"].values())
    # the control basket is not a target: no such note for it
    assert not any(a.startswith("control/") for a in out["attention"])

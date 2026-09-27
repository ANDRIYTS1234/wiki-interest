"""Core metrics: panels, basket indices with bootstrap intervals, sums and shares, comparisons,
long history and trend. Pure functions over monthly pandas series.

Definitions (also in the appendix):
- A comparison sets a current period against a base period of the same calendar months
  (the window a year earlier, or the same months of a baseline year), so seasonality cancels.
- Panel: basket articles that existed before the base period started, have complete data in
  both periods and at least `min_monthly_views` on average in the base period.
- index: geometric mean over panel articles of (current + 1) / (base + 1).
- index_norm: index divided by the same ratio for the whole language edition (user views), i.e.
  the change of the typical article's share of the edition's traffic. change_norm = index_norm - 1.
- share_change: change of the panel's summed share of the edition's traffic (total attention).
- 95% interval: bootstrap over panel articles, fixed seed per claim.
"""

from __future__ import annotations

import math
import zlib
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .robustness import index_norm_of, variants
from .series import ArticleData, period_sum

M = pd.Period
MIN_CI_ARTICLES = 3  # bootstrap intervals need at least this many panel articles


def period_months(end: M, n: int, shift_years: int = 0) -> list[M]:
    last = end - 12 * shift_years
    return [last - i for i in range(n - 1, -1, -1)]


def months_label(months: list[M]) -> list[str]:
    return [str(months[0]), str(months[-1])]


def rng_for(seed: int, key: str) -> np.random.Generator:
    return np.random.default_rng([int(seed), zlib.crc32(key.encode("utf-8"))])


def bootstrap_means(logs: np.ndarray, rng: np.random.Generator, b: int) -> np.ndarray:
    idx = rng.integers(0, len(logs), size=(b, len(logs)))
    return logs[idx].mean(axis=1)


def sign(x: float | None, flat: float) -> int:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0
    return 0 if abs(x) < flat else (1 if x > 0 else -1)


class Member:
    """An article taking part in a comparison, with its monthly series and variant series."""

    def __init__(self, cand_item: str, group: str | None, art: ArticleData, monthly_nospikes: pd.Series):
        self.item = cand_item
        self.group = group
        self.art = art
        self.monthly = art.monthly_user
        self.monthly_nospikes = monthly_nospikes


def select_panel(
    members: list[Member], base: list[M], cur: list[M], params: dict[str, Any]
) -> tuple[list[tuple[Member, float, float]], list[dict[str, Any]]]:
    base_start = base[0].start_time.date()
    panel, excluded = [], []
    for m in members:
        info = {"item": m.item, "title": m.art.title, "qid": m.art.qid}
        if m.art.created and m.art.created > base_start:
            excluded.append({**info, "reason": f"created_after:{m.art.created.isoformat()}"})
            continue
        vb, vc = period_sum(m.monthly, base), period_sum(m.monthly, cur)
        if math.isnan(vb) or math.isnan(vc):
            excluded.append({**info, "reason": "partial_data"})
            continue
        if vb / len(base) < params["min_monthly_views"]:
            excluded.append({**info, "reason": "low_volume"})
            continue
        panel.append((m, vb, vc))
    return panel, excluded


def comparison(
    members: list[Member],
    section: pd.Series,
    base: list[M],
    cur: list[M],
    params: dict[str, Any],
    key: str,
    anomaly_months: set[M],
) -> dict[str, Any]:
    """All numbers for one claim: current period vs base period for a basket (or group) in one language."""
    panel, excluded = select_panel(members, base, cur, params)
    out: dict[str, Any] = {
        "periods": {"current": months_label(cur), "base": months_label(base)},
        "panel": {
            "n": len(panel),
            "articles": sorted(m.art.title for m, _, _ in panel),
            "excluded": sorted(excluded, key=lambda e: (e["reason"], e["title"])),
        },
    }
    sb, sc = period_sum(section, base), period_sum(section, cur)
    if math.isnan(sb) or math.isnan(sc) or sb <= 0:
        out["status"] = "no_section_data"
        return out
    if not panel:
        out["status"] = "empty_panel"
        return out
    out["status"] = "ok"
    section_ratio = sc / sb
    vb = np.array([p[1] for p in panel])
    vc = np.array([p[2] for p in panel])
    logs = np.log((vc + 1.0) / (vb + 1.0))
    index = float(np.exp(logs.mean()))
    index_norm = index / section_ratio

    if len(logs) >= MIN_CI_ARTICLES:
        means = bootstrap_means(logs, rng_for(params["seed"], key), int(params["bootstrap"]))
        lo, hi = (float(np.exp(q)) / section_ratio for q in np.quantile(means, [0.025, 0.975]))
        ci, change_ci = [lo, hi], [lo - 1, hi - 1]
    else:
        ci = change_ci = None  # resampling one or two articles gives no meaningful interval

    views_b, views_c = float(vb.sum()), float(vc.sum())
    share_b, share_c = views_b / sb * 1e6, views_c / sc * 1e6
    share_change = share_c / share_b - 1 if share_b > 0 else None
    monthly_sum = sum(m.monthly for m, _, _ in panel)
    med = lambda ms: float(monthly_sum.reindex(pd.PeriodIndex(ms, freq="M")).median())  # noqa: E731

    articles = []
    for (m, b, c), lg in zip(panel, logs):
        contribution = (c / sc - b / sb) / (views_b / sb) if views_b > 0 else None
        articles.append(
            {
                "item": m.item,
                "title": m.art.title,
                "qid": m.art.qid,
                "group": m.group,
                "views_base": b,
                "views_current": c,
                "ratio_norm": float(np.exp(lg)) / section_ratio,
                "contribution_to_share_change": contribution,
            }
        )
    articles.sort(key=lambda a: (-a["views_base"], a["title"]))

    out.update(
        {
            "views_base": views_b,
            "views_current": views_c,
            "change_abs": views_c / views_b - 1 if views_b > 0 else None,
            "section_change": section_ratio - 1,
            "share_base_per_million": share_b,
            "share_current_per_million": share_c,
            "share_change": share_change,
            "median_month_base": med(base),
            "median_month_current": med(cur),
            "index": index,
            "index_norm": index_norm,
            "index_norm_ci": ci,
            "change_norm": index_norm - 1,
            "change_norm_ci": change_ci,
            "articles": articles,
            "top_contributors": sorted(
                (a for a in articles if a["contribution_to_share_change"] is not None),
                key=lambda a: (-abs(a["contribution_to_share_change"]), a["title"]),
            )[:3],
        }
    )
    out["variants"] = variants(panel, section, base, cur, section_ratio, index_norm, anomaly_months)
    out["_logs"] = logs  # used by comparisons between languages/baskets; removed before writing
    out["_section_ratio"] = section_ratio
    out["_qids"] = [m.art.qid for m, _, _ in panel]
    return out


def ratio_of_indices(a: dict[str, Any], b: dict[str, Any], params: dict[str, Any], key: str, paired_qids: bool) -> dict[str, Any]:
    """index_norm(a) / index_norm(b) with a bootstrap interval.

    paired_qids=True (languages): only QIDs present in both panels, resampled jointly.
    paired_qids=False (baskets): independent resampling of each panel.
    """
    if a.get("status") != "ok" or b.get("status") != "ok":
        return {"status": "not_comparable"}
    rng = rng_for(params["seed"], key)
    reps = int(params["bootstrap"])
    if paired_qids:
        qa = {q: l for q, l in zip(a["_qids"], a["_logs"]) if q}
        qb = {q: l for q, l in zip(b["_qids"], b["_logs"]) if q}
        common = sorted(set(qa) & set(qb))
        if not common:
            return {"status": "no_common_articles", "n_common": 0}
        la, lb = np.array([qa[q] for q in common]), np.array([qb[q] for q in common])
        diff = la - lb
        point = float(np.exp(diff.mean())) * b["_section_ratio"] / a["_section_ratio"]
        means = bootstrap_means(diff, rng, reps)
        lo, hi = (float(np.exp(q)) * b["_section_ratio"] / a["_section_ratio"] for q in np.quantile(means, [0.025, 0.975]))
        return {"status": "ok", "ratio": point, "ratio_ci": [lo, hi], "n_common": len(common), "qids": common}
    ma = bootstrap_means(a["_logs"], rng, reps) - math.log(a["_section_ratio"])
    mb = bootstrap_means(b["_logs"], rng, reps) - math.log(b["_section_ratio"])
    lo, hi = (float(np.exp(q)) for q in np.quantile(ma - mb, [0.025, 0.975]))
    return {
        "status": "ok",
        "ratio": a["index_norm"] / b["index_norm"],
        "ratio_ci": [lo, hi],
        "n_a": a["panel"]["n"],
        "n_b": b["panel"]["n"],
    }


# -- long history ------------------------------------------------------------------------


def mann_kendall(x: list[float]) -> dict[str, float] | None:
    n = len(x)
    if n < 4:
        return None
    s = sum(np.sign(x[j] - x[i]) for i in range(n - 1) for j in range(i + 1, n))
    _, counts = np.unique(np.round(x, 12), return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in counts)) / 18.0
    z = 0.0 if s == 0 else (s - np.sign(s)) / math.sqrt(var)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return {"s": float(s), "tau": float(s) / (n * (n - 1) / 2), "z": float(z), "p": float(p)}


def theil_sen(x: list[float]) -> dict[str, float] | None:
    n = len(x)
    if n < 3:
        return None
    slopes = [(x[j] - x[i]) / (j - i) for i in range(n - 1) for j in range(i + 1, n)]
    slope = float(np.median(slopes))
    level = float(np.median(x))
    return {"slope_per_year": slope, "relative_slope_per_year": slope / level if level else None}


def history(
    members: list[Member], section: pd.Series, end: M, first_month: M, history_start: M
) -> dict[str, Any]:
    """12-month blocks ending in the data_as_of month each year, as share per million of the edition."""
    blocks = []
    k = 0
    while True:
        months = period_months(end, 12, k)
        if months[0] < first_month:
            break
        blocks.append(months)
        k += 1
    blocks.reverse()
    values: dict[str, Any] = {}
    series = []
    total = sum(m.monthly for m in members) if members else None
    created = [m.art.created for m in members if m.art.created]
    latest_created = max(created) if created else None
    for months in blocks:
        label = str(months[-1].year)
        sv = period_sum(section, months)
        tv = period_sum(total, months) if total is not None else float("nan")
        v = None if math.isnan(sv) or math.isnan(tv) or sv <= 0 else tv / sv * 1e6
        exist = latest_created is None or months[0].start_time.date() >= latest_created
        values[label] = {"months": months_label(months), "share_per_million": v, "all_articles_exist": exist}
        series.append((label, months[0], v))

    base_label = None
    for label, start, v in series:
        if v is not None and (latest_created is None or start.start_time.date() >= latest_created):
            base_label = label
            break
    trend_part = [(l, v) for l, s, v in series if base_label and l >= base_label and v is not None]
    out: dict[str, Any] = {
        "block_end_month": str(end),
        "blocks": values,
        "base_year": base_label,
        "base_year_rule": "first 12-month block that starts after every basket article was created",
        "new_articles": sorted(
            ({"title": m.art.title, "created": m.art.created.isoformat()} for m in members if m.art.created and m.art.created > history_start.start_time.date()),
            key=lambda a: (a["created"], a["title"]),
        ),
    }
    if trend_part:
        vals = [v for _, v in trend_part]
        peak_i = int(np.argmax(vals))
        out.update(
            {
                "peak_year": trend_part[peak_i][0],
                "current_pct_of_peak": vals[-1] / vals[peak_i] if vals[peak_i] else None,
                "mann_kendall": mann_kendall(vals),
                "theil_sen": theil_sen(vals),
            }
        )
    return out


def seasonality(monthly_total: pd.Series) -> dict[str, Any]:
    """Mean share of each calendar month in complete calendar years."""
    shares: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    years = []
    for year in sorted({p.year for p in monthly_total.index}):
        months = [M(f"{year}-{m:02d}", freq="M") for m in range(1, 13)]
        vals = monthly_total.reindex(pd.PeriodIndex(months, freq="M"))
        if vals.isna().any() or vals.sum() <= 0:
            continue
        years.append(year)
        for m, v in zip(range(1, 13), vals):
            shares[m].append(float(v / vals.sum()))
    if not years:
        return {"years": [], "mean_share": None}
    return {"years": [str(y) for y in years], "mean_share": {f"{m:02d}": float(np.mean(shares[m])) for m in range(1, 13)}}


def sum_series(series: Iterable[pd.Series]) -> pd.Series | None:
    items = list(series)
    return sum(items) if items else None

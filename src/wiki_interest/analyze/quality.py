"""Quality checks, flags and confidence rules.

CONFIDENCE_RULES is the single source of the rules: used by the code below and printed in the
appendix, so the text and the behaviour cannot drift apart.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .metrics import M, sign

BOT_RECLASS_2025 = (M("2025-03", freq="M"), M("2025-08", freq="M"))
AUTOMATED_CLASS_START = M("2020-05", freq="M")

SEVERITY = {
    "PARTIAL_DATA": "high",
    "ARTICLE_MISSING": "warning",
    "PROXY_USED": "warning",
    "REDIRECTS_SKIPPED": "warning",
    "LOW_VOLUME": "warning",
    "PANEL_SMALL": "warning",
    "SPIKE_DRIVEN": "warning",
    "BASKET_SENSITIVE": "warning",
    "ANOMALY_MONTHS": "warning",
    "BOT_SUSPECT": "warning",
    "CONCENTRATION_DIVERGENCE": "warning",
    "PRE_2020_BOT_CLASS": "info",
    "BOT_RECLASSIFICATION_2025": "info",
    "NEW_ARTICLE": "info",
    "UNUSED_SERIES": "info",
}

DIRECTION_CAPS = ("LOW_VOLUME", "PANEL_SMALL", "REDIRECTS_SKIPPED")
MAGNITUDE_CAPS = ("BOT_RECLASSIFICATION_2025", "PRE_2020_BOT_CLASS")
MAGNITUDE_BLOCKERS = ("SPIKE_DRIVEN", "ANOMALY_MONTHS")
VARIANT_KEYS = ("loo_min", "loo_max", "no_top3", "median_ratio", "no_spikes", "no_anomalies")

CONFIDENCE_RULES = {
    "direction": [
        "Variants: the main estimate, leave-one-out minimum and maximum, without the top 3 articles, "
        "median of article ratios, without one-off spikes, without anomalous months (those that exist).",
        "high: every variant has the same sign as the main estimate and the 95% interval of index_norm excludes 1 "
        "(no interval with fewer than 3 panel articles, so at most medium).",
        "medium: every variant has the same sign, but the interval includes 1.",
        "low: otherwise.",
        "Caps: LOW_VOLUME, PANEL_SMALL or REDIRECTS_SKIPPED limit direction to medium.",
    ],
    "magnitude": [
        "spread = max / min of index_norm over the same variants.",
        "high: spread <= magnitude_high and no SPIKE_DRIVEN or ANOMALY_MONTHS for this claim.",
        "medium: spread <= magnitude_medium (or high blocked by those flags).",
        "low: otherwise.",
        "Caps: BOT_RECLASSIFICATION_2025 or PRE_2020_BOT_CLASS for the periods of this claim limit magnitude to medium.",
    ],
    "comparisons": [
        "direction high: the 95% interval of the ratio excludes 1; medium: the ratio differs from 1 by more "
        "than `flat` but the interval includes 1; low: otherwise. Fewer than min_panel common articles caps it at medium.",
        "magnitude high: interval upper/lower <= 1.3; medium: <= 1.8; low: otherwise.",
    ],
}
LEVELS = ("low", "medium", "high")


def _cap(level: str, cap: str) -> str:
    return LEVELS[min(LEVELS.index(level), LEVELS.index(cap))]


def flag(code: str, detail: str, **scope: Any) -> dict[str, Any]:
    return {"code": code, "severity": SEVERITY[code], "detail": detail, **{k: v for k, v in scope.items() if v is not None}}


# -- anomalies ---------------------------------------------------------------------------


def anomaly_months(monthly_total: pd.Series, params: dict[str, Any], first_year: int | None = None) -> list[dict[str, Any]]:
    """Months far above what the seasonal profile and the level of their own year predict.

    - Blocks: complete calendar years, plus the 12 months ending with the last month for the
      incomplete current year.
    - Typical share of calendar month m for year y: median share of m in all other complete years
      (at least 3 needed).
    - Level of a block: median over its months of views / typical share. A median, so one or two
      anomalous months do not inflate it. A plain share of the year fails both ways: Jan+Feb 2024
      took a third of that year and so inflated the total they are divided by, and a slow drift of
      the seasonal profile (uk astronomy: August grew from ~2% to ~4.5% of the year as school months
      fell) looked like an anomaly in the latest months.
    - A month is anomalous if views > anomaly_k x typical share x level.
    - Only years from `first_year` count (the first full year in which every basket article existed).
    """
    if first_year is not None:
        monthly_total = monthly_total[[p.year >= first_year for p in monthly_total.index]]
    s = monthly_total.dropna()
    if s.empty:
        return []
    complete: dict[int, pd.Series] = {}
    for year in sorted({p.year for p in s.index}):
        months = pd.PeriodIndex([f"{year}-{m:02d}" for m in range(1, 13)], freq="M")
        vals = monthly_total.reindex(months)
        if not vals.isna().any() and vals.sum() > 0:
            complete[year] = vals
    shares = {y: v / v.sum() for y, v in complete.items()}

    def typical(p: pd.Period) -> float | None:
        others = [float(shares[y].iloc[p.month - 1]) for y in shares if y != p.year]
        return float(np.median(others)) if len(others) >= 3 else None

    blocks = list(complete.values())
    last = s.index.max()
    if last.year not in complete:
        trailing = monthly_total.reindex(pd.PeriodIndex([last - i for i in range(11, -1, -1)], freq="M"))
        if not trailing.isna().any() and trailing.sum() > 0:
            blocks.append(trailing)

    found: dict[str, dict[str, Any]] = {}
    for block in blocks:
        t = {p: typical(p) for p in block.index}
        ratios = [float(block[p]) / t[p] for p in block.index if t[p]]
        if len(ratios) < 6:
            continue
        level = float(np.median(ratios))
        total = float(block.sum())
        for p, v in block.items():
            if not t[p] or level <= 0:
                continue
            expected = t[p] * level
            if v > params["anomaly_k"] * expected:
                found[str(p)] = {
                    "month": str(p),
                    "views": float(v),
                    "expected_views": expected,
                    "ratio": float(v) / expected,
                    "share_of_year": float(v) / total,
                    "typical_share": t[p],
                }
    return [found[k] for k in sorted(found)]


def bot_months(main_user: pd.Series, automated: pd.Series, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Months with a jump of the automated share (main titles, since May 2020)."""
    total = main_user + automated
    share = (automated / total.where(total > 0)).dropna()
    share = share[share.index >= AUTOMATED_CLASS_START]
    if len(share) < 6:
        return []
    med = float(share.median())
    return [
        {"month": str(p), "automated_share": float(v), "median_share": med}
        for p, v in share.items()
        if v > params["bot_min_share"] and v > params["bot_k"] * med
    ]


def overlaps(months: list[M], lo: M, hi: M) -> bool:
    return any(lo <= m <= hi for m in months)


# -- confidence --------------------------------------------------------------------------


def claim_confidence(comp: dict[str, Any], flag_codes: set[str], params: dict[str, Any]) -> dict[str, Any]:
    if comp.get("status") != "ok":
        return {"direction": "low", "magnitude": "low", "reasons": [f"no estimate: {comp.get('status')}"], "label": "none"}
    flat = params["flat"]
    main = comp["change_norm"]
    main_sign = sign(main, flat)
    var = {k: comp["variants"][k] for k in VARIANT_KEYS if comp["variants"].get(k) is not None}
    values = [main, *var.values()]
    same = all(sign(v, flat) == main_sign for v in values)
    ci = comp["index_norm_ci"]
    excludes_one = ci is not None and (ci[0] > 1 or ci[1] < 1)
    reasons: list[str] = []
    if ci is None:
        reasons.append(f"no 95% interval: fewer than 3 articles in the panel ({comp['panel']['n']})")
    label = {1: "up", -1: "down", 0: "flat"}[main_sign]

    if same and excludes_one and main_sign != 0:
        direction = "high"
        reasons.append(f"direction high: all {len(values)} estimates have the same sign and the 95% interval excludes 1")
    elif same:
        direction = "medium"
        why = "the 95% interval includes 1" if ci is not None else "there is no 95% interval"
        reasons.append(f"direction medium: all {len(values)} estimates agree on the sign, but {why}")
    else:
        direction = "low"
        flips = sorted(k for k, v in var.items() if sign(v, flat) != main_sign)
        reasons.append("direction low: these variants disagree with the main estimate: " + ", ".join(flips))
    for code in DIRECTION_CAPS:
        if code in flag_codes and direction == "high":
            direction = "medium"
            reasons.append(f"direction capped at medium: {code}")
        elif code in flag_codes:
            reasons.append(f"{code} would cap direction at medium")

    ratios = [1 + v for v in values]
    spread = max(ratios) / min(ratios) if min(ratios) > 0 else math.inf
    if spread <= params["magnitude_high"]:
        magnitude = "high"
        reasons.append("magnitude high: robustness variants stay within magnitude_high of each other")
    elif spread <= params["magnitude_medium"]:
        magnitude = "medium"
        reasons.append("magnitude medium: robustness variants differ by more than magnitude_high")
    else:
        magnitude = "low"
        reasons.append("magnitude low: robustness variants differ by more than magnitude_medium")
    for code in (*MAGNITUDE_BLOCKERS, *MAGNITUDE_CAPS):
        if code in flag_codes:
            if magnitude == "high":
                magnitude = "medium"
                reasons.append(f"magnitude capped at medium: {code}")
            else:
                reasons.append(f"{code} would cap magnitude at medium")
    return {"direction": direction, "magnitude": magnitude, "label": label, "spread": spread, "reasons": reasons}


def ratio_confidence(r: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    if r.get("status") != "ok":
        return {"direction": "low", "magnitude": "low", "reasons": [f"no estimate: {r.get('status')}"]}
    lo, hi = r["ratio_ci"]
    reasons = []
    if lo > 1 or hi < 1:
        direction = "high"
        reasons.append("direction high: the 95% interval of the ratio excludes 1")
    elif abs(r["ratio"] - 1) > params["flat"]:
        direction = "medium"
        reasons.append("direction medium: the ratio differs from 1 but the interval includes 1")
    else:
        direction = "low"
        reasons.append("direction low: the ratio is close to 1")
    n = r.get("n_common", min(r.get("n_a", 0), r.get("n_b", 0)))
    if n < params["min_panel"] and direction == "high":
        direction = "medium"
        reasons.append("direction capped at medium: PANEL_SMALL")
    width = hi / lo if lo > 0 else math.inf
    magnitude = "high" if width <= 1.3 else "medium" if width <= 1.8 else "low"
    reasons.append(f"magnitude {magnitude}: interval upper/lower ratio")
    return {"direction": direction, "magnitude": magnitude, "reasons": reasons}

"""Robustness variants of a comparison. Each is reported as change_norm (index_norm - 1):

- loo_min / loo_max: leave-one-out range (and which article was left out);
- no_top3: without the three articles with the most base-period views;
- median_ratio: median instead of geometric mean of article ratios;
- no_spikes: spike days replaced by the rolling median (see spikes.py);
- no_anomalies: month pairs with an anomalous month (see quality.anomaly_months) removed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .series import period_sum


def index_norm_of(vb: np.ndarray, vc: np.ndarray, section_ratio: float) -> float:
    return float(np.exp(np.mean(np.log((vc + 1.0) / (vb + 1.0)))) / section_ratio)


def variants(
    panel: list[tuple[Any, float, float]],
    section: pd.Series,
    base: list[pd.Period],
    cur: list[pd.Period],
    section_ratio: float,
    index_norm: float,
    anomaly_months: set[pd.Period],
) -> dict[str, Any]:
    """Robustness variants, each as change_norm (index_norm - 1)."""
    vb = np.array([p[1] for p in panel])
    vc = np.array([p[2] for p in panel])
    titles = [p[0].art.title for p in panel]
    n = len(panel)
    out: dict[str, Any] = {}

    if n >= 2:
        loo = [(index_norm_of(np.delete(vb, i), np.delete(vc, i), section_ratio) - 1, titles[i]) for i in range(n)]
        lo, hi = min(loo), max(loo)
        out["loo_min"], out["loo_min_without"] = lo
        out["loo_max"], out["loo_max_without"] = hi
    if n >= 4:
        top = np.argsort(-vb, kind="stable")[:3]
        keep = np.setdiff1d(np.arange(n), top)
        out["no_top3"] = index_norm_of(vb[keep], vc[keep], section_ratio) - 1
        out["no_top3_removed"] = sorted(titles[i] for i in top)
    out["median_ratio"] = float(np.median((vc + 1.0) / (vb + 1.0))) / section_ratio - 1

    nb = np.array([period_sum(p[0].monthly_nospikes, base) for p in panel])
    nc = np.array([period_sum(p[0].monthly_nospikes, cur) for p in panel])
    if not (np.isnan(nb).any() or np.isnan(nc).any()):
        out["no_spikes"] = index_norm_of(nb, nc, section_ratio) - 1

    pairs = [(b, c) for b, c in zip(base, cur) if b not in anomaly_months and c not in anomaly_months]
    if len(pairs) < len(base):
        out["no_anomalies_months_removed"] = sorted({str(x) for b, c in zip(base, cur) for x in (b, c) if x in anomaly_months})
        if pairs:
            b2, c2 = [p[0] for p in pairs], [p[1] for p in pairs]
            ab = np.array([period_sum(p[0].monthly, b2) for p in panel])
            ac = np.array([period_sum(p[0].monthly, c2) for p in panel])
            sr = period_sum(section, c2) / period_sum(section, b2)
            out["no_anomalies"] = index_norm_of(ab, ac, sr) - 1
    return out

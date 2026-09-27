"""One-off spikes: days far above the centred rolling median.

Detection runs on the article's user views (main title plus redirects). The bot/device
diagnostics use the main title only, because redirects are fetched for `user` only.

Classification of a spike day:
- unknown_pre_2020  - no `automated` class before May 2020, bots were counted as users;
- bot_suspect       - automated share of the day >= 0.5;
- unusual_devices   - desktop share differs from its usual level by more than 0.3;
- likely_human      - otherwise.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .series import ArticleData

BOT_SHARE = 0.5
DEVICE_SHIFT = 0.3


def rolling_median(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, center=True, min_periods=window // 2 + 1).median()


def detect(art: ArticleData, params: dict[str, Any]) -> tuple[list[dict[str, Any]], pd.Series]:
    """Spike days of one article and its user series with spike days replaced by the median."""
    user = art.user
    med = rolling_median(user, int(params["spike_window"]))
    mask = (user > params["spike_k"] * med) & (user - med >= params["spike_min_abs"]) & med.notna()
    cleaned = user.where(~mask, med)

    total_main = art.main_user + art.automated
    auto_share = art.automated / total_main.where(total_main > 0)
    desktop_share = art.desktop / art.main_user.where(art.main_user > 0)
    usual_desktop = rolling_median(desktop_share.where(~mask), int(params["spike_window"]))

    spikes = []
    for ts in user.index[mask.to_numpy()]:
        a, d, u = auto_share.get(ts), desktop_share.get(ts), usual_desktop.get(ts)
        a = None if a is None or np.isnan(a) else float(a)
        d = None if d is None or np.isnan(d) else float(d)
        u = None if u is None or np.isnan(u) else float(u)
        if a is None:
            kind = "unknown_pre_2020"
        elif a >= BOT_SHARE:
            kind = "bot_suspect"
        elif d is not None and u is not None and abs(d - u) > DEVICE_SHIFT:
            kind = "unusual_devices"
        else:
            kind = "likely_human"
        spikes.append(
            {
                "date": ts.strftime("%Y-%m-%d"),
                "article": art.title,
                "views": float(user[ts]),
                "median": float(med[ts]),
                "ratio": float(user[ts] / med[ts]) if med[ts] > 0 else None,
                "automated_share": a,
                "desktop_share": d,
                "usual_desktop_share": u,
                "class": kind,
            }
        )
    return spikes, cleaned

"""Analysis parameters: defaults, documented, overridable via analysis.json "params"."""

from __future__ import annotations

from typing import Any

from ..errors import InputError

# name: (default, description) — descriptions go to metrics.json and the appendix.
PARAMS: dict[str, tuple[Any, str]] = {
    "min_monthly_views": (30, "article leaves a comparison if its mean monthly views in the base period are below this"),
    "low_volume_month": (300, "LOW_VOLUME if the panel's median monthly views in the base period are below this"),
    "min_panel": (5, "PANEL_SMALL if fewer articles remain in a comparison panel"),
    "spike_k": (5.0, "a spike day has more than spike_k x the centred rolling median"),
    "spike_min_abs": (30, "... and at least this many views above that median"),
    "spike_window": (29, "days in the centred rolling median for spikes"),
    "spike_driven_delta": (0.10, "SPIKE_DRIVEN if removing spikes moves change_norm by more than this or flips its sign"),
    "anomaly_k": (2.0, "anomalous month: its share of the year's views exceeds anomaly_k x the typical share of that calendar month"),
    "bot_k": (3.0, "automated jump: monthly automated share above bot_k x its median since May 2020 ..."),
    "bot_min_share": (0.2, "... and above this absolute share"),
    "sensitive_delta": (0.15, "BASKET_SENSITIVE if leave-one-out or no-top-3 moves change_norm by more than this or flips its sign"),
    "flat": (0.02, "|change| below this counts as no change when comparing signs"),
    "magnitude_high": (1.15, "magnitude confidence high if max/min of the robustness variants is at most this"),
    "magnitude_medium": (1.35, "... medium if at most this, low otherwise"),
    "bootstrap": (2000, "bootstrap resamples over articles for 95% intervals"),
    "seed": (0, "bootstrap seed (fixed: identical inputs give identical metrics.json)"),
}


def resolve_params(raw: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(raw) - set(PARAMS))
    if unknown:
        raise InputError(f"params: unknown keys {unknown}", hint=f"Known params: {sorted(PARAMS)}")
    out = {}
    for name, (default, _) in PARAMS.items():
        value = raw.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise InputError(f"params.{name} must be a non-negative number, got {value!r}")
        if isinstance(default, int) and not isinstance(value, int):
            raise InputError(f"params.{name} must be an integer, got {value!r}")
        out[name] = value
    if out["bootstrap"] < 100:
        raise InputError("params.bootstrap must be at least 100")
    return out


def describe_params(values: dict[str, Any]) -> dict[str, Any]:
    return {k: {"value": values[k], "description": PARAMS[k][1]} for k in PARAMS}

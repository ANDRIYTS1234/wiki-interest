"""Page-1 chart. Shape follows the data (SPEC §9): one language -> long history + window bars;
several languages -> basket indices side by side. Saved as PNG (also embedded in the PDF)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402

from . import fonts

TARGET_COLOR = "#2f6fed"
CONTROL_COLOR = "#9aa5b1"
BAR_COLORS = ["#2f6fed", "#e0722b", "#2fa84f", "#9b51e0", "#c94f4f", "#1aa6a6"]


def _style() -> None:
    fonts.configure_matplotlib()
    plt.rcParams.update(
        {
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#444444",
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linewidth": 0.6,
            "font.size": 9,
        }
    )


def _basket_labels(basket_info: dict[str, Any]) -> dict[str, str]:
    return {bid: info["label"] for bid, info in basket_info.items()}


def history_and_window_chart(basket_info: dict[str, Any], baskets: dict[str, Any], lang: str, out_path: Path, report_lang: str) -> None:
    """One language: long-history line for each basket (left) + window index_norm bars (right)."""
    _style()
    labels = _basket_labels(basket_info)
    fig, (ax_hist, ax_bar) = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [1.5, 1]})

    for i, bid in enumerate(baskets):
        hist = baskets[bid][lang].get("history") or {}
        blocks = hist.get("blocks") or {}
        years = sorted(blocks)
        values = [blocks[y]["share_per_million"] for y in years]
        color = BAR_COLORS[i % len(BAR_COLORS)]
        xs = [int(y) for y, v in zip(years, values) if v is not None]
        ys = [v for v in values if v is not None]
        if xs:
            ax_hist.plot(xs, ys, marker="o", markersize=3, linewidth=1.6, color=color, label=labels.get(bid, bid))
    ax_hist.set_title("Traffic share of the edition, per year" if report_lang == "en" else "Частка в трафіку розділу, за роками", fontsize=9)
    ax_hist.set_ylabel("per 1M views")
    ax_hist.legend(fontsize=7, frameon=False)
    ax_hist.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    xs_bar, vals, errs, colors = [], [], [], []
    for i, bid in enumerate(baskets):
        w = baskets[bid][lang]["window"]
        if w.get("status") != "ok":
            continue
        xs_bar.append(labels.get(bid, bid))
        vals.append(w["index_norm"])
        lo, hi = w["index_norm_ci"] or (w["index_norm"], w["index_norm"])
        errs.append([[w["index_norm"] - lo], [hi - w["index_norm"]]])
        colors.append(BAR_COLORS[i % len(BAR_COLORS)])
    if xs_bar:
        errs_arr = [[e[0][0] for e in errs], [e[1][0] for e in errs]]
        ax_bar.bar(xs_bar, vals, color=colors, width=0.5)
        ax_bar.errorbar(xs_bar, vals, yerr=errs_arr, fmt="none", ecolor="#222222", capsize=3, linewidth=1)
        ax_bar.axhline(1.0, color="#888888", linewidth=0.8, linestyle="--")
    ax_bar.set_title("This window vs a year earlier" if report_lang == "en" else "Це вікно проти року тому", fontsize=9)
    ax_bar.set_ylabel("index_norm")
    plt.setp(ax_bar.get_xticklabels(), rotation=20, ha="right", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def basket_indices_chart(basket_info: dict[str, Any], baskets: dict[str, Any], langs: list[str], out_path: Path, report_lang: str) -> None:
    """Several languages: basket index_norm bars grouped by language, one colour per basket."""
    _style()
    labels = _basket_labels(basket_info)
    bids = list(baskets)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    n_groups, width = len(bids), 0.8 / max(1, len(bids))
    x_base = range(len(langs))
    for i, bid in enumerate(bids):
        vals, errs = [], [[], []]
        for lang in langs:
            w = baskets[bid][lang]["window"]
            if w.get("status") == "ok":
                v = w["index_norm"]
                lo, hi = w["index_norm_ci"] or (v, v)
            else:
                v, lo, hi = None, None, None
            vals.append(v or 0)
            errs[0].append(0 if v is None else v - lo)
            errs[1].append(0 if v is None else hi - v)
        xs = [x + i * width for x in x_base]
        ax.bar(xs, vals, width=width * 0.9, color=BAR_COLORS[i % len(BAR_COLORS)], label=labels.get(bid, bid))
        ax.errorbar(xs, vals, yerr=errs, fmt="none", ecolor="#222222", capsize=3, linewidth=1)
    ax.axhline(1.0, color="#888888", linewidth=0.8, linestyle="--")
    ax.set_xticks([x + width * (n_groups - 1) / 2 for x in x_base])
    ax.set_xticklabels(langs)
    ax.set_ylabel("index_norm")
    ax.set_title(
        "Basket index by language (this window vs a year earlier)"
        if report_lang == "en"
        else "Індекс кошика за мовою (це вікно проти року тому)",
        fontsize=9,
    )
    ax.legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def render_chart(metrics: dict[str, Any], out_path: Path, report_lang: str) -> Path:
    basket_info, baskets = metrics["basket_info"], metrics["baskets"]
    langs = metrics["spec"]["langs"]
    if len(langs) == 1:
        history_and_window_chart(basket_info, baskets, langs[0], out_path, report_lang)
    else:
        basket_indices_chart(basket_info, baskets, langs, out_path, report_lang)
    return out_path

"""`analyze`: metrics.json from cached pageviews (SPEC §8). No network.

metrics.json layout (placeholders in narrative.json use these paths):
  baskets.<basket>.<lang>.window                  current window vs the same months a year earlier
  baskets.<basket>.<lang>.baselines.<year>        current window vs the same months of <year>
  baskets.<basket>.<lang>.groups.<group>.window | .baselines.<year>
  baskets.<basket>.<lang>.confidence.window | .baselines.<year>
  baskets.<basket>.<lang>.history | seasonality | spikes | anomaly_months | bot_months
  compare.<basket>.<lang1>_vs_<lang2>.window | .baselines.<year>   same QIDs in both languages
  compare.<basket1>_vs_<basket2>.<lang>.window | .baselines.<year> target vs control/context
  flags[]  (code, severity, detail, basket, lang, scope)
Floats are rounded to 6 significant digits and keys sorted: same inputs give the same bytes.
"""

from __future__ import annotations

import json
import math
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .. import __version__
from ..cache import Cache
from ..schemas import AnalysisSpec, load_json_file, parse_analysis_spec
from .metrics import M, Member, comparison, history, period_months, ratio_of_indices, seasonality, sign
from .params import describe_params, resolve_params
from .quality import (
    AUTOMATED_CLASS_START,
    BOT_RECLASS_2025,
    CONFIDENCE_RULES,
    anomaly_months,
    bot_months,
    claim_confidence,
    flag,
    overlaps,
    ratio_confidence,
)
from .series import Dataset, load_dataset, monthly
from .spikes import detect

METRICS_FILE = "metrics.json"
MAX_SPIKES = 30


def _clean(x: Any) -> Any:
    """Drop private keys, round floats to 6 significant digits, NaN/inf -> None."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items() if not str(k).startswith("_")}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if math.isnan(f) or math.isinf(f) else float(f"{f:.6g}")
    if isinstance(x, np.integer):
        return int(x)
    return x


def _claim_flags(comp: dict[str, Any], params: dict[str, Any], anomalies: set[M], bots: set[M], bot_spike_months: set[M], **where: Any) -> list[dict[str, Any]]:
    """Flags that belong to one claim (a comparison of two periods)."""
    if comp.get("status") != "ok":
        return [flag("PANEL_SMALL", f"no estimate ({comp.get('status')}); panel has {comp['panel']['n']} articles", **where)]
    out = []
    base = [M(m, freq="M") for m in comp["periods"]["base"]]
    cur = [M(m, freq="M") for m in comp["periods"]["current"]]
    base_months = pd.period_range(base[0], base[1], freq="M").tolist()
    cur_months = pd.period_range(cur[0], cur[1], freq="M").tolist()
    used = base_months + cur_months
    main, var, flat = comp["change_norm"], comp["variants"], params["flat"]
    n = comp["panel"]["n"]
    if n < params["min_panel"]:
        out.append(flag("PANEL_SMALL", f"{n} articles in the panel (min_panel {params['min_panel']})", **where))
    low = sum(1 for e in comp["panel"]["excluded"] if e["reason"] == "low_volume")
    if comp["median_month_base"] < params["low_volume_month"] or low > n:
        out.append(flag("LOW_VOLUME", "median monthly views of the panel in the base period are below low_volume_month"
                        if comp["median_month_base"] < params["low_volume_month"] else f"{low} articles excluded for low volume, more than the panel", **where))
    ns = var.get("no_spikes")
    if ns is not None and (abs(ns - main) > params["spike_driven_delta"] or sign(ns, flat) != sign(main, flat)):
        out.append(flag("SPIKE_DRIVEN", "removing one-off spikes changes change_norm materially (see variants.no_spikes)", **where))
    moved = [k for k in ("loo_min", "loo_max", "no_top3") if var.get(k) is not None
             and (abs(var[k] - main) > params["sensitive_delta"] or sign(var[k], flat) != sign(main, flat))]
    if moved:
        out.append(flag("BASKET_SENSITIVE", "the result depends on single articles: " + ", ".join(moved), **where))
    hit = sorted(str(m) for m in used if m in anomalies)
    if hit:
        out.append(flag("ANOMALY_MONTHS", "anomalous months inside the compared periods: " + ", ".join(hit), **where))
    bot_hit = sorted(str(m) for m in used if m in bots or m in bot_spike_months)
    if bot_hit:
        out.append(flag("BOT_SUSPECT", "automated jumps or bot-like spikes in: " + ", ".join(bot_hit), **where))
    if comp["share_change"] is not None and sign(main, flat) * sign(comp["share_change"], flat) == -1:
        top = ", ".join(a["title"] for a in comp["top_contributors"])
        out.append(flag("CONCENTRATION_DIVERGENCE",
                        "the typical article (index_norm) and total attention (share_change) move in opposite "
                        f"directions; largest contributions to share_change: {top}", **where))
    if base_months[0] < AUTOMATED_CLASS_START:
        out.append(flag("PRE_2020_BOT_CLASS", "the base period is before May 2020, when bots were still counted as users", **where))
    if overlaps(used, *BOT_RECLASS_2025):
        out.append(flag("BOT_RECLASSIFICATION_2025", "compared periods include March-August 2025, when Wikimedia reclassified bot traffic", **where))
    return out


def _claims(members: list[Member], section: pd.Series, periods: dict[str, tuple[list[M], list[M]]], params: dict[str, Any],
            key: str, anomalies: set[M], bots: set[M], bot_spikes: set[M], extra_flags: list[dict[str, Any]], **where: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """window + baselines comparisons, their flags and confidence."""
    block: dict[str, Any] = {"baselines": {}}
    confidence: dict[str, Any] = {"baselines": {}}
    flags: list[dict[str, Any]] = []
    for name, (base, cur) in periods.items():
        comp = comparison(members, section, base, cur, params, f"{key}/{name}", anomalies)
        scope = "window" if name == "window" else f"baseline:{name}"
        fl = _claim_flags(comp, params, anomalies, bots, bot_spikes, scope=scope, **where)
        flags += fl
        codes = {f["code"] for f in fl} | {f["code"] for f in extra_flags}
        conf = claim_confidence(comp, codes, params)
        if name == "window":
            block["window"], confidence["window"] = comp, conf
        else:
            block["baselines"][name], confidence["baselines"][name] = comp, conf
    block["confidence"] = confidence
    return block, flags


def run_analysis(spec: AnalysisSpec, cache: Cache, workdir: Path | None = None) -> dict[str, Any]:
    params = resolve_params(spec.params)
    ds: Dataset = load_dataset(spec, cache, workdir)
    end = M(ds.data_as_of, freq="M")
    n = spec.window_months
    periods: dict[str, tuple[list[M], list[M]]] = {"window": (period_months(end, n, 1), period_months(end, n))}
    for y in spec.baselines:
        periods[str(y)] = (period_months(end, n, end.year - y), period_months(end, n))
    first_month = M(ds.start.strftime("%Y-%m"), freq="M")
    used_months = {m for base, cur in periods.values() for m in (*base, *cur)}

    spikes_by_article: dict[str, list[dict[str, Any]]] = {}
    nospikes: dict[str, pd.Series] = {}
    for key, art in ds.articles.items():
        spikes_by_article[key], cleaned = detect(art, params)
        nospikes[key] = monthly(cleaned)

    flags: list[dict[str, Any]] = []
    baskets: dict[str, Any] = {}
    basket_info: dict[str, Any] = {}
    claim_blocks: dict[tuple[str, str], dict[str, Any]] = {}
    for basket in spec.baskets:
        basket_info[basket.id] = {
            "role": basket.role,
            "label": basket.label,
            "items": [
                {"item": c.item, "lang": c.lang, "status": c.status, "reason": c.reason, "article": c.article, "group": c.group, "proxy_for": c.proxy_for}
                for c in ds.candidates if c.basket == basket.id
            ],
        }
        baskets[basket.id] = {}
        for lang in spec.langs:
            where = {"basket": basket.id, "lang": lang}
            cands = [c for c in ds.candidates if c.basket == basket.id and c.lang == lang]
            members = [Member(c.item, c.group, ds.articles[c.article], nospikes[c.article]) for c in cands if c.status == "ok"]
            section = ds.section_monthly[lang]
            base_flags: list[dict[str, Any]] = []
            missing = [c.item for c in cands if c.status == "missing"]
            if missing:
                base_flags.append(flag("ARTICLE_MISSING", f"no article in {lang}.wikipedia for: " + ", ".join(missing), **where))
            proxies = [f"{c.item} (for {c.proxy_for})" for c in cands if c.proxy_for and c.status == "ok"]
            if proxies:
                base_flags.append(flag("PROXY_USED", "non-equivalent substitutes: " + ", ".join(proxies), **where))
            keys = {m.art.key for m in members} | {lang}
            for code in ("PARTIAL_DATA", "REDIRECTS_SKIPPED"):
                probs = [p for p in ds.problems if p["code"] == code and p["article"] in keys]
                if probs:
                    titles = sorted({p["series"]["article"] for p in probs})
                    base_flags.append(flag(code, f"{len(probs)} series ranges without data: " + ", ".join(titles[:10]), **where))

            # sum() starts from 0: an empty Series as the start would align indices and give NaN.
            total = sum(m.monthly for m in members) if members else pd.Series(dtype=float)
            created = [m.art.created for m in members if m.art.created]
            first_full_year = (max(created).year + 1) if created else None
            anomalies = anomaly_months(total, params, first_full_year) if members else []
            anomaly_set = {M(a["month"], freq="M") for a in anomalies}
            main_user = sum(monthly(m.art.main_user) for m in members) if members else pd.Series(dtype=float)
            automated = sum(monthly(m.art.automated) for m in members) if members else pd.Series(dtype=float)
            bots = bot_months(main_user, automated, params) if members else []
            bot_set = {M(b["month"], freq="M") for b in bots}
            spikes = sorted(
                (s for m in members for s in spikes_by_article[m.art.key] if M(s["date"][:7], freq="M") in used_months),
                key=lambda s: (s["date"], s["article"]),
            )
            bot_spike_set = {M(s["date"][:7], freq="M") for s in spikes if s["class"] == "bot_suspect"}

            block, claim_flags = _claims(members, section, periods, params, f"{basket.id}/{lang}", anomaly_set, bot_set, bot_spike_set, base_flags, **where)
            groups = sorted({m.group for m in members if m.group})
            block["groups"] = {}
            for g in groups:
                gm = [m for m in members if m.group == g]
                gblock, gflags = _claims(gm, section, periods, params, f"{basket.id}/{lang}/{g}", anomaly_set, bot_set, bot_spike_set, base_flags, group=g, **where)
                block["groups"][g] = gblock
                claim_flags += gflags
            hist = history(members, section, end, first_month, M(spec.history_start, freq="M")) if members else {}
            if hist.get("new_articles"):
                base_flags.append(flag("NEW_ARTICLE", "created after history_start: " + ", ".join(a["title"] for a in hist["new_articles"]), **where))
            block.update(
                {
                    "history": hist,
                    "seasonality": seasonality(total) if members else {},
                    "anomaly_months": anomalies,
                    "bot_months": bots,
                    "spikes": spikes[:MAX_SPIKES],
                    "spikes_total": len(spikes),
                    "missing_items": missing,
                }
            )
            flags += base_flags + claim_flags
            baskets[basket.id][lang] = block
            claim_blocks[(basket.id, lang)] = block

    compare: dict[str, Any] = {}
    for basket in spec.baskets:
        pairs = {}
        for a, b in combinations(spec.langs, 2):
            pairs[f"{a}_vs_{b}"] = _compare(claim_blocks[(basket.id, a)], claim_blocks[(basket.id, b)], params, f"{basket.id}/{a}_vs_{b}", True)
        if pairs:
            compare[basket.id] = pairs
    targets = [b for b in spec.baskets if b.role == "target"]
    others = [b for b in spec.baskets if b.role != "target"]
    for t in targets:
        for o in others:
            compare[f"{t.id}_vs_{o.id}"] = {
                lang: _compare(claim_blocks[(t.id, lang)], claim_blocks[(o.id, lang)], params, f"{t.id}_vs_{o.id}/{lang}", False)
                for lang in spec.langs
            }

    if ds.unused_series:
        flags.append(flag("UNUSED_SERIES", f"{len(ds.unused_series)} downloaded series are in no basket: "
                          + ", ".join(sorted({u['article'] for u in ds.unused_series})[:10])))

    flags.sort(key=lambda f: (f.get("basket", ""), f.get("lang", ""), f.get("group", ""), f.get("scope", ""), f["code"]))
    return _clean(
        {
            "tool_version": __version__,
            "data_as_of": ds.data_as_of,
            "question": spec.question,
            "spec": {
                "langs": list(spec.langs),
                "window": {"months": n, "end": ds.data_as_of},
                "history_start": spec.history_start,
                "baselines": list(spec.baselines),
                "range": {"start": ds.start.isoformat(), "end": ds.end.isoformat()},
            },
            "params": describe_params(params),
            "confidence_rules": CONFIDENCE_RULES,
            "basket_info": basket_info,
            "baskets": baskets,
            "compare": compare,
            "flags": flags,
            "data_problems": ds.problems,
            "unused_series": ds.unused_series,
        }
    )


def _compare(a: dict[str, Any], b: dict[str, Any], params: dict[str, Any], key: str, paired: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"baselines": {}}
    names = ["window", *a["baselines"].keys()]
    for name in names:
        ca = a["window"] if name == "window" else a["baselines"][name]
        cb = b["window"] if name == "window" else b["baselines"][name]
        r = ratio_of_indices(ca, cb, params, f"{key}/{name}", paired)
        r["confidence"] = ratio_confidence(r, params)
        if name == "window":
            out["window"] = r
        else:
            out["baselines"][name] = r
    return out


# -- CLI ---------------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:+.0f}%"


def _claim_line(comp: dict[str, Any], conf: dict[str, Any]) -> str:
    if comp.get("status") != "ok":
        return f"no estimate ({comp.get('status')})"
    ci = comp["index_norm_ci"]
    interval = f"[{ci[0]:.3g}; {ci[1]:.3g}]" if ci else "[no interval]"
    return (
        f"{conf['label']} index_norm {comp['index_norm']:.3g} {interval} (change {_pct(comp['change_norm'])}), "
        f"share_change {_pct(comp['share_change'])}, direction {conf['direction']}, magnitude {conf['magnitude']}, "
        f"panel {comp['panel']['n']}"
    )


def summarize(metrics: dict[str, Any], path: Path) -> dict[str, Any]:
    lines = []
    for bid, langs in metrics["baskets"].items():
        for lang, block in langs.items():
            codes = sorted({f["code"] for f in metrics["flags"] if f.get("basket") == bid and f.get("lang") == lang and not f.get("group")})
            parts = [f"{bid}/{lang} window: " + _claim_line(block["window"], block["confidence"]["window"])]
            for year, comp in block["baselines"].items():
                c = block["confidence"]["baselines"][year]
                parts.append(f"vs {year}: {c['label']} {_pct(comp.get('change_norm'))} ({c['direction']}/{c['magnitude']})")
            parts.append("flags: " + (", ".join(codes) if codes else "none"))
            lines.append("; ".join(parts))
    comps = []
    for name, entry in metrics["compare"].items():
        for sub, r in entry.items():
            w = r.get("window", {})
            if w.get("status") == "ok":
                lo, hi = w["ratio_ci"]
                c = w["confidence"]
                comps.append(f"{name} {sub}: ratio {w['ratio']:.3g} [{lo:.3g}; {hi:.3g}], direction {c['direction']}, magnitude {c['magnitude']}")
            else:
                comps.append(f"{name} {sub}: {w.get('status')}")
    return {
        "metrics_file": str(path),
        "summary": lines,
        "compare": comps,
        "flags_total": len(metrics["flags"]),
        "hint": "Details, panels, exclusions and reasons are in metrics_file. In narrative.json use placeholders "
        "such as {target.uk.window.change_norm:pct}; never type numbers.",
    }


def cmd_analyze(args: Any, ctx: Any) -> dict[str, Any]:
    spec = parse_analysis_spec(load_json_file(args.spec, "analysis spec"))
    workdir: Path = ctx.settings.workdir
    metrics = run_analysis(spec, ctx.cache, workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / METRICS_FILE
    path.write_text(json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return {"data_as_of": metrics["data_as_of"], **summarize(metrics, path)}

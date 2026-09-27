"""`report`: metrics.json + narrative.json -> a one-page PDF, appendix.md and a PNG chart (SPEC §9)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..analyze import METRICS_FILE
from ..errors import InputError
from ..schemas import load_json_file
from .appendix import build_appendix
from .charts import render_chart
from .flag_text import duplicate_of
from .narrative import render_narrative, validate_narrative
from .pdf import render_pdf

APPENDIX_FILE = "appendix.md"
CHART_FILE = "report_chart.png"


REPORT_FILE = "report.pdf"


def cmd_report(args: Any, ctx: Any) -> dict[str, Any]:
    workdir: Path = ctx.settings.workdir
    metrics_path = Path(args.metrics) if args.metrics else workdir / METRICS_FILE
    metrics = load_json_file(metrics_path, "metrics.json")
    if not isinstance(metrics, dict) or "baskets" not in metrics:
        raise InputError(f"{metrics_path} does not look like a metrics.json (no 'baskets' key)", hint="Pass the file written by `analyze`")
    narrative_raw = load_json_file(args.narrative, "narrative.json")
    narrative = validate_narrative(narrative_raw)
    rendered = render_narrative(narrative, metrics, args.report_lang)
    # An agent caveat that repeats an automatically printed line is not printed twice (a Haiku run
    # added "Cannot compare Polish-Czech" next to the automatic line); stdout says what was dropped.
    printed = {f["code"] for f in metrics.get("flags", [])}
    if any(r.get("window", {}).get("comparable") is False for e in metrics.get("compare", {}).values() for r in e.values()):
        printed.add("NOT_COMPARABLE")
    kept, dropped = [], []
    for raw, text in zip(narrative["caveats"], rendered["caveats"]):
        repeats = duplicate_of(raw, printed)
        if repeats:
            dropped.append({"caveat": raw, "repeats": repeats})
        else:
            kept.append(text)
    rendered["caveats"] = kept

    workdir.mkdir(parents=True, exist_ok=True)
    # One stable path by default: a follow-up question updates the same report, never a second
    # PDF next to it that disagrees with the first (scenario E).
    out_path = Path(args.out) if args.out else workdir / REPORT_FILE
    out_path.parent.mkdir(parents=True, exist_ok=True)
    replaced = out_path.exists()
    chart_path = workdir / CHART_FILE
    render_chart(metrics, chart_path, args.report_lang)

    layout = render_pdf(metrics, rendered, chart_path, out_path, args.report_lang)

    appendix_path = workdir / APPENDIX_FILE
    appendix_path.write_text(build_appendix(metrics, args.report_lang), encoding="utf-8")

    return {
        "data_as_of": metrics["data_as_of"],
        "pdf": str(out_path),
        "replaced": replaced,
        "pages": 1,
        "layout": layout,
        "chart": str(chart_path),
        "appendix": str(appendix_path),
        "caveats_dropped": dropped,
    }

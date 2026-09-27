"""`report`: metrics.json + narrative.json -> a one-page PDF, appendix.md and a PNG chart (SPEC §9)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import InputError
from ..schemas import load_json_file
from .appendix import build_appendix
from .charts import render_chart
from .narrative import render_narrative, validate_narrative
from .pdf import render_pdf

APPENDIX_FILE = "appendix.md"
CHART_FILE = "report_chart.png"


def cmd_report(args: Any, ctx: Any) -> dict[str, Any]:
    metrics = load_json_file(args.metrics, "metrics.json")
    if not isinstance(metrics, dict) or "baskets" not in metrics:
        raise InputError(f"{args.metrics} does not look like a metrics.json (no 'baskets' key)", hint="Pass the file written by `analyze`")
    narrative_raw = load_json_file(args.narrative, "narrative.json")
    narrative = validate_narrative(narrative_raw)
    rendered = render_narrative(narrative, metrics, args.report_lang)

    workdir: Path = ctx.settings.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path = workdir / CHART_FILE
    render_chart(metrics, chart_path, args.report_lang)

    render_pdf(metrics, rendered, chart_path, out_path, args.report_lang)

    appendix_path = workdir / APPENDIX_FILE
    appendix_path.write_text(build_appendix(metrics, args.report_lang), encoding="utf-8")

    return {
        "data_as_of": metrics["data_as_of"],
        "pdf": str(out_path),
        "pages": 1,
        "chart": str(chart_path),
        "appendix": str(appendix_path),
    }

"""The one-page PDF (SPEC §9): title, answer, confidence badge, chart, compact number table,
up to 4 findings, recommendation, caveats, source line. Verified to be exactly one page: if the
content does not fit, this raises instead of silently spilling onto a second page."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..errors import WikiInterestError

from . import fonts
from .flag_text import flag_lines, not_comparable_text
from .fmt import fmt_ci, fmt_int, fmt_pct, fmt_x

MARGIN = 14 * mm
CAVEATS_MAX_HEIGHT = A4[1] / 4
CONF_COLORS = {"high": "#2fa84f", "medium": "#e0a52b", "low": "#c94f4f"}

LABELS = {
    "uk": {
        "confidence": "Довіра",
        "direction": "напрям",
        "magnitude": "масштаб",
        "table_title": "Ключові числа",
        "col_basket": "кошик", "col_lang": "мова", "col_index": "index_norm",
        "col_change": "зміна", "col_share": "частка", "col_panel": "панель",
        "findings": "Висновки",
        "recommendation": "Рекомендація",
        "caveats": "Застереження",
        "source": "Джерело",
        "data_as_of": "дані станом на",
    },
    "en": {
        "confidence": "Confidence",
        "direction": "direction",
        "magnitude": "magnitude",
        "table_title": "Key numbers",
        "col_basket": "basket", "col_lang": "lang", "col_index": "index_norm",
        "col_change": "change", "col_share": "share", "col_panel": "panel",
        "findings": "Findings",
        "recommendation": "Recommendation",
        "caveats": "Caveats",
        "source": "Source",
        "data_as_of": "data as of",
    },
}


class ReportTooLongError(WikiInterestError):
    exit_code = 2
    code = "report_too_long"


# Layouts tried in order. The automatic caveats (every flag, every "do not compare") are
# mandatory, so a report with many flags falls back to the compact layout before failing.
LAYOUTS = {
    "normal": {"title": 20, "answer": 13, "h2": 12.5, "body": 10.5, "small": 9, "table": 9.5, "chart_h": 92, "space": 10},
    "compact": {"title": 16, "answer": 11, "h2": 10.5, "body": 9, "small": 7.8, "table": 8.5, "chart_h": 64, "space": 5},
}


def _styles(report_lang: str, layout: str = "normal") -> dict[str, ParagraphStyle]:
    base_font = fonts.RL_REGULAR
    bold_font = fonts.RL_BOLD
    z = LAYOUTS[layout]
    return {
        "title": ParagraphStyle("title", fontName=bold_font, fontSize=z["title"], leading=z["title"] * 1.2, spaceAfter=6),
        "answer": ParagraphStyle("answer", fontName=base_font, fontSize=z["answer"], leading=z["answer"] * 1.3, spaceAfter=z["space"] - 2),
        "h2": ParagraphStyle("h2", fontName=bold_font, fontSize=z["h2"], leading=z["h2"] * 1.2, spaceBefore=z["space"], spaceAfter=3),
        "body": ParagraphStyle("body", fontName=base_font, fontSize=z["body"], leading=z["body"] * 1.33),
        "small": ParagraphStyle("small", fontName=base_font, fontSize=z["small"], leading=z["small"] * 1.3, textColor=colors.HexColor("#555555")),
        "table": ParagraphStyle("table", fontName=base_font, fontSize=z["table"], leading=z["table"] * 1.26),
    }


def _confidence_badge(
    baskets: dict[str, Any], langs: list[str], report_lang: str, styles: dict[str, ParagraphStyle], basket_info: dict[str, Any] | None = None
) -> Table:
    L = LABELS[report_lang]
    info = basket_info or {}
    # Badges are about the topic: target baskets only (all baskets if none is a target), by label.
    shown = [b for b in baskets if info.get(b, {}).get("role") == "target"] or list(baskets)
    chips = []
    for bid in shown:
        per_lang = baskets[bid]
        for lang in langs:
            conf = per_lang[lang]["confidence"]["window"]
            if conf.get("direction") is None:
                continue
            name = info.get(bid, {}).get("label", bid) + (f" ({lang})" if len(langs) > 1 else "")
            text = f"{escape(name)}: {L['direction']} {conf['direction']}, {L['magnitude']} {conf['magnitude']}"
            color = CONF_COLORS.get(conf["direction"], "#888888")
            chips.append(
                Table(
                    [[Paragraph(text, ParagraphStyle("chip", parent=styles["body"], textColor=colors.white, fontSize=8))]],
                    style=TableStyle(
                        [("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(color)), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                         ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
                    ),
                )
            )
    if not chips:
        return Paragraph("", styles["body"])
    rows = [chips[i : i + 2] for i in range(0, len(chips), 2)]
    if len(rows) > 1 and len(rows[-1]) == 1:
        rows[-1].append("")
    return Table(rows, hAlign="LEFT", style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                                         ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))


def _number_table(metrics: dict[str, Any], report_lang: str, styles: dict[str, ParagraphStyle]) -> Table:
    L = LABELS[report_lang]
    header = [L["col_basket"], L["col_lang"], L["col_index"], L["col_change"], L["col_share"], L["col_panel"]]
    rows = [[Paragraph(h, styles["table"]) for h in header]]
    for bid, per_lang in metrics["baskets"].items():
        label = metrics["basket_info"][bid]["label"]
        for lang, block in per_lang.items():
            w = block["window"]
            if w.get("status") != "ok":
                rows.append([Paragraph(x, styles["table"]) for x in (label, lang, "—", "—", "—", w.get("status", ""))])
                continue
            ci = fmt_ci(w["index_norm_ci"], report_lang) if w["index_norm_ci"] else "—"
            rows.append(
                [
                    Paragraph(label, styles["table"]),
                    Paragraph(lang, styles["table"]),
                    Paragraph(f"{fmt_x(w['index_norm'], report_lang)} {ci}", styles["table"]),
                    Paragraph(fmt_pct(w["change_norm"], report_lang), styles["table"]),
                    Paragraph(fmt_pct(w["share_change"], report_lang) if w["share_change"] is not None else "—", styles["table"]),
                    Paragraph(str(w["panel"]["n"]), styles["table"]),
                ]
            )
    t = Table(rows, colWidths=[32 * mm, 12 * mm, 40 * mm, 22 * mm, 22 * mm, 16 * mm], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2fb")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#888888")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#dddddd")),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return t


def _bullets(items: list[str], style: ParagraphStyle) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(item, style), leftIndent=10) for item in items],
        bulletType="bullet",
        start="•",
        leftIndent=10,
        spaceBefore=1,
        spaceAfter=1,
    )


def automatic_caveats(metrics: dict[str, Any], report_lang: str) -> list[str]:
    """Plain-language lines for all quality flags and all window comparisons that are not possible."""
    labels = {bid: info["label"] for bid, info in metrics.get("basket_info", {}).items()}
    lines = flag_lines(metrics.get("flags", []), report_lang, labels, metrics.get("spec", {}).get("langs"))
    for entry in metrics.get("compare", {}).values():
        for r in entry.values():
            w = r.get("window", {})
            if w and w.get("comparable") is False:
                lines.append(not_comparable_text(w, report_lang))
    return [escape(line) for line in lines]


def build_story(metrics: dict[str, Any], narrative: dict[str, Any], chart_path: Path, report_lang: str, layout: str = "normal") -> list:
    L = LABELS[report_lang]
    styles = _styles(report_lang, layout)
    story: list = []
    story.append(Paragraph(narrative["title"], styles["title"]))
    story.append(_confidence_badge(metrics["baskets"], metrics["spec"]["langs"], report_lang, styles, metrics.get("basket_info")))
    story.append(Spacer(1, 4))
    story.append(Paragraph(narrative["answer"], styles["answer"]))

    img = Image(str(chart_path))
    max_w, max_h = 182 * mm, LAYOUTS[layout]["chart_h"] * mm
    scale = min(max_w / img.imageWidth, max_h / img.imageHeight)
    img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
    story.append(img)
    story.append(Spacer(1, 8))

    story.append(Paragraph(L["table_title"], styles["h2"]))
    story.append(_number_table(metrics, report_lang, styles))

    if narrative["findings"]:
        story.append(Paragraph(L["findings"], styles["h2"]))
        story.append(_bullets(narrative["findings"], styles["body"]))

    story.append(Paragraph(L["recommendation"], styles["h2"]))
    story.append(Paragraph(narrative["recommendation"], styles["body"]))

    # Every flag and every "do not compare directly" is printed here whatever the narrative says
    # (a Haiku run left flags out of the PDF), then the agent's own caveats.
    auto = automatic_caveats(metrics, report_lang)
    caveats = auto + list(narrative["caveats"])
    if caveats:
        story.append(Paragraph(L["caveats"], styles["h2"]))
        block = _bullets(caveats, styles["small"])
        block._wi_caveats = (caveats, styles["small"])  # measured in render_pdf: at most a quarter page
        story.append(block)

    source = (
        f"{L['source']}: Wikimedia Pageviews API. {L['data_as_of']} {metrics['data_as_of']}. "
        f"wiki-interest {metrics['tool_version']}."
    )
    story.append(Spacer(1, 4))
    story.append(Paragraph(source, styles["small"]))
    return story


def _build(story: list, title: str) -> tuple[bytes, bool]:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN, title=title)
    overflowed = {"flag": False}

    def _mark_overflow(canvas, doc_):
        overflowed["flag"] = True

    # SimpleDocTemplate paginates automatically; onLaterPages fires only for page 2+, which is
    # exactly the overflow signal.
    doc.build(story, onLaterPages=_mark_overflow)
    return buf.getvalue(), overflowed["flag"]


def render_pdf(metrics: dict[str, Any], narrative: dict[str, Any], chart_path: Path, out_path: Path, report_lang: str) -> str:
    """Write the one-page PDF; returns the layout used. Built in memory and written only when it
    fits, so a failed rerun never deletes or half-overwrites the previous report at the same path."""
    fonts.register_reportlab()
    caveats_too_long = False
    for layout in LAYOUTS:
        story = build_story(metrics, narrative, chart_path, report_lang, layout)
        # The caveats block may take at most a quarter of the page. Automatic lines are mandatory,
        # so only the agent's own caveats can make it too long.
        block = next((f for f in story if getattr(f, "_wi_caveats", None)), None)
        if block is not None and narrative["caveats"]:
            texts, style = block._wi_caveats
            width = A4[0] - 2 * MARGIN - 20  # minus the bullet indent
            height = sum(Paragraph(t, style).wrap(width, A4[1])[1] + 2 for t in texts)
            if height > CAVEATS_MAX_HEIGHT:
                caveats_too_long = True
                continue
        data, overflowed = _build(story, narrative["title"])
        if not overflowed:
            out_path.write_bytes(data)
            return layout
    n_auto = len(automatic_caveats(metrics, report_lang))
    if caveats_too_long:
        raise ReportTooLongError(
            "the caveats block would take more than a quarter of the page",
            hint=f"Shorten or drop your own caveats: the {n_auto} flag lines are printed automatically; "
            "keep only what they do not cover.",
        )
    sizes = [("answer", len(narrative["answer"])), ("recommendation", len(narrative["recommendation"]))]
    sizes += [(f"{f}[{i}]", len(t)) for f in ("findings", "next_steps", "caveats") for i, t in enumerate(narrative[f])]
    longest = ", ".join(f"{name} ({n} chars)" for name, n in sorted(sizes, key=lambda x: -x[1])[:4])
    raise ReportTooLongError(
        "the report does not fit on one A4 page even in the compact layout",
        hint=f"Shorten the longest texts first: {longest}. Drop caveats that repeat the {n_auto} automatic flag "
        "lines (those are always printed). Text is never silently cut.",
    )

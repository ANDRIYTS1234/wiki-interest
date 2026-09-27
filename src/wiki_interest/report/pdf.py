"""The one-page PDF (SPEC §9): title, answer, confidence badge, chart, compact number table,
up to 4 findings, recommendation, caveats, source line. Verified to be exactly one page: if the
content does not fit, this raises instead of silently spilling onto a second page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
from .fmt import fmt_ci, fmt_int, fmt_pct, fmt_x

MARGIN = 14 * mm
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


def _styles(report_lang: str) -> dict[str, ParagraphStyle]:
    base_font = fonts.RL_REGULAR
    bold_font = fonts.RL_BOLD
    return {
        "title": ParagraphStyle("title", fontName=bold_font, fontSize=20, leading=24, spaceAfter=6),
        "answer": ParagraphStyle("answer", fontName=base_font, fontSize=13, leading=17, spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName=bold_font, fontSize=12.5, leading=15, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", fontName=base_font, fontSize=10.5, leading=14),
        "small": ParagraphStyle("small", fontName=base_font, fontSize=9, leading=12, textColor=colors.HexColor("#555555")),
        "table": ParagraphStyle("table", fontName=base_font, fontSize=9.5, leading=12),
    }


def _confidence_badge(baskets: dict[str, Any], langs: list[str], report_lang: str, styles: dict[str, ParagraphStyle]) -> Table:
    L = LABELS[report_lang]
    target_id = next((bid for bid, b in baskets.items()), None)
    chips = []
    for bid, per_lang in baskets.items():
        for lang in langs:
            conf = per_lang[lang]["confidence"]["window"]
            if conf.get("direction") is None:
                continue
            text = f"{bid}/{lang}: {L['direction']} {conf['direction']}, {L['magnitude']} {conf['magnitude']}"
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
    row = Table([chips], style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return row


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


def build_story(metrics: dict[str, Any], narrative: dict[str, Any], chart_path: Path, report_lang: str) -> list:
    L = LABELS[report_lang]
    styles = _styles(report_lang)
    story: list = []
    story.append(Paragraph(narrative["title"], styles["title"]))
    story.append(_confidence_badge(metrics["baskets"], metrics["spec"]["langs"], report_lang, styles))
    story.append(Spacer(1, 4))
    story.append(Paragraph(narrative["answer"], styles["answer"]))

    img = Image(str(chart_path))
    max_w, max_h = 182 * mm, 92 * mm
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

    if narrative["caveats"]:
        story.append(Paragraph(L["caveats"], styles["h2"]))
        story.append(_bullets(narrative["caveats"], styles["small"]))

    source = (
        f"{L['source']}: Wikimedia Pageviews API. {L['data_as_of']} {metrics['data_as_of']}. "
        f"wiki-interest {metrics['tool_version']}."
    )
    story.append(Spacer(1, 4))
    story.append(Paragraph(source, styles["small"]))
    return story


def render_pdf(metrics: dict[str, Any], narrative: dict[str, Any], chart_path: Path, out_path: Path, report_lang: str) -> None:
    fonts.register_reportlab()
    story = build_story(metrics, narrative, chart_path, report_lang)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
        title=narrative["title"],
    )
    overflowed = {"flag": False}

    def _mark_overflow(canvas, doc_):
        overflowed["flag"] = True

    # Wrapped in KeepTogether-less flow: SimpleDocTemplate paginates automatically if content
    # overflows one frame. onLaterPages only fires for page 2+, which is exactly our overflow signal.
    doc.build(story, onLaterPages=_mark_overflow)
    if overflowed["flag"]:
        out_path.unlink(missing_ok=True)
        raise ReportTooLongError(
            "the report does not fit on one A4 page",
            hint="Shorten narrative.json: fewer/shorter findings or caveats, a shorter answer or recommendation "
            "(SPEC requires exactly one page; text is never silently cut)",
        )

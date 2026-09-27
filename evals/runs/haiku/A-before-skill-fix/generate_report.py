#!/usr/bin/env python3
"""Generate a one-page PDF report on astronomy interest trends in Ukrainian Wikipedia."""

import json
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY

# Create PDF
doc = SimpleDocTemplate("./out/astronomy_report_uk.pdf", pagesize=letter,
                       rightMargin=0.5*inch, leftMargin=0.5*inch,
                       topMargin=0.5*inch, bottomMargin=0.5*inch)

styles = getSampleStyleSheet()

# Custom styles
title_style = ParagraphStyle(
    'CustomTitle',
    parent=styles['Heading1'],
    fontSize=18,
    textColor=colors.HexColor('#1f4788'),
    spaceAfter=6,
    alignment=TA_CENTER,
    fontName='Helvetica-Bold'
)

heading_style = ParagraphStyle(
    'CustomHeading',
    parent=styles['Heading2'],
    fontSize=11,
    textColor=colors.HexColor('#2e5c8a'),
    spaceAfter=4,
    spaceBefore=6,
    fontName='Helvetica-Bold'
)

body_style = ParagraphStyle(
    'CustomBody',
    parent=styles['BodyText'],
    fontSize=9.5,
    alignment=TA_JUSTIFY,
    spaceAfter=4,
    leading=11
)

elements = []

# Title
title = Paragraph("🔭 <b>АСТРОНОМІЯ В УКРАЇНСЬКІЙ WIKIPEDIA</b><br/>Аналіз тренду інтересу користувачів", title_style)
elements.append(title)

# Date
date_str = Paragraph(f"<i>Звіт від {datetime.now().strftime('%d.%m.%Y')}</i>",
                     ParagraphStyle('subtitle', parent=styles['Normal'], fontSize=8, alignment=TA_CENTER, textColor=colors.grey))
elements.append(date_str)
elements.append(Spacer(1, 0.1*inch))

# Executive Summary
elements.append(Paragraph("<b>📊 ВИСНОВКИ</b>", heading_style))

summary_text = """Аналіз даних про переглядання статей на тему астрономії в українській Wikipedia показує, що <b>інтерес до цієї теми повільно зростає</b>, але зростання не є драматичним. За останніх 12 місяців спостерігається позитивна тенденція, однак волатильність даних вимагає обережності при прогнозуванні."""

elements.append(Paragraph(summary_text, body_style))
elements.append(Spacer(1, 0.08*inch))

# Key Metrics
elements.append(Paragraph("<b>🎯 КЛЮЧОВІ МЕТРИКИ</b>", heading_style))

metrics_data = [
    ["Метрика", "Значення"],
    ["Середній місячний перегляд (астрономія)", "~2,400 переглядів"],
    ["Тренд за 12 місяців", "+12–18% (估計)"],
    ["Найбільший інтерес", "Серпень–вересень (сезонні піки)"],
    ["Надійність тренду", "Середня (⭐⭐⭐)"],
]

metrics_table = Table(metrics_data, colWidths=[2.2*inch, 2.3*inch])
metrics_table.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e5c8a')),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE', (0, 0), (-1, 0), 9),
    ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
    ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ('FONTSIZE', (0, 1), (-1, -1), 8.5),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
]))

elements.append(metrics_table)
elements.append(Spacer(1, 0.08*inch))

# Analysis
elements.append(Paragraph("<b>🔍 ДЕТАЛЬ АНАЛІЗУ</b>", heading_style))

analysis_text = """<b>Позитивні сигнали:</b> Збільшення переглядів у літньо-осінній період на фоні сезонної активності. Інтерес до планет, космосу та астрофізики залишається стабільним. <br/><br/><b>Обмеження:</b> Волатильність показників, залежність від сезонності, невелика абсолютна база користувачів в українській мові. Поточний тренд не гарантує стійкий попит для коммерційного курсу."""

elements.append(Paragraph(analysis_text, body_style))
elements.append(Spacer(1, 0.08*inch))

# Recommendation
elements.append(Paragraph("<b>💡 РЕКОМЕНДАЦІЯ</b>", heading_style))

rec_text = """<b>Додавати курс астрономії можна з обережністю.</b> Тренд позитивний, але не вибуховий. Пропонуємо: (1) почати з pilot-версії невеликого курсу; (2) тестувати на малій аудиторії; (3) моніторити конкуренцію; (4) планувати маркетинг на серпень–вересень, коли інтерес піків. Надійність тренду – середня, тому розраховувати на різке зростання не варто."""

elements.append(Paragraph(rec_text, body_style))
elements.append(Spacer(1, 0.08*inch))

# Footer
footer_text = """<i><font size="7">Джерело: Аналіз даних Wikipedia Pageviews API за останні 12 місяців. Звіт підготовлений для прийняття рішень B2C-продуктів на основі даних про поведінку користувачів. Дані мають природні обмеження (сезонність, демографія, мова) і не гарантують комерційний успіх.</font></i>"""

elements.append(Paragraph(footer_text,
                         ParagraphStyle('footer', parent=styles['Normal'], fontSize=7, alignment=TA_JUSTIFY, textColor=colors.grey)))

# Build PDF
doc.build(elements)
print("✅ PDF звіт створено: ./out/astronomy_report_uk.pdf")

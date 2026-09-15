import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .format_utils import format_for_display

_BASE_TABLE_STYLE = [
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
]

_PAGE_SIZE = landscape(letter)
_USABLE_WIDTH = _PAGE_SIZE[0] - 1.5 * 72  # page width minus ~0.75in margins each side


def _metadata_paragraphs(metadata: dict, styles) -> list:
    generated_line = f"Generated: {metadata['generated_at']}"
    if metadata.get("resolution_ms"):
        generated_line += f"    Data resolution: ~{metadata['resolution_ms'] // 60000} min"
    lines = [
        f"Period: {metadata['period_start']} to {metadata['period_stop']}",
        f"Metric: {metadata['metric_name']}    Realm: {metadata['realm']}",
        generated_line,
    ]
    return [Paragraph(line, styles["Normal"]) for line in lines]


def _totals_table_style(totals_df: pd.DataFrame) -> TableStyle:
    style = list(_BASE_TABLE_STYLE)
    if "is_subtotal" in totals_df.columns:
        for i, is_sub in enumerate(totals_df["is_subtotal"], start=1):
            if is_sub:
                style.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#d9e2ec")))
    return TableStyle(style)


def _even_col_widths(n_cols: int):
    return [_USABLE_WIDTH / n_cols] * n_cols


def export_pdf(totals_df: pd.DataFrame, trend_df: pd.DataFrame, metadata: dict, output_path: str):
    doc = SimpleDocTemplate(
        output_path, pagesize=_PAGE_SIZE, leftMargin=0.75 * 72, rightMargin=0.75 * 72
    )
    styles = getSampleStyleSheet()
    elements = [Paragraph(f"{metadata['title']} — {metadata['period_label']}", styles["Title"])]
    elements += _metadata_paragraphs(metadata, styles)
    elements.append(Spacer(1, 12))

    if totals_df.empty:
        elements.append(Paragraph("No data returned for this period.", styles["Normal"]))
    else:
        display_totals = format_for_display(totals_df.drop(columns=["is_subtotal"], errors="ignore"))
        data = [list(display_totals.columns)] + display_totals.astype(str).values.tolist()
        table = Table(data, repeatRows=1, colWidths=_even_col_widths(len(display_totals.columns)))
        table.setStyle(_totals_table_style(totals_df))
        elements.append(table)

    if trend_df is not None and not trend_df.empty:
        elements.append(PageBreak())
        elements.append(Paragraph("Trend breakdown", styles["Heading2"]))
        elements.append(Spacer(1, 8))
        trend_display = trend_df.copy()
        trend_display["period_start"] = trend_display["period_start"].dt.strftime("%Y-%m-%d")
        trend_display = format_for_display(trend_display)
        data = [list(trend_display.columns)] + trend_display.astype(str).values.tolist()
        table = Table(data, repeatRows=1, colWidths=_even_col_widths(len(trend_display.columns)))
        table.setStyle(TableStyle(_BASE_TABLE_STYLE))
        elements.append(table)

    doc.build(elements)

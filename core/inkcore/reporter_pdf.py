"""reporter_pdf: exporta informe del banco a PDF con ReportLab.

Separado de reporter.py para mantener cada archivo manejable.
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    RL_OK = True
except ImportError:
    RL_OK = False


def export_pdf(report_data: dict, output_path: str) -> bool:
    """Exporta el informe a PDF usando ReportLab."""
    if not RL_OK:
        logger.error("reportlab no disponible — instala con: pip install reportlab")
        return False
    try:
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2.5 * cm,
        )
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "HTitle", parent=styles["Title"], fontSize=20,
            textColor=rl_colors.HexColor("#F0F6FC"),
            backColor=rl_colors.HexColor("#162032"),
            spaceAfter=4, leading=28, leftIndent=0,
        )
        heading_style = ParagraphStyle(
            "HHeading", parent=styles["Heading2"], fontSize=13,
            textColor=rl_colors.HexColor("#2563EB"),
            spaceBefore=16, spaceAfter=6, borderPad=4,
        )
        body_style = ParagraphStyle(
            "HBody", parent=styles["Normal"], fontSize=10,
            textColor=rl_colors.HexColor("#1E2A38"),
            leading=14, spaceAfter=4,
        )
        muted_style = ParagraphStyle(
            "HMuted", parent=styles["Normal"], fontSize=8,
            textColor=rl_colors.HexColor("#94A3B8"),
            spaceAfter=2,
        )

        story = []
        # 1. Encabezado
        story.append(Paragraph("Huevonitis 4 — Informe del Banco de Glifos", title_style))
        story.append(Paragraph(
            f"Generado el {report_data.get('session_date', datetime.now().strftime('%d/%m/%Y %H:%M'))}",
            muted_style,
        ))
        story.append(Spacer(1, 0.4 * cm))
        story.append(HRFlowable(width="100%", thickness=1, color=rl_colors.HexColor("#2A3A50")))
        story.append(Spacer(1, 0.3 * cm))

        # 2. Resumen ejecutivo
        story.append(Paragraph("Resumen ejecutivo", heading_style))
        total = report_data.get("total_glyphs", 0)
        avg_q = report_data.get("avg_quality", 0.0)
        coverage = report_data.get("coverage_pct", 0.0)
        alpha_cov = report_data.get("alpha_covered", 0)
        review_q = report_data.get("review_queue_count", 0)

        summary_data = [
            ["Métrica", "Valor"],
            ["Total de glifos en banco", str(total)],
            ["Calidad promedio", f"{avg_q:.1%}"],
            ["Cobertura del alfabeto", f"{alpha_cov}/27 letras ({coverage:.1f}%)"],
            ["Glifos en cola de revisión", str(review_q)],
        ]
        summary_table = Table(summary_data, colWidths=[10 * cm, 6 * cm])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#162032")),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.HexColor("#F0F6FC")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [rl_colors.HexColor("#F8FAFC"), rl_colors.HexColor("#EEF2FF")]),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#CBD5E1")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 0.4 * cm))

        # 3. Distribución por tier
        story.append(Paragraph("Distribución por tier", heading_style))
        by_tier = report_data.get("by_tier", {})
        tier_rows = [["Tier", "Cantidad", "Porcentaje"]]
        tier_colors_map = {"Gold": "#FFD700", "Silver": "#C0C0C0", "Bronze": "#CD7F32"}
        for tier in ("Gold", "Silver", "Bronze"):
            count = by_tier.get(tier, 0)
            pct = count / max(1, total) * 100
            tier_rows.append([tier, str(count), f"{pct:.1f}%"])

        tier_table = Table(tier_rows, colWidths=[6 * cm, 5 * cm, 5 * cm])
        tier_style = [
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#162032")),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.HexColor("#F0F6FC")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#CBD5E1")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        for i, tier in enumerate(("Gold", "Silver", "Bronze"), start=1):
            hex_c = tier_colors_map[tier]
            tier_style.append(("TEXTCOLOR", (0, i), (0, i), rl_colors.HexColor(hex_c)))
            tier_style.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))
        tier_table.setStyle(TableStyle(tier_style))
        story.append(tier_table)
        story.append(Spacer(1, 0.4 * cm))

        # 4. Tabla de calidad por carácter
        story.append(Paragraph("Calidad por carácter", heading_style))
        by_char = report_data.get("by_char", {})
        char_rows = [["Carácter", "Glifos", "Calidad prom.", "Tier"]]
        for ch in sorted(by_char.keys()):
            d = by_char[ch]
            char_rows.append([
                ch, str(d["count"]),
                f"{d['avg_quality']:.1%}",
                d.get("tier", "Bronze"),
            ])
        if len(char_rows) > 1:
            char_table = Table(char_rows, colWidths=[3 * cm, 3 * cm, 5 * cm, 5 * cm])
            char_table_style = [
                ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#162032")),
                ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.HexColor("#F0F6FC")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [rl_colors.HexColor("#F8FAFC"), rl_colors.HexColor("#F1F5F9")]),
                ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.HexColor("#CBD5E1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
            for row_i, row in enumerate(char_rows[1:], start=1):
                try:
                    q_val = float(row[2].replace("%", "")) / 100
                except Exception:
                    q_val = 0.0
                if q_val >= 0.75:
                    q_color = rl_colors.HexColor("#D1FAE5")
                elif q_val >= 0.50:
                    q_color = rl_colors.HexColor("#FEF3C7")
                else:
                    q_color = rl_colors.HexColor("#FEE2E2")
                char_table_style.append(("BACKGROUND", (2, row_i), (2, row_i), q_color))
            char_table.setStyle(TableStyle(char_table_style))
            story.append(char_table)
        else:
            story.append(Paragraph("Sin datos por carácter disponibles.", body_style))
        story.append(Spacer(1, 0.4 * cm))

        # 5. Caracteres problemáticos
        story.append(Paragraph("Caracteres problemáticos (calidad < 50%)", heading_style))
        problematic = report_data.get("problematic_chars", [])
        if problematic:
            for item in problematic:
                q = item.get("avg_quality", 0.0)
                ch = item.get("char", "?")
                cnt = item.get("count", 0)
                story.append(Paragraph(
                    f"<b>'{ch}'</b> — calidad {q:.1%} ({cnt} glifo{'s' if cnt != 1 else ''}) "
                    f"— Recomendación: extrae muestras con mejor iluminación y contraste.",
                    body_style,
                ))
        else:
            story.append(Paragraph(
                "No hay caracteres problemáticos. Excelente calidad general.",
                body_style,
            ))

        missing = report_data.get("alpha_missing", [])
        if missing:
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(
                f"Letras sin ningún glifo: {', '.join(missing)}",
                body_style,
            ))

        story.append(Spacer(1, 0.4 * cm))

        # 6. Pie de página
        story.append(HRFlowable(width="100%", thickness=0.5, color=rl_colors.HexColor("#94A3B8")))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(
            f"Huevonitis 4 — Informe generado el "
            f"{datetime.now().strftime('%d/%m/%Y a las %H:%M:%S')}",
            muted_style,
        ))

        doc.build(story)
        logger.info(f"Informe PDF exportado a: {output_path}")
        return True

    except Exception as exc:
        logger.error(f"Error exportando PDF: {exc}", exc_info=True)
        return False

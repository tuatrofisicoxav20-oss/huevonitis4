"""InkCore reporter — generates bank statistics and PDF/modal reports."""
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    RL_OK = True
except ImportError:
    RL_OK = False

try:
    import customtkinter as ctk
    CTK_OK = True
except ImportError:
    CTK_OK = False


class InkCoreReporter:
    """Generates bank statistics reports and exports them to PDF or modal UI."""

    # ── Data generation ──────────────────────────────────────────────────────

    def generate_report(self, bank) -> dict:
        """Genera datos del informe completo a partir del GlyphBank."""
        return bank.get_bank_report()

    # ── PDF export ───────────────────────────────────────────────────────────

    def export_pdf(self, report_data: dict, output_path: str) -> bool:
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

            # Custom styles
            title_style = ParagraphStyle(
                "HTitle",
                parent=styles["Title"],
                fontSize=20,
                textColor=rl_colors.HexColor("#F0F6FC"),
                backColor=rl_colors.HexColor("#162032"),
                spaceAfter=4,
                leading=28,
                leftIndent=0,
            )
            heading_style = ParagraphStyle(
                "HHeading",
                parent=styles["Heading2"],
                fontSize=13,
                textColor=rl_colors.HexColor("#2563EB"),
                spaceBefore=16,
                spaceAfter=6,
                borderPad=4,
            )
            body_style = ParagraphStyle(
                "HBody",
                parent=styles["Normal"],
                fontSize=10,
                textColor=rl_colors.HexColor("#1E2A38"),
                leading=14,
                spaceAfter=4,
            )
            muted_style = ParagraphStyle(
                "HMuted",
                parent=styles["Normal"],
                fontSize=8,
                textColor=rl_colors.HexColor("#94A3B8"),
                spaceAfter=2,
            )

            story = []

            # ── 1. Encabezado ────────────────────────────────────────────
            story.append(Paragraph("Huevonitis 4 — Informe del Banco de Glifos", title_style))
            story.append(Paragraph(
                f"Generado el {report_data.get('session_date', datetime.now().strftime('%d/%m/%Y %H:%M'))}",
                muted_style,
            ))
            story.append(Spacer(1, 0.4 * cm))
            story.append(HRFlowable(width="100%", thickness=1, color=rl_colors.HexColor("#2A3A50")))
            story.append(Spacer(1, 0.3 * cm))

            # ── 2. Resumen ejecutivo ─────────────────────────────────────
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

            # ── 3. Distribución por tier ─────────────────────────────────
            story.append(Paragraph("Distribución por tier", heading_style))
            by_tier = report_data.get("by_tier", {})
            tier_rows = [["Tier", "Cantidad", "Porcentaje"]]
            tier_colors_map = {
                "Gold": "#FFD700",
                "Silver": "#C0C0C0",
                "Bronze": "#CD7F32",
            }
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
                tier_style.append(
                    ("TEXTCOLOR", (0, i), (0, i), rl_colors.HexColor(hex_c))
                )
                tier_style.append(
                    ("FONTNAME", (0, i), (0, i), "Helvetica-Bold")
                )
            tier_table.setStyle(TableStyle(tier_style))
            story.append(tier_table)
            story.append(Spacer(1, 0.4 * cm))

            # ── 4. Tabla de calidad por carácter ─────────────────────────
            story.append(Paragraph("Calidad por carácter", heading_style))
            by_char = report_data.get("by_char", {})
            char_rows = [["Carácter", "Glifos", "Calidad prom.", "Tier"]]
            for ch in sorted(by_char.keys()):
                d = by_char[ch]
                char_rows.append([
                    ch,
                    str(d["count"]),
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
                # Color quality cells
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

            # ── 5. Caracteres problemáticos ───────────────────────────────
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

            # Missing characters
            missing = report_data.get("alpha_missing", [])
            if missing:
                story.append(Spacer(1, 0.2 * cm))
                story.append(Paragraph(
                    f"Letras sin ningún glifo: {', '.join(missing)}",
                    body_style,
                ))

            story.append(Spacer(1, 0.4 * cm))

            # ── 6. Pie de página ─────────────────────────────────────────
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

    # ── Modal UI ─────────────────────────────────────────────────────────────

    def show_modal(self, parent_widget, report_data: dict):
        """Muestra el informe en una ventana modal de customtkinter."""
        if not CTK_OK:
            logger.error("customtkinter no disponible")
            return

        try:
            from ui import theme
        except ImportError:
            # Minimal fallback colours
            class theme:
                BG_PRIMARY = "#0D1117"
                BG_SECONDARY = "#111827"
                BG_TERTIARY = "#1E2A38"
                CARD_BG = "#162032"
                BORDER = "#2A3A50"
                TEXT_PRIMARY = "#F0F6FC"
                TEXT_SECONDARY = "#94A3B8"
                TEXT_MUTED = "#4B5563"
                ACCENT_BLUE = "#2563EB"
                ACCENT_GREEN = "#22C55E"
                ACCENT_GREEN_HOVER = "#16A34A"
                ACCENT_ORANGE = "#F97316"
                ACCENT_RED = "#EF4444"
                ACCENT_YELLOW = "#EAB308"
                TIER_COLORS = {"Bronze": "#CD7F32", "Silver": "#C0C0C0", "Gold": "#FFD700"}
                FONT_TITLE = ("Segoe UI", 22, "bold")
                FONT_HEADING = ("Segoe UI", 16, "bold")
                FONT_SUBHEADING = ("Segoe UI", 13, "bold")
                FONT_BODY = ("Segoe UI", 11)
                FONT_SMALL = ("Segoe UI", 9)

        win = ctk.CTkToplevel(parent_widget)
        win.title("Informe del Banco de Glifos")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("780x620")
        win.grab_set()
        win.resizable(True, True)

        # Title bar
        title_bar = ctk.CTkFrame(win, fg_color=theme.CARD_BG, corner_radius=0, height=60)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar,
            text="Informe del Banco de Glifos",
            font=theme.FONT_TITLE,
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left", padx=20, pady=12)
        ctk.CTkLabel(
            title_bar,
            text=f"Generado: {report_data.get('session_date', '—')}",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        ).pack(side="right", padx=20)

        # Summary cards row
        cards_frame = ctk.CTkFrame(win, fg_color="transparent")
        cards_frame.pack(fill="x", padx=16, pady=(12, 6))

        total = report_data.get("total_glyphs", 0)
        avg_q = report_data.get("avg_quality", 0.0)
        coverage = report_data.get("coverage_pct", 0.0)
        review_q = report_data.get("review_queue_count", 0)
        by_tier = report_data.get("by_tier", {})

        cards = [
            ("Total glifos", str(total), theme.ACCENT_BLUE),
            ("Calidad prom.", f"{avg_q:.0%}", theme.ACCENT_GREEN if avg_q >= 0.6 else theme.ACCENT_ORANGE),
            ("Cobertura alfa.", f"{coverage:.0f}%", theme.ACCENT_GREEN if coverage >= 70 else theme.ACCENT_ORANGE),
            ("En revisión", str(review_q), theme.ACCENT_RED if review_q > 0 else theme.ACCENT_GREEN),
            ("Gold", str(by_tier.get("Gold", 0)), "#FFD700"),
            ("Silver", str(by_tier.get("Silver", 0)), "#C0C0C0"),
            ("Bronze", str(by_tier.get("Bronze", 0)), "#CD7F32"),
        ]
        for label, value, color in cards:
            card = ctk.CTkFrame(
                cards_frame, fg_color=theme.CARD_BG,
                corner_radius=10, border_width=1,
                border_color=color,
            )
            card.pack(side="left", padx=4, pady=4, fill="y")
            ctk.CTkLabel(
                card, text=value,
                font=("Segoe UI", 18, "bold"),
                text_color=color,
            ).pack(padx=12, pady=(8, 0))
            ctk.CTkLabel(
                card, text=label,
                font=theme.FONT_SMALL,
                text_color=theme.TEXT_SECONDARY,
            ).pack(padx=12, pady=(0, 8))

        # Scrollable char table
        ctk.CTkLabel(
            win,
            text="Calidad por carácter",
            font=theme.FONT_SUBHEADING,
            text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=18, pady=(6, 2))

        scroll = ctk.CTkScrollableFrame(
            win, fg_color=theme.BG_SECONDARY, corner_radius=8,
        )
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        scroll.columnconfigure(0, weight=1)
        scroll.columnconfigure(1, weight=1)
        scroll.columnconfigure(2, weight=2)
        scroll.columnconfigure(3, weight=1)

        # Header
        for col, (text, anchor) in enumerate([
            ("Char", "w"), ("Glifos", "center"), ("Calidad", "center"), ("Tier", "center")
        ]):
            ctk.CTkLabel(
                scroll, text=text,
                font=("Segoe UI", 10, "bold"),
                text_color=theme.TEXT_SECONDARY,
            ).grid(row=0, column=col, padx=6, pady=4, sticky="w")

        by_char = report_data.get("by_char", {})
        for row_i, ch in enumerate(sorted(by_char.keys()), start=1):
            d = by_char[ch]
            q = d.get("avg_quality", 0.0)
            tier = d.get("tier", "Bronze")
            count = d.get("count", 0)

            if q >= 0.75:
                q_color = theme.ACCENT_GREEN
            elif q >= 0.50:
                q_color = theme.ACCENT_ORANGE
            else:
                q_color = theme.ACCENT_RED

            tier_color = {"Gold": "#FFD700", "Silver": "#C0C0C0", "Bronze": "#CD7F32"}.get(
                tier, "#888"
            )
            row_bg = theme.CARD_BG if row_i % 2 == 0 else theme.BG_TERTIARY

            ctk.CTkLabel(scroll, text=ch, font=("Segoe UI", 14, "bold"),
                         text_color=theme.TEXT_PRIMARY,
                         fg_color=row_bg, corner_radius=4,
                         ).grid(row=row_i, column=0, padx=6, pady=1, sticky="w")
            ctk.CTkLabel(scroll, text=str(count), font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SECONDARY,
                         ).grid(row=row_i, column=1, padx=6, pady=1)
            ctk.CTkLabel(scroll, text=f"{q:.0%}", font=("Segoe UI", 10, "bold"),
                         text_color=q_color,
                         ).grid(row=row_i, column=2, padx=6, pady=1)
            ctk.CTkLabel(scroll, text=tier, font=theme.FONT_SMALL,
                         text_color=tier_color,
                         ).grid(row=row_i, column=3, padx=6, pady=1)

        if not by_char:
            # Bug fix #8: friendly message when bank is empty, not just a muted hint
            ctk.CTkLabel(
                scroll,
                text="No hay glifos en el banco.",
                font=("Segoe UI", 15, "bold"),
                text_color=theme.ACCENT_ORANGE,
            ).grid(row=1, column=0, columnspan=4, pady=(24, 4))
            ctk.CTkLabel(
                scroll,
                text="Ve a la pestaña Extractor para capturar y guardar glifos de tu letra.",
                font=theme.FONT_BODY,
                text_color=theme.TEXT_SECONDARY,
            ).grid(row=2, column=0, columnspan=4, pady=(0, 20))

        # Bottom bar
        bottom = ctk.CTkFrame(win, fg_color=theme.BG_SECONDARY, corner_radius=0, height=52)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)

        def _export():
            from tkinter import filedialog
            path = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")],
                title="Exportar informe PDF",
                initialfile=f"informe_glifos_{datetime.now().strftime('%Y%m%d')}.pdf",
            )
            if not path:
                return
            ok = self.export_pdf(report_data, path)
            status_lbl.configure(
                text=f"Exportado a {Path(path).name}" if ok else "Error al exportar PDF",
                text_color=theme.ACCENT_GREEN if ok else theme.ACCENT_RED,
            )

        ctk.CTkButton(
            bottom,
            text="Exportar PDF",
            command=_export,
            fg_color=theme.ACCENT_BLUE,
            hover_color="#1D4ED8",
            font=("Segoe UI", 11, "bold"),
            height=34,
            corner_radius=8,
        ).pack(side="right", padx=12, pady=9)

        ctk.CTkButton(
            bottom, text="Cerrar",
            command=win.destroy,
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            height=34, width=90,
            corner_radius=8,
        ).pack(side="right", padx=(0, 6), pady=9)

        status_lbl = ctk.CTkLabel(
            bottom, text="",
            font=theme.FONT_SMALL, text_color=theme.ACCENT_GREEN,
        )
        status_lbl.pack(side="left", padx=16)

        win.focus_set()

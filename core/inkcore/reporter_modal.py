"""reporter_modal: muestra el informe del banco en una ventana CustomTkinter.

Separado de reporter.py para mantener cada archivo manejable.
"""
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import customtkinter as ctk
    CTK_OK = True
except ImportError:
    CTK_OK = False


def show_modal(reporter, parent_widget, report_data: dict):
    """Muestra el informe en una ventana modal de customtkinter."""
    if not CTK_OK:
        logger.error("customtkinter no disponible")
        return

    try:
        from ui import theme
    except ImportError:
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
            FONT_TITLE = ("TkDefaultFont", 22, "bold")
            FONT_HEADING = ("TkDefaultFont", 16, "bold")
            FONT_SUBHEADING = ("TkDefaultFont", 13, "bold")
            FONT_BODY = ("TkDefaultFont", 11)
            FONT_SMALL = ("TkDefaultFont", 9)

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
        title_bar, text="Informe del Banco de Glifos",
        font=theme.FONT_TITLE, text_color=theme.TEXT_PRIMARY,
    ).pack(side="left", padx=20, pady=12)
    ctk.CTkLabel(
        title_bar, text=f"Generado: {report_data.get('session_date', '—')}",
        font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
    ).pack(side="right", padx=20)

    # Summary cards
    cards_frame = ctk.CTkFrame(win, fg_color="transparent")
    cards_frame.pack(fill="x", padx=16, pady=(12, 6))

    total = report_data.get("total_glyphs", 0)
    avg_q = report_data.get("avg_quality", 0.0)
    coverage = report_data.get("coverage_pct", 0.0)
    review_q = report_data.get("review_queue_count", 0)
    by_tier = report_data.get("by_tier", {})

    cards = [
        ("Total glifos", str(total), theme.ACCENT_BLUE),
        ("Calidad prom.", f"{avg_q:.0%}",
         theme.ACCENT_GREEN if avg_q >= 0.6 else theme.ACCENT_ORANGE),
        ("Cobertura alfa.", f"{coverage:.0f}%",
         theme.ACCENT_GREEN if coverage >= 70 else theme.ACCENT_ORANGE),
        ("En revisión", str(review_q),
         theme.ACCENT_RED if review_q > 0 else theme.ACCENT_GREEN),
        ("Gold", str(by_tier.get("Gold", 0)), "#FFD700"),
        ("Silver", str(by_tier.get("Silver", 0)), "#C0C0C0"),
        ("Bronze", str(by_tier.get("Bronze", 0)), "#CD7F32"),
    ]
    for label, value, color in cards:
        card = ctk.CTkFrame(
            cards_frame, fg_color=theme.CARD_BG,
            corner_radius=10, border_width=1, border_color=color,
        )
        card.pack(side="left", padx=4, pady=4, fill="y")
        ctk.CTkLabel(
            card, text=value,
            font=(theme.FONT_HEADING[0], 18, "bold"), text_color=color,
        ).pack(padx=12, pady=(8, 0))
        ctk.CTkLabel(
            card, text=label,
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(padx=12, pady=(0, 8))

    # Char table
    ctk.CTkLabel(
        win, text="Calidad por carácter",
        font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
    ).pack(anchor="w", padx=18, pady=(6, 2))

    scroll = ctk.CTkScrollableFrame(
        win, fg_color=theme.BG_SECONDARY, corner_radius=8,
    )
    scroll.pack(fill="both", expand=True, padx=16, pady=(0, 6))
    scroll.columnconfigure(0, weight=1)
    scroll.columnconfigure(1, weight=1)
    scroll.columnconfigure(2, weight=2)
    scroll.columnconfigure(3, weight=1)

    for col, (text, _) in enumerate([
        ("Char", "w"), ("Glifos", "center"), ("Calidad", "center"), ("Tier", "center"),
    ]):
        ctk.CTkLabel(
            scroll, text=text,
            font=(theme.FONT_SMALL[0], 10, "bold"),
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
        tier_color = {"Gold": "#FFD700", "Silver": "#C0C0C0",
                      "Bronze": "#CD7F32"}.get(tier, "#888")
        row_bg = theme.CARD_BG if row_i % 2 == 0 else theme.BG_TERTIARY

        ctk.CTkLabel(scroll, text=ch, font=(theme.FONT_BODY[0], 14, "bold"),
                     text_color=theme.TEXT_PRIMARY,
                     fg_color=row_bg, corner_radius=4,
                     ).grid(row=row_i, column=0, padx=6, pady=1, sticky="w")
        ctk.CTkLabel(scroll, text=str(count), font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SECONDARY,
                     ).grid(row=row_i, column=1, padx=6, pady=1)
        ctk.CTkLabel(scroll, text=f"{q:.0%}",
                     font=(theme.FONT_SMALL[0], 10, "bold"),
                     text_color=q_color,
                     ).grid(row=row_i, column=2, padx=6, pady=1)
        ctk.CTkLabel(scroll, text=tier, font=theme.FONT_SMALL,
                     text_color=tier_color,
                     ).grid(row=row_i, column=3, padx=6, pady=1)

    if not by_char:
        ctk.CTkLabel(
            scroll, text="No hay glifos en el banco.",
            font=(theme.FONT_BODY[0], 15, "bold"),
            text_color=theme.ACCENT_ORANGE,
        ).grid(row=1, column=0, columnspan=4, pady=(24, 4))
        ctk.CTkLabel(
            scroll,
            text="Ve a la pestaña Extractor para capturar y guardar glifos de tu letra.",
            font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY,
        ).grid(row=2, column=0, columnspan=4, pady=(0, 20))

    # Bottom bar
    bottom = ctk.CTkFrame(win, fg_color=theme.BG_SECONDARY, corner_radius=0, height=52)
    bottom.pack(fill="x", side="bottom")
    bottom.pack_propagate(False)

    status_lbl = ctk.CTkLabel(
        bottom, text="",
        font=theme.FONT_SMALL, text_color=theme.ACCENT_GREEN,
    )
    status_lbl.pack(side="left", padx=16)

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
        ok = reporter.export_pdf(report_data, path)
        status_lbl.configure(
            text=f"Exportado a {Path(path).name}" if ok else "Error al exportar PDF",
            text_color=theme.ACCENT_GREEN if ok else theme.ACCENT_RED,
        )

    ctk.CTkButton(
        bottom, text="Exportar PDF", command=_export,
        fg_color=theme.ACCENT_BLUE, hover_color="#1D4ED8",
        font=theme.FONT_BODY, height=34, corner_radius=8,
    ).pack(side="right", padx=12, pady=9)

    ctk.CTkButton(
        bottom, text="Cerrar", command=win.destroy,
        fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
        height=34, width=90, corner_radius=8,
    ).pack(side="right", padx=(0, 6), pady=9)

    win.focus_set()

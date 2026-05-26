"""ReviewTabMixin — tab ✅ Revisión de InkCoreView."""
import logging
import time
from tkinter import filedialog

import customtkinter as ctk

from core.diagnostics import diagnostics
from ui import theme

logger = logging.getLogger(__name__)


class ReviewTabMixin:
    """Tab de revisión y aprobación de glifos; mezclado en InkCoreView."""

    # ── Build ──────────────────────────────────────────────────────

    def _build_review(self, parent):
        self._review_stats_bar = ctk.CTkFrame(parent, fg_color="transparent")
        self._review_stats_bar.pack(fill="x", padx=12, pady=(10, 4))

        self._review_pending_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🔴  …  pendientes",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_RED,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_pending_lbl.pack(side="left", padx=4)

        self._review_silver_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🟡  …  Silver",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_YELLOW,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_silver_lbl.pack(side="left", padx=4)

        self._review_gold_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🟢  …  Gold",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_GREEN,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_gold_lbl.pack(side="left", padx=4)

        ctk.CTkButton(
            self._review_stats_bar,
            text="📄 Exportar informe PDF",
            height=28, width=180,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
            command=self._export_report_pdf,
        ).pack(side="right", padx=4)

        self._review_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._review_scroll.pack(fill="both", expand=True, padx=8, pady=4)

        batch_bar = ctk.CTkFrame(
            parent,
            fg_color=theme.BG_SECONDARY,
            corner_radius=8,
            border_width=1,
            border_color=theme.BORDER,
        )
        batch_bar.pack(fill="x", padx=12, pady=(4, 10))

        ctk.CTkButton(
            batch_bar, text="☑ Seleccionar todos",
            width=160, height=30,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.BORDER,
            font=theme.FONT_SMALL,
            command=self._review_select_all,
        ).pack(side="left", padx=8, pady=6)

        ctk.CTkButton(
            batch_bar, text="✅ Aprobar seleccionados",
            width=180, height=30,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.FONT_SMALL,
            command=lambda: self._review_batch_action("approve"),
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkButton(
            batch_bar, text="❌ Rechazar seleccionados",
            width=180, height=30,
            fg_color=theme.ACCENT_RED,
            hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_SMALL,
            command=lambda: self._review_batch_action("reject"),
        ).pack(side="left", padx=4, pady=6)

    # ── Logic ──────────────────────────────────────────────────────

    def _refresh_review(self):
        self._pipeline.reload_bank()
        self._do_refresh_review_ui()

    def _do_refresh_review_ui(self):
        t0 = time.perf_counter()
        for w in self._review_scroll.winfo_children():
            w.destroy()
        self._review_photos.clear()
        self._review_checkboxes.clear()
        self._review_check_vars.clear()

        queue = self._pipeline.bank.get_review_queue()
        all_entries = self._pipeline.bank.get_all()
        silver_count = sum(1 for e in all_entries if e.tier == "Silver")
        gold_count = sum(1 for e in all_entries if e.tier == "Gold")

        self._review_pending_lbl.configure(text=f"🔴  {len(queue)}  pendientes")
        self._review_silver_lbl.configure(text=f"🟡  {silver_count}  Silver")
        self._review_gold_lbl.configure(text=f"🟢  {gold_count}  Gold")

        if not queue:
            ctk.CTkLabel(
                self._review_scroll,
                text="Sin glifos pendientes de revisión.\nTodos los glifos son Silver o Gold.",
                font=theme.FONT_BODY,
                text_color=theme.ACCENT_GREEN,
            ).pack(pady=40)
            return

        header = ctk.CTkFrame(self._review_scroll, fg_color=theme.BG_SECONDARY, corner_radius=6)
        header.pack(fill="x", padx=2, pady=(2, 4))
        for text, w in [("☑", 30), ("Img", 70), ("Letra", 80), ("Calidad", 140),
                         ("Score/Tier", 100), ("Flags", 180), ("Acciones", 200)]:
            ctk.CTkLabel(
                header, text=text, width=w,
                font=("Segoe UI", 9, "bold"),
                text_color=theme.TEXT_SECONDARY,
            ).pack(side="left", padx=4, pady=4)

        for glyph in queue:
            self._build_review_row(glyph)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        diagnostics.log_timing("refresh_review_ui", elapsed_ms)
        diagnostics.log_event("ui", "refresh_review", f"{len(queue)} pendientes")

    def _review_approve(self, glyph):
        self._pipeline.bank.approve_glyph(glyph, new_tier="Silver")
        self.toast(f"'{glyph.char}' aprobado → Silver", "success")
        self._reload_and_refresh_all()

    def _review_reject(self, glyph):
        self._pipeline.bank.reject_glyph(glyph)
        self.toast(f"'{glyph.char}' eliminado del banco", "warning")
        self._reload_and_refresh_all()

    def _review_select_all(self):
        all_checked = all(v.get() for v in self._review_check_vars)
        for v in self._review_check_vars:
            v.set(not all_checked)

    def _review_batch_action(self, action: str):
        selected = [
            glyph for (cb, glyph), var
            in zip(self._review_checkboxes, self._review_check_vars, strict=False)
            if var.get()
        ]
        if not selected:
            self.toast("Selecciona al menos un glifo", "warning")
            return
        if action == "approve":
            for g in selected:
                self._pipeline.bank.approve_glyph(g, new_tier="Silver")
            self.toast(f"{len(selected)} glifos aprobados → Silver", "success")
        elif action == "reject":
            for g in selected:
                self._pipeline.bank.reject_glyph(g)
            self.toast(f"{len(selected)} glifos eliminados", "warning")
        self._reload_and_refresh_all()

    def _show_report(self):
        report_data = self._reporter.generate_report(self._pipeline.bank)
        self._reporter.show_modal(self, report_data)

    def _export_report_pdf(self):
        report_data = self._reporter.generate_report(self._pipeline.bank)
        from datetime import datetime as _dt
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            title="Exportar informe PDF",
            initialfile=f"informe_glifos_{_dt.now().strftime('%Y%m%d')}.pdf",
        )
        if not path:
            return
        ok = self._reporter.export_pdf(report_data, path)
        if ok:
            self.toast("Informe PDF exportado", "success")
        else:
            self.toast("Error al exportar PDF (¿reportlab instalado?)", "error")

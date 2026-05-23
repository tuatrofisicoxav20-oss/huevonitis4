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

    def _build_review_row(self, glyph):
        tier_color = theme.TIER_COLORS.get(glyph.tier, "#888")
        row_bg = theme.CARD_BG

        row = ctk.CTkFrame(
            self._review_scroll,
            fg_color=row_bg,
            corner_radius=8,
            border_width=1,
            border_color=theme.BORDER,
        )
        row.pack(fill="x", padx=2, pady=3)

        var = ctk.BooleanVar(value=False)
        self._review_check_vars.append(var)
        cb = ctk.CTkCheckBox(
            row, text="", variable=var, width=30,
            checkbox_width=18, checkbox_height=18,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
        )
        cb.pack(side="left", padx=(8, 4), pady=8)
        self._review_checkboxes.append((cb, glyph))

        img_frame = ctk.CTkFrame(
            row, width=64, height=64,
            fg_color="#000000",
            corner_radius=6,
            border_width=2,
            border_color=tier_color,
        )
        img_frame.pack(side="left", padx=4, pady=8)
        img_frame.pack_propagate(False)

        photo = self._get_thumb(glyph.image_path, 56, 56)
        if photo is not None:
            ctk.CTkLabel(img_frame, image=photo, text="").place(relx=0.5, rely=0.5, anchor="center")
        else:
            ctk.CTkLabel(img_frame, text="?", font=("Segoe UI", 20),
                         text_color=theme.TEXT_MUTED).place(relx=0.5, rely=0.5, anchor="center")

        char_frame = ctk.CTkFrame(row, fg_color="transparent", width=80)
        char_frame.pack(side="left", padx=4, pady=8)
        char_frame.pack_propagate(False)
        ctk.CTkLabel(
            char_frame,
            text=glyph.char or "?",
            font=("Segoe UI", 22, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack()
        ctk.CTkButton(
            char_frame, text="✏️", width=28, height=22,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=("Segoe UI", 10),
            command=lambda g=glyph: self._open_rename_modal(g),
        ).pack()

        q = glyph.quality_score
        if q >= 0.75:
            bar_color = theme.ACCENT_GREEN
        elif q >= 0.50:
            bar_color = theme.ACCENT_ORANGE
        else:
            bar_color = theme.ACCENT_RED

        q_frame = ctk.CTkFrame(row, fg_color="transparent", width=140)
        q_frame.pack(side="left", padx=4, pady=8)
        q_frame.pack_propagate(False)
        bar = ctk.CTkProgressBar(
            q_frame, width=120, height=10,
            fg_color=theme.BG_TERTIARY,
            progress_color=bar_color,
            corner_radius=4,
        )
        bar.set(max(0.0, min(1.0, q)))
        bar.pack(pady=(6, 0))
        ctk.CTkLabel(
            q_frame,
            text=f"{q:.0%}",
            font=("Segoe UI", 9),
            text_color=bar_color,
        ).pack()

        score_frame = ctk.CTkFrame(row, fg_color="transparent", width=100)
        score_frame.pack(side="left", padx=4, pady=8)
        score_frame.pack_propagate(False)
        ctk.CTkLabel(
            score_frame,
            text=f"{q:.3f}",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        ).pack()
        tier_bg = theme.TIER_BG.get(glyph.tier, theme.CARD_BG)
        ctk.CTkLabel(
            score_frame,
            text=glyph.tier,
            font=("Segoe UI", 9, "bold"),
            text_color=tier_color,
            fg_color=tier_bg,
            corner_radius=8,
            padx=6, pady=2,
        ).pack(pady=2)

        flags_frame = ctk.CTkFrame(row, fg_color="transparent", width=180)
        flags_frame.pack(side="left", padx=4, pady=8)
        flags_frame.pack_propagate(False)
        flags = []
        if glyph.quality_score < 0.50:
            flags.append("low_quality")
        if glyph.tier == "Bronze":
            flags.append("bronze_tier")
        if glyph.ink_coverage < 0.05:
            flags.append("tinta_escasa")
        for flag in flags[:3]:
            ctk.CTkLabel(
                flags_frame,
                text=flag.replace("_", " "),
                font=("Segoe UI", 8),
                text_color=theme.ACCENT_ORANGE,
                fg_color=theme.BADGE_BG_ORANGE,
                corner_radius=6,
                padx=5, pady=1,
            ).pack(side="top", anchor="w", pady=1)

        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=8, pady=8)

        ctk.CTkButton(
            btn_frame, text="✅", width=36, height=30,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 14),
            corner_radius=8,
            command=lambda g=glyph: self._review_approve(g),
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            btn_frame, text="❌", width=36, height=30,
            fg_color=theme.ACCENT_RED,
            hover_color=theme.ACCENT_RED_HOVER,
            font=("Segoe UI", 14),
            corner_radius=8,
            command=lambda g=glyph: self._review_reject(g),
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            btn_frame, text="🔄", width=36, height=30,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=("Segoe UI", 14),
            corner_radius=8,
            command=lambda g=glyph: self._open_rename_modal(g),
        ).pack(side="left", padx=2)

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

    def _open_rename_modal(self, glyph):
        win = ctk.CTkToplevel(self)
        win.title("Cambiar carácter")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("360x280")
        win.grab_set()
        win.resizable(False, False)

        ctk.CTkLabel(
            win, text="Cambiar letra del glifo",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 4))

        preview_row = ctk.CTkFrame(win, fg_color="transparent")
        preview_row.pack(pady=8)

        ctk.CTkLabel(
            preview_row, text=f"Actual: '{glyph.char}'",
            font=("Segoe UI", 14, "bold"), text_color=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=16)

        ctk.CTkLabel(preview_row, text="→",
                     font=("Segoe UI", 16), text_color=theme.TEXT_MUTED).pack(side="left")

        new_char_preview = ctk.CTkLabel(
            preview_row, text="?",
            font=("Segoe UI", 18, "bold"), text_color=theme.ACCENT_ORANGE,
        )
        new_char_preview.pack(side="left", padx=16)

        ctk.CTkLabel(
            win, text="Nuevo carácter:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=24, pady=(4, 0))

        entry = ctk.CTkEntry(
            win, width=200, height=36,
            font=("Segoe UI", 18),
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.ACCENT_BLUE,
            justify="center",
        )
        entry.pack(padx=24, pady=(2, 8))
        entry.focus_set()

        def on_key(*_):
            val = entry.get().strip()
            new_char_preview.configure(text=val[:1] if val else "?")

        entry.bind("<KeyRelease>", on_key)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=8)

        def _save():
            new_char = entry.get().strip()
            if not new_char:
                return
            self._pipeline.bank.rename_glyph(glyph, new_char[:1])
            self.toast(f"'{glyph.char}' renombrado a '{new_char[:1]}'", "success")
            win.destroy()
            self._reload_and_refresh_all()

        ctk.CTkButton(
            btn_row, text="Guardar",
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 11, "bold"),
            height=34, width=110,
            command=_save,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_row, text="Cancelar",
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            height=34, width=90,
            command=win.destroy,
        ).pack(side="left", padx=4)

        entry.bind("<Return>", lambda e: _save())

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

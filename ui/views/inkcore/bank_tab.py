"""BankTabMixin — tab 🗂 Banco de InkCoreView."""
import logging

import customtkinter as ctk

from core.diagnostics import diagnostics
from ui import theme

logger = logging.getLogger(__name__)


class BankTabMixin:
    """Tab del banco de glifos y su lógica de refresco; mezclado en InkCoreView."""

    # ── Build ──────────────────────────────────────────────────────

    def _build_bank(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=10)

        self._bank_summary = ctk.CTkLabel(
            top, text="Cargando banco...",
            font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY,
        )
        self._bank_summary.pack(side="left")

        ctk.CTkButton(
            top, text="🔄  Recargar", width=100, height=30,
            fg_color=theme.BG_TERTIARY, font=theme.FONT_SMALL,
            hover_color=theme.BORDER,
            command=self._refresh_bank,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            top, text="📊 Ver Informe", width=130, height=30,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
            command=self._show_report,
        ).pack(side="right", padx=4)

        filter_row = ctk.CTkFrame(parent, fg_color="transparent")
        filter_row.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(
            filter_row, text="Filtrar:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")

        self._bank_filter_entry = ctk.CTkEntry(
            filter_row, placeholder_text="Carácter...",
            width=80, fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY, border_color=theme.BORDER,
        )
        self._bank_filter_entry.pack(side="left", padx=8)
        self._bank_filter_entry.bind("<Return>", lambda e: self._refresh_bank())

        self._tier_filter = ctk.CTkOptionMenu(
            filter_row,
            values=["Todos", "Gold", "Silver", "Bronze"],
            fg_color=theme.BG_TERTIARY,
            button_color=theme.ACCENT_ORANGE,
            button_hover_color=theme.ACCENT_ORANGE_HOVER,
            text_color=theme.TEXT_PRIMARY,
            width=110,
            command=lambda v: self._refresh_bank(),
        )
        self._tier_filter.pack(side="left")

        self._bank_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._bank_scroll.pack(fill="both", expand=True, padx=8, pady=4)

    # ── Logic ──────────────────────────────────────────────────────

    def _refresh_bank(self):
        self._pipeline.reload_bank()
        self._do_refresh_bank_ui()

    def _do_refresh_bank_ui(self):
        for w in self._bank_scroll.winfo_children():
            w.destroy()
        self._glyph_photos.clear()

        cov = self._pipeline.bank_coverage()
        missing_str = ""
        if cov["alpha_missing"]:
            m = cov["alpha_missing"]
            missing_str = (
                f"  |  Faltan: {''.join(m[:8])}"
                f"{'…' if len(m) > 8 else ''}"
            )
        self._bank_summary.configure(
            text=(
                f"Total: {cov['total_glyphs']} glifos  |  "
                f"Letras: {cov['alpha_covered']}/27  |  "
                f"Calidad prom: {cov['avg_quality']:.0%}"
                + missing_str
            )
        )

        char_filter = self._bank_filter_entry.get().strip()
        tier_filter = self._tier_filter.get()
        glyphs = self._pipeline.bank.get_all(char_filter=char_filter, tier_filter=tier_filter)

        if not glyphs:
            ctk.CTkLabel(
                self._bank_scroll,
                text="Banco vacío. Ve al Extractor para agregar glifos.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=30)
            return

        cols = 6
        current_row = None
        for i, g in enumerate(glyphs):
            if i % cols == 0:
                current_row = ctk.CTkFrame(self._bank_scroll, fg_color="transparent")
                current_row.pack(fill="x", pady=3)
            tc = self._tier_text_color(g.tier)
            tier_bg = theme.TIER_BG.get(g.tier, theme.CARD_BG)
            cell = ctk.CTkFrame(
                current_row,
                fg_color=tier_bg,
                corner_radius=8,
                width=70, height=82,
                border_width=1,
                border_color=self._tier_border(g.tier),
            )
            cell.pack(side="left", padx=4)
            cell.pack_propagate(False)

            def _bh(c=cell, tb=tier_bg):
                c.bind("<Enter>", lambda e: c.configure(fg_color=theme.CARD_BG_HOVER), add="+")
                c.bind("<Leave>", lambda e: c.configure(fg_color=tb), add="+")
            _bh()

            photo = self._get_thumb(g.image_path, 50, 52)
            if photo is not None:
                ctk.CTkLabel(cell, image=photo, text="").pack(pady=(4, 0))
            else:
                ctk.CTkLabel(
                    cell, text=g.char, font=("Segoe UI", 20),
                    text_color=theme.TEXT_PRIMARY,
                ).pack(pady=8)

            ctk.CTkLabel(
                cell, text=f"{g.char}  {g.tier[0]}",
                font=theme.FONT_SMALL, text_color=tc,
            ).pack()
            ctk.CTkLabel(
                cell, text=f"{g.quality_score:.0%}",
                font=("", 8), text_color=theme.TEXT_MUTED,
            ).pack()

    def _reload_and_refresh_all(self):
        """Recarga el banco una sola vez y actualiza banco + revisión."""
        try:
            self._pipeline.reload_bank()
        except Exception as exc:
            logger.error("reload_bank failed: %s", exc, exc_info=True)
            diagnostics.log_error("reload_and_refresh_all", exc)
        try:
            self._do_refresh_bank_ui()
        except Exception as exc:
            logger.error("_do_refresh_bank_ui failed: %s", exc, exc_info=True)
        try:
            self._do_refresh_review_ui()
        except Exception as exc:
            logger.error("_do_refresh_review_ui failed: %s", exc, exc_info=True)

"""BankTabRenderMixin — refresco/render del grid del Banco de InkCoreView."""
import logging

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)


class BankTabRenderMixin:
    """Refresco y render del grid del banco (resumen, agrupación por letra, celdas)."""

    def _do_refresh_bank_ui(self):
        for w in self._bank_scroll.winfo_children():
            w.destroy()
        self._glyph_photos.clear()
        # Reset selección al refrescar (los path pueden cambiar después de ops)
        self._bank_selection_vars = {}
        self._update_bank_selection_bar()

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
                text="Banco vacío. Ve al Extractor para agregar glifos\n"
                     "o usa ➕ Agregar desde imagen.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
                justify="center",
            ).pack(pady=30)
            return

        # Orden canónico: a-z con ñ en su posición (índice 14), luego 0-9, luego resto
        _ALPHA_ORDER = list("abcdefghijklmnñopqrstuvwxyz")

        def _char_sort_key(ch: str) -> tuple:
            ch_l = ch.lower()
            if ch_l in _ALPHA_ORDER:
                return (0, _ALPHA_ORDER.index(ch_l), ch)
            if ch.isdigit():
                return (1, int(ch), ch)
            return (2, ord(ch), ch)

        # Agrupar por carácter
        by_char: dict[str, list] = {}
        for g in glyphs:
            by_char.setdefault(g.char, []).append(g)

        # Si hay filtro de un solo char, mostrar flat (sin cabecera redundante)
        use_groups = len(by_char) > 1

        cols = 6
        for char in sorted(by_char.keys(), key=_char_sort_key):
            char_glyphs = by_char[char]
            if use_groups:
                # Cabecera de grupo con calidad promedio
                avg_q = sum(g.quality_score for g in char_glyphs) / len(char_glyphs)
                q_color = (theme.ACCENT_GREEN if avg_q >= 0.75
                           else theme.ACCENT_ORANGE if avg_q >= 0.50
                           else theme.ACCENT_RED)
                hdr = ctk.CTkFrame(
                    self._bank_scroll,
                    fg_color=theme.BG_SECONDARY, corner_radius=6,
                )
                hdr.pack(fill="x", pady=(10, 2), padx=4)
                ctk.CTkLabel(
                    hdr,
                    text=f"  {char.upper()}",
                    font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
                ).pack(side="left", padx=10, pady=4)
                ctk.CTkLabel(
                    hdr,
                    text=f"{len(char_glyphs)} muestra{'s' if len(char_glyphs) != 1 else ''}",
                    font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                ).pack(side="left", padx=4)
                ctk.CTkLabel(
                    hdr,
                    text=f"prom {avg_q:.0%}",
                    font=theme.FONT_SMALL, text_color=q_color,
                ).pack(side="right", padx=10, pady=4)

            current_row = None
            for i, g in enumerate(char_glyphs):
                if i % cols == 0:
                    current_row = ctk.CTkFrame(self._bank_scroll, fg_color="transparent")
                    current_row.pack(fill="x", pady=2, padx=4)
                self._build_bank_cell(current_row, g)

    def _build_bank_cell(self, parent, glyph) -> None:
        """Construye una celda con thumb, char/tier, calidad y botones de acción."""
        tc = self._tier_text_color(glyph.tier)
        tier_bg = theme.TIER_BG.get(glyph.tier, theme.CARD_BG)
        select_mode = bool(self._bank_select_mode.get())
        # Celda más alta para acomodar la fila de acciones (o checkbox + thumb)
        cell_h = 122
        cell = ctk.CTkFrame(
            parent,
            fg_color=tier_bg,
            corner_radius=8,
            width=78, height=cell_h,
            border_width=1,
            border_color=self._tier_border(glyph.tier),
        )
        cell.pack(side="left", padx=4)
        cell.pack_propagate(False)

        def _bh(c=cell, tb=tier_bg):
            c.bind("<Enter>", lambda e: c.configure(fg_color=theme.CARD_BG_HOVER), add="+")
            c.bind("<Leave>", lambda e: c.configure(fg_color=tb), add="+")
        _bh()

        # Checkbox en esquina superior izquierda (solo en modo selección)
        if select_mode:
            var = ctk.BooleanVar(value=False)
            self._bank_selection_vars[glyph.image_path] = var
            chk = ctk.CTkCheckBox(
                cell, text="", variable=var,
                width=14, height=14, checkbox_width=14, checkbox_height=14,
                fg_color=theme.ACCENT_BLUE,
                command=self._update_bank_selection_bar,
            )
            chk.place(x=2, y=2)

        photo = self._get_thumb(glyph.image_path, 50, 52)
        if photo is not None:
            ctk.CTkLabel(cell, image=photo, text="").pack(pady=(4, 0))
        else:
            ctk.CTkLabel(
                cell, text=glyph.char, font=("Segoe UI", 20),
                text_color=theme.TEXT_PRIMARY,
            ).pack(pady=8)

        ctk.CTkLabel(
            cell, text=f"{glyph.char}  {glyph.tier[0]}",
            font=theme.FONT_SMALL, text_color=tc,
        ).pack()
        ctk.CTkLabel(
            cell, text=f"{glyph.quality_score:.0%}",
            font=("", 8), text_color=theme.TEXT_MUTED,
        ).pack()

        # Botones de acción
        btn_row = ctk.CTkFrame(cell, fg_color="transparent")
        btn_row.pack(side="bottom", pady=(0, 3))

        ctk.CTkButton(
            btn_row, text="✏️", width=20, height=20,
            font=("Segoe UI", 10),
            fg_color=theme.BG_TERTIARY, hover_color=theme.ACCENT_BLUE,
            text_color=theme.TEXT_PRIMARY, corner_radius=4,
            command=lambda g=glyph: self._open_rename_modal(g),
        ).pack(side="left", padx=1)

        ctk.CTkButton(
            btn_row, text="⬆️", width=20, height=20,
            font=("Segoe UI", 10),
            fg_color=theme.BG_TERTIARY, hover_color=theme.ACCENT_GREEN,
            text_color=theme.TEXT_PRIMARY, corner_radius=4,
            command=lambda g=glyph: self._bank_cycle_tier(g),
        ).pack(side="left", padx=1)

        ctk.CTkButton(
            btn_row, text="🗑️", width=20, height=20,
            font=("Segoe UI", 10),
            fg_color=theme.BG_TERTIARY, hover_color=theme.ACCENT_RED,
            text_color=theme.TEXT_PRIMARY, corner_radius=4,
            command=lambda g=glyph: self._bank_delete_glyph(g),
        ).pack(side="left", padx=1)

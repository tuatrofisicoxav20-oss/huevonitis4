"""ExtractorTabGridMixin — renderiza la grilla de glifos extraídos.

Separado de extractor_tab.py para mantener cada archivo manejable.
Solo depende de:
  • self._glyphs_scroll, self._glyph_count_label, self._quality_summary, self._extracted
  • self._get_thumb (definido en main_view.py)
"""
import customtkinter as ctk

from ui import theme


class ExtractorTabGridMixin:
    """Renderizado de la grilla 8-col + tooltips por glifo."""

    LOW_QUALITY = 0.4
    GRID_COLS = 8

    def _show_extracted_grid(self):
        for w in self._glyphs_scroll.winfo_children():
            w.destroy()
        self._glyph_photos.clear()
        self._glyph_count_label.configure(text=f"{len(self._extracted)} glifos")

        if not self._extracted:
            ctk.CTkLabel(
                self._glyphs_scroll, text="Sin glifos",
                text_color=theme.TEXT_MUTED, font=theme.FONT_BODY,
            ).pack(pady=20)
            self._quality_summary.configure(text="")
            return

        avg_q = sum(g.quality_score for g in self._extracted) / len(self._extracted)
        if avg_q >= 0.75:
            q_color, q_label = theme.ACCENT_GREEN, "Excelente"
        elif avg_q >= 0.5:
            q_color, q_label = theme.ACCENT_ORANGE, "Buena"
        else:
            q_color, q_label = theme.ACCENT_RED, "Baja"
        self._quality_summary.configure(
            text=f"Calidad promedio: {avg_q:.0%} ({q_label})",
            text_color=q_color,
        )

        current_row = None
        for i, g in enumerate(self._extracted):
            if i % self.GRID_COLS == 0:
                current_row = ctk.CTkFrame(self._glyphs_scroll, fg_color="transparent")
                current_row.pack(fill="x", pady=2)
            self._build_glyph_cell(current_row, g, i)

    def _build_glyph_cell(self, parent, glyph, idx: int):
        tc = self._tier_text_color(glyph.tier)
        low_q = glyph.quality_score < self.LOW_QUALITY
        cell = ctk.CTkFrame(
            parent,
            fg_color=theme.CARD_BG,
            corner_radius=6,
            width=54, height=68,
            border_width=1,
            border_color=theme.ACCENT_RED if low_q else self._tier_border(glyph.tier),
        )
        cell.pack(side="left", padx=3)
        cell.pack_propagate(False)

        del_btn = ctk.CTkButton(
            cell, text="×", width=16, height=16,
            font=("Segoe UI", 10, "bold"),
            fg_color="#3a1a1a", hover_color=theme.ACCENT_RED,
            text_color=theme.ACCENT_RED, corner_radius=8,
            command=lambda i=idx: self._delete_extracted_glyph(i),
        )
        del_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-1, y=1)

        photo = self._get_thumb(glyph.image_path, 42, 46)
        if photo is not None:
            ctk.CTkLabel(cell, image=photo, text="").pack(pady=(4, 0))
        else:
            ctk.CTkLabel(
                cell, text="?", font=("Segoe UI", 16),
                text_color=theme.TEXT_MUTED,
            ).pack(pady=(8, 0))

        # Si hay predicción del labeler, esa es la canónica (modo auto OCR-first)
        shown_char = (getattr(glyph, "predicted_char", None) or glyph.char or "?")
        ctk.CTkLabel(cell, text=shown_char,
                     font=theme.FONT_SMALL, text_color=tc).pack()
        conf = getattr(glyph, "label_confidence", None)
        badge = (f"{conf:.0%}·{glyph.quality_score:.0%}"
                 if conf is not None else f"{glyph.quality_score:.0%}")
        ctk.CTkLabel(cell, text=badge, font=("", 8),
                     text_color=theme.TEXT_MUTED).pack()

        self._attach_glyph_tooltip(cell, glyph)

    def _attach_glyph_tooltip(self, widget, glyph) -> None:
        """Hover tooltip con predicción, confianza, fuentes y métricas."""
        lines = [
            f"Char: {glyph.char or '?'}",
            f"Tier: {glyph.tier}",
            f"Calidad: {glyph.quality_score:.0%}",
            f"Cobertura tinta: {glyph.ink_coverage:.1%}",
        ]
        pred = getattr(glyph, "predicted_char", None)
        conf = getattr(glyph, "label_confidence", None)
        sources = getattr(glyph, "detector_sources", None) or []
        if pred is not None:
            confs = f" ({conf:.2f})" if conf is not None else ""
            lines.append(f"Predicción: {pred}{confs}")
        if sources:
            lines.append(f"Detectores: {', '.join(sources)}")
        text = "\n".join(lines)

        tip = {"win": None}

        def _show(_evt):
            if tip["win"] is not None:
                return
            try:
                tw = ctk.CTkToplevel(widget)
                tw.overrideredirect(True)
                tw.attributes("-topmost", True)
                tw.configure(fg_color=theme.BG_SECONDARY)
                lbl = ctk.CTkLabel(
                    tw, text=text, font=theme.FONT_SMALL,
                    text_color=theme.TEXT_PRIMARY, justify="left",
                    fg_color=theme.BG_SECONDARY,
                )
                lbl.pack(padx=8, pady=6)
                x = widget.winfo_rootx() + widget.winfo_width() + 6
                y = widget.winfo_rooty()
                tw.geometry(f"+{x}+{y}")
                tip["win"] = tw
            except Exception:
                tip["win"] = None

        def _hide(_evt):
            tw = tip["win"]
            if tw is not None:
                try:
                    tw.destroy()
                except Exception:
                    pass
                tip["win"] = None

        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)

    @staticmethod
    def _tier_text_color(tier: str) -> str:
        return {
            "Gold":   theme.ACCENT_YELLOW,
            "Silver": "#C0C0C0",
            "Bronze": "#CD7F32",
        }.get(tier, "#888")

    @staticmethod
    def _tier_border(tier: str) -> str:
        return {
            "Gold":   theme.ACCENT_GREEN,
            "Silver": theme.ACCENT_ORANGE,
            "Bronze": theme.BORDER,
        }.get(tier, theme.BORDER)

    def _delete_extracted_glyph(self, idx: int):
        if 0 <= idx < len(self._extracted):
            self._extracted.pop(idx)
            self._show_extracted_grid()

"""BankTabRenderMixin — grid del Banco v2 (U4).

Reemplaza el rebuild total (UI-01) por:
  • Acordeón por letra: solo las secciones ABIERTAS construyen celdas
    (default: las primeras 3; el estado se recuerda durante la sesión).
  • Refresh diferencial: diff por image_path (thumb_cache.diff_paths) —
    solo se crean/destruyen/actualizan las celdas que cambiaron.
  • Chunking: las celdas nuevas se construyen por lotes vía _render_chunked.
  • Celda v2 compacta (4 widgets: frame+thumb+char+barra de calidad) con
    thumbs de DISCO (core/inkcore/thumb_cache, 64px) y acciones en una
    barra flotante COMPARTIDA que aparece al hacer hover (no 3 botones
    por celda). El anillo del borde codifica el tier.
"""
import contextlib
import logging

import customtkinter as ctk

from core.inkcore import thumb_cache
from ui import icons, theme

logger = logging.getLogger(__name__)

_ALPHA_ORDER = list("abcdefghijklmnñopqrstuvwxyz")

CELL_W, CELL_H = 80, 100
COLS = 6
DEFAULT_OPEN = 3


def _char_sort_key(ch: str) -> tuple:
    ch_l = ch.lower()
    if ch_l in _ALPHA_ORDER:
        return (0, _ALPHA_ORDER.index(ch_l), ch)
    if ch.isdigit():
        return (1, int(ch), ch)
    return (2, ord(ch), ch)


def _tier_ring(tier: str) -> str:
    return {
        "Gold": theme.ACCENT_PRIMARY,
        "Silver": theme.TIER_COLORS["Silver"],
        "Bronze": theme.TIER_COLORS["Bronze"],
    }.get(tier, theme.BORDER)


class BankTabRenderMixin:
    """Acordeón + refresh diferencial del grid del banco."""

    # ── Estado ─────────────────────────────────────────────────────

    def _bank_state_init(self) -> None:
        if hasattr(self, "_bank_sections"):
            return
        # char → {"header","chev","count_lbl","qual_lbl","body","cells","glyphs"}
        self._bank_sections: dict[str, dict] = {}
        self._bank_open_chars: set | None = None  # None = aplicar default
        self._bank_thumb_photos: dict = {}
        self._bank_selected_paths: set[str] = set()
        self._bank_hover_bar = None
        self._bank_hover_hide_job = None
        self._bank_empty_widgets: list = []

    # ── Refresh (diferencial) ──────────────────────────────────────

    def _do_refresh_bank_ui(self):
        self._bank_state_init()
        self._cancel_chunked("bank_cells")
        self._bank_hover_hide(now=True)

        cov = self._pipeline.bank_coverage()
        missing = cov.get("alpha_missing") or []
        missing_str = (f"  |  Faltan: {''.join(missing[:8])}{'…' if len(missing) > 8 else ''}"
                       if missing else "")
        self._bank_summary.configure(
            text=(f"Total: {cov['total_glyphs']} glifos  |  "
                  f"Letras: {cov['alpha_covered']}/27  |  "
                  f"Calidad prom: {cov['avg_quality']:.0%}" + missing_str))

        char_filter = self._bank_filter_entry.get().strip()
        tier_filter = self._tier_filter.get()
        glyphs = self._pipeline.bank.get_all(char_filter=char_filter,
                                             tier_filter=tier_filter)

        for w in self._bank_empty_widgets:
            with contextlib.suppress(Exception):
                w.destroy()
        self._bank_empty_widgets.clear()

        if not glyphs:
            self._bank_destroy_sections()
            self._bank_show_empty_state(filtered=bool(char_filter or tier_filter != "Todos"))
            return

        by_char: dict[str, list] = {}
        for g in glyphs:
            by_char.setdefault(g.char, []).append(g)
        order = sorted(by_char, key=_char_sort_key)

        if self._bank_open_chars is None:
            self._bank_open_chars = set(order[:DEFAULT_OPEN])
        # Con filtro de texto el resultado es chico: abrir todo lo filtrado
        if char_filter:
            self._bank_open_chars |= set(order)

        # Secciones cuyo char salió del banco/filtro → fuera
        for ch in list(self._bank_sections):
            if ch not in by_char:
                self._bank_remove_section(ch)

        # Pre-generar thumbs faltantes en worker (no bloquea el grid)
        self._bank_pregen_thumbs([g.image_path for g in glyphs])

        ops: list = []
        for ch in order:
            sec = self._bank_sections.get(ch)
            if sec is None:
                sec = self._bank_make_section(ch)
            sec["glyphs"] = by_char[ch]
            self._bank_update_header(ch)
            if ch in self._bank_open_chars:
                ops.extend(self._bank_section_cell_ops(ch))
            else:
                self._bank_close_section_body(ch)
        self._bank_repack_sections(order)
        self._render_chunked("bank_cells", ops)
        self._update_bank_selection_bar()

    def _bank_destroy_sections(self) -> None:
        for ch in list(self._bank_sections):
            self._bank_remove_section(ch)

    def _bank_remove_section(self, ch: str) -> None:
        sec = self._bank_sections.pop(ch, None)
        if not sec:
            return
        with contextlib.suppress(Exception):
            sec["header"].destroy()
        if sec.get("body") is not None:
            with contextlib.suppress(Exception):
                sec["body"].destroy()

    def _bank_show_empty_state(self, filtered: bool) -> None:
        if filtered:
            lbl = ctk.CTkLabel(
                self._bank_scroll, text="Sin glifos que coincidan con el filtro.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED)
            lbl.pack(pady=30)
            self._bank_empty_widgets.append(lbl)
            return
        lbl = ctk.CTkLabel(
            self._bank_scroll,
            text="Banco vacío. Genera una plantilla, escríbela con tu letra\n"
                 "y cárgala en Captura masiva — o agrega glifos desde imagen.",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED, justify="center")
        lbl.pack(pady=(40, 8))
        btn = ctk.CTkButton(
            self._bank_scroll, text="Ir a Plantilla",
            image=icons.get_icon("puzzle", 14, theme.ACCENT_TEXT_ON), compound="left",
            fg_color=theme.ACCENT_PRIMARY, hover_color=theme.ACCENT_PRIMARY_HOVER,
            text_color=theme.ACCENT_TEXT_ON, corner_radius=theme.RADIUS["m"],
            command=lambda: self._show_tab("1 · 🧩 Plantilla"))
        btn.pack()
        self._bank_empty_widgets.extend([lbl, btn])

    # ── Secciones (acordeón) ───────────────────────────────────────

    def _bank_make_section(self, ch: str) -> dict:
        # UN solo widget por header (en este equipo cada widget cuesta
        # ~100-200 ms de primer pintado; con 27 secciones importa MUCHO).
        header = ctk.CTkButton(
            self._bank_scroll, text="", anchor="w", height=26,
            image=icons.get_icon("chevron-r", 12), compound="left",
            fg_color=theme.BG_SECONDARY, hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY, corner_radius=theme.RADIUS["s"],
            font=theme.FONT_SUBHEADING,
            command=lambda c=ch: self._bank_toggle_section(c))
        sec = {"header": header, "body": None, "cells": {}, "glyphs": [],
               "order": []}
        self._bank_sections[ch] = sec
        return sec

    def _bank_update_header(self, ch: str) -> None:
        sec = self._bank_sections[ch]
        glyphs = sec["glyphs"]
        avg_q = sum(g.quality_score for g in glyphs) / max(1, len(glyphs))
        n = len(glyphs)
        is_open = ch in (self._bank_open_chars or set())
        sec["header"].configure(
            text=f"  {ch.upper()}    ·    {n} muestra{'s' if n != 1 else ''}"
                 f"    ·    prom {avg_q:.0%}",
            image=icons.get_icon("chevron-d" if is_open else "chevron-r", 12))

    def _bank_repack_sections(self, order: list) -> None:
        """Re-empaqueta headers y bodies en orden canónico (pack barato)."""
        for ch in order:
            sec = self._bank_sections[ch]
            sec["header"].pack_forget()
            sec["header"].pack(fill="x", pady=(theme.SPACE["s"], 2),
                               padx=theme.SPACE["xs"])
            if sec.get("body") is not None:
                sec["body"].pack_forget()
                sec["body"].pack(fill="x", padx=theme.SPACE["xs"])

    def _bank_toggle_section(self, ch: str) -> None:
        sec = self._bank_sections.get(ch)
        if sec is None:
            return
        if ch in self._bank_open_chars:
            self._bank_open_chars.discard(ch)
            self._bank_close_section_body(ch)
        else:
            self._bank_open_chars.add(ch)
            ops = self._bank_section_cell_ops(ch)
            # Empacar el body justo después de su header
            self._bank_repack_sections(
                sorted(self._bank_sections, key=_char_sort_key))
            self._render_chunked("bank_cells", ops)
        self._bank_update_header(ch)

    def _bank_close_section_body(self, ch: str) -> None:
        """Cierra una sección destruyendo sus celdas (solo lo abierto vive)."""
        sec = self._bank_sections[ch]
        if sec.get("body") is not None:
            with contextlib.suppress(Exception):
                sec["body"].destroy()
            sec["body"] = None
        sec["cells"] = {}

    # ── Celdas (diff + chunking) ───────────────────────────────────


    def _bank_section_cell_ops(self, ch: str) -> list:
        """Ops chunked que sincronizan las celdas de una sección abierta."""
        sec = self._bank_sections[ch]
        if sec.get("body") is None:
            self._bank_make_body(sec)  # canvas único por sección (BankCellsMixin)
        glyphs = sec["glyphs"]
        new_order = [g.image_path for g in glyphs]
        by_path = {g.image_path: g for g in glyphs}
        added, removed, _kept = thumb_cache.diff_paths(set(sec["cells"]), set(new_order))

        ops: list = []
        for p in removed:
            ops.append(lambda p=p, sec=sec: self._bank_destroy_cell(sec, p))
        for p in new_order:
            if p in added:
                ops.append(lambda sec=sec, g=by_path[p]: self._bank_build_cell(sec, g))
            else:
                ops.append(lambda sec=sec, p=p, g=by_path[p]: self._bank_update_cell(sec, p, g))
        ops.append(lambda sec=sec, order=new_order: self._bank_regrid(sec, order))
        return ops

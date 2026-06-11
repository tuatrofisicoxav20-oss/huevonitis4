"""BulkCaptureGridMixin — grid de candidatos + keyboard nav + edit popup.

Separado de bulk_capture_tab.py para mantener cada archivo manejable.
Depende de:
  • self._bulk_grid_scroll, self._bulk_card_widgets, self._bulk_selected_idx
  • self._bulk_session
  • self._bulk_approve_all_btn, self._bulk_commit_btn
  • self._bulk_filtered_candidates() (en filters mixin / tab principal)
  • self._bulk_update_stats() (en tab principal)
  • self._get_thumb (en main_view)
"""
from typing import ClassVar

import customtkinter as ctk

from ui import theme

try:
    from PIL import ImageTk  # noqa: F401 (chequeo)
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class BulkCaptureGridMixin:
    """Render del grid de candidatos + interacción teclado/mouse."""

    DECISION_BG: ClassVar[dict] = {
        "pending":  theme.BG_TERTIARY,
        "approved": "#1A3A1A",
        "rejected": "#3A1A1A",
    }
    DECISION_BORDER: ClassVar[dict] = {
        "pending":  theme.BORDER,
        "approved": theme.ACCENT_GREEN,
        "rejected": theme.ACCENT_RED,
    }
    DECISION_ICON: ClassVar[dict] = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    GRID_COLS = 7

    # Cards por página. Meter cientos de widgets a un CTkScrollableFrame tiene
    # costo de layout O(n²) (cada pack re-mide a todos los anteriores): una
    # sesión real de 400-700 candidatos congelaba la app por decenas de
    # segundos. Se renderiza por páginas + lotes; "Mostrar más" AGREGA la
    # siguiente tanda sin reconstruir lo ya visible.
    GRID_PAGE = 70  # 10 filas × 7 (~57ms/card en CTk: página chica = aparece rápido)

    def _bulk_render_grid(self):
        # Cancelar un render por lotes en curso ANTES de destruir (un tick
        # encolado pintaría sobre widgets muertos).
        self._cancel_chunked("bulk_grid")
        for w in self._bulk_grid_scroll.winfo_children():
            w.destroy()
        self._bulk_card_widgets = []
        self._bulk_selected_idx = None

        candidates = self._bulk_filtered_candidates()
        if not candidates:
            ctk.CTkLabel(
                self._bulk_grid_scroll,
                text="Sin candidatos con los filtros actuales.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=80)
            return

        self._bulk_grid_state = {"cands": candidates, "next": 0,
                                 "row": None, "more_btn": None}
        self._bulk_render_next_page()

    def _bulk_render_next_page(self):
        st = getattr(self, "_bulk_grid_state", None)
        if not st:
            return
        if st["more_btn"] is not None:
            st["more_btn"].destroy()
            st["more_btn"] = None
        cands = st["cands"]
        start = st["next"]
        end = min(start + self.GRID_PAGE, len(cands))
        st["next"] = end

        def _make(i, cand):
            def _op():
                if i % self.GRID_COLS == 0:
                    st["row"] = ctk.CTkFrame(
                        self._bulk_grid_scroll, fg_color="transparent")
                    # anchor (no fill): si la fila se estira al ancho del padre,
                    # cada cambio de ancho del scrollable la redibuja (CTk canvas
                    # caro) → construir N cards costaba O(N²) en redraws.
                    st["row"].pack(anchor="w", pady=2)
                card = self._bulk_make_card(st["row"], cand, i)
                card.pack(side="left", padx=3, pady=2)
                self._bulk_card_widgets.append((cand, card))
            return _op

        ops = [_make(i, cands[i]) for i in range(start, end)]

        def _done():
            remaining = len(cands) - st["next"]
            if remaining > 0:
                st["more_btn"] = ctk.CTkButton(
                    self._bulk_grid_scroll,
                    text=f"▼ Mostrar {min(self.GRID_PAGE, remaining)} más "
                         f"({remaining} restantes)",
                    command=self._bulk_render_next_page,
                    fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
                    font=theme.FONT_SMALL, height=30,
                )
                st["more_btn"].pack(pady=8)
            self._bulk_approve_all_btn.configure(state="normal")
            self._bulk_commit_btn.configure(state="normal")
            self._bulk_grid_scroll.focus_set()

        self._render_chunked("bulk_grid", ops, on_done=_done)

    def _bulk_make_card(self, parent, cand, idx: int) -> ctk.CTkFrame:
        bg = self.DECISION_BG.get(cand.decision, theme.BG_TERTIARY)
        border = self.DECISION_BORDER.get(cand.decision, theme.BORDER)

        extra_h = 14 if cand.source_label else 0
        card = ctk.CTkFrame(parent, fg_color=bg, corner_radius=8,
                            width=88, height=110 + extra_h,
                            border_width=2, border_color=border)
        card.pack_propagate(False)

        thumb_size = 56
        thumb = None
        if _PIL_OK and cand.glyph.image_path:
            thumb = self._get_thumb(cand.glyph.image_path, thumb_size, thumb_size)
        if thumb:
            ctk.CTkLabel(card, image=thumb, text="").pack(pady=(6, 2))
        else:
            ctk.CTkLabel(card, text="?", font=("Segoe UI", 24),
                         text_color=theme.TEXT_MUTED).pack(pady=(6, 2))

        char_lbl = ctk.CTkLabel(
            card, text=cand.display_char,
            font=("Segoe UI", 18, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        char_lbl.pack()
        card._char_lbl = char_lbl  # para refrescar in-place al editar

        lc = cand.glyph.label_confidence
        if lc is None:
            conf_text, conf_color = cand.glyph.tier, theme.TEXT_MUTED
        elif lc >= 0.7:
            conf_text, conf_color = f"{lc:.0%}", theme.ACCENT_GREEN
        elif lc >= 0.4:
            conf_text, conf_color = f"{lc:.0%}", theme.ACCENT_YELLOW
        else:
            conf_text, conf_color = f"{lc:.0%}", theme.ACCENT_RED
        ctk.CTkLabel(card, text=conf_text, font=("Segoe UI", 9),
                     text_color=conf_color).pack()

        decision_lbl = ctk.CTkLabel(card, text=self.DECISION_ICON.get(cand.decision, ""),
                                    font=("Segoe UI", 10))
        decision_lbl.pack()
        card._decision_lbl = decision_lbl  # para refrescar in-place al aprobar/rechazar

        if cand.source_label:
            ctk.CTkLabel(
                card, text=cand.source_label,
                font=("Segoe UI", 7), text_color=theme.TEXT_MUTED,
            ).pack(pady=(0, 2))

        def on_click(e, i=idx):
            self._bulk_select(i)
        def on_dbl(e, i=idx):
            self._bulk_toggle_decision(i)
        def on_right(e, i=idx):
            self._bulk_edit_char_popup(i)

        for w in [card, *list(card.winfo_children())]:
            w.bind("<Button-1>", on_click, add="+")
            w.bind("<Double-Button-1>", on_dbl, add="+")
            w.bind("<Button-3>", on_right, add="+")

        return card

    def _bulk_refresh_card_visual(self, idx: int):
        """Refresca SOLO la card `idx` (color/borde/ícono/char) tras cambiar su
        decisión. Antes cada tecla A/R re-renderizaba el grid COMPLETO (cientos
        de cards) — eso congelaba la app en sesiones grandes."""
        if idx is None or idx >= len(self._bulk_card_widgets):
            return
        cand, card = self._bulk_card_widgets[idx]
        selected = (idx == self._bulk_selected_idx)
        card.configure(
            fg_color=self.DECISION_BG.get(cand.decision, theme.BG_TERTIARY),
            border_color=(theme.ACCENT_ORANGE if selected
                          else self.DECISION_BORDER.get(cand.decision, theme.BORDER)),
        )
        lbl = getattr(card, "_decision_lbl", None)
        if lbl is not None:
            lbl.configure(text=self.DECISION_ICON.get(cand.decision, ""))
        char_lbl = getattr(card, "_char_lbl", None)
        if char_lbl is not None:
            char_lbl.configure(text=cand.display_char)

    def _bulk_select_next(self, idx: int):
        """Selecciona la card siguiente, paginando si idx era la última visible."""
        st = getattr(self, "_bulk_grid_state", None)
        if (idx >= len(self._bulk_card_widgets) - 1 and st
                and st["next"] < len(st["cands"])):
            self._bulk_render_next_page()
        self._bulk_select(min(len(self._bulk_card_widgets) - 1, idx + 1))

    def _bulk_select(self, idx: int):
        if self._bulk_selected_idx is not None and self._bulk_selected_idx < len(self._bulk_card_widgets):
            prev_cand, prev_card = self._bulk_card_widgets[self._bulk_selected_idx]
            prev_card.configure(border_color=self.DECISION_BORDER.get(prev_cand.decision, theme.BORDER))
        self._bulk_selected_idx = idx
        if idx < len(self._bulk_card_widgets):
            _, card = self._bulk_card_widgets[idx]
            card.configure(border_color=theme.ACCENT_ORANGE)
        self._bulk_grid_scroll.focus_set()

    def _bulk_toggle_decision(self, idx: int):
        if not self._bulk_session or idx >= len(self._bulk_card_widgets):
            return
        cand, _ = self._bulk_card_widgets[idx]
        cand.decision = {
            "pending": "approved",
            "approved": "rejected",
            "rejected": "pending",
        }.get(cand.decision, "pending")
        self._bulk_refresh_card_visual(idx)
        self._bulk_update_stats()
        self._bulk_select(idx)

    def _bulk_edit_char_popup(self, idx: int):
        if not self._bulk_session or idx >= len(self._bulk_card_widgets):
            return
        cand, _ = self._bulk_card_widgets[idx]

        win = ctk.CTkToplevel(self)
        win.title("Editar carácter")
        win.geometry("280x140")
        win.grab_set()

        ctk.CTkLabel(win, text=f"Carácter actual: {cand.display_char!r}",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(pady=(16, 4))
        entry = ctk.CTkEntry(win, placeholder_text="Nuevo carácter",
                             fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
                             width=200)
        entry.pack(pady=4)
        entry.insert(0, cand.display_char)
        entry.focus()

        def save():
            new_char = entry.get().strip()
            if new_char:
                cand.user_label = new_char[:1]
                cand.decision = "approved"
            win.destroy()
            self._bulk_refresh_card_visual(idx)
            self._bulk_update_stats()

        entry.bind("<Return>", lambda e: save())
        ctk.CTkButton(win, text="Guardar", command=save,
                      fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
                      width=200).pack(pady=8)

    def _bulk_on_key(self, event):
        if not self._bulk_session or not self._bulk_card_widgets:
            return
        key = event.keysym.lower()
        idx = self._bulk_selected_idx
        n = len(self._bulk_card_widgets)

        if key in ("right", "down"):
            # Al llegar al final de la página, cargar la siguiente tanda para
            # que la revisión por teclado fluya sin tocar el mouse.
            st = getattr(self, "_bulk_grid_state", None)
            if (idx is not None and idx >= n - 1 and st
                    and st["next"] < len(st["cands"])):
                self._bulk_render_next_page()
            self._bulk_select(min(len(self._bulk_card_widgets) - 1, (idx or 0) + 1))
        elif key in ("left", "up"):
            self._bulk_select(max(0, (idx or 0) - 1))
        elif key == "a" and idx is not None:
            cand, _ = self._bulk_card_widgets[idx]
            cand.decision = "approved"
            self._bulk_refresh_card_visual(idx)
            self._bulk_update_stats()
            self._bulk_select_next(idx)
        elif key == "r" and idx is not None:
            cand, _ = self._bulk_card_widgets[idx]
            cand.decision = "rejected"
            self._bulk_refresh_card_visual(idx)
            self._bulk_update_stats()
            self._bulk_select_next(idx)
        elif key == "e" and idx is not None:
            self._bulk_edit_char_popup(idx)
        elif key == "space" and idx is not None:
            self._bulk_toggle_decision(idx)
        elif key == "escape":
            self._bulk_select(-1)
            self._bulk_selected_idx = None
        elif event.state & 0x4:  # Ctrl
            if key in ("a", "d"):
                decision = "approved" if key == "a" else "rejected"
                # Aplica a TODOS los candidatos filtrados (también los aún no
                # paginados); refresca el visual solo de los visibles.
                st = getattr(self, "_bulk_grid_state", None)
                targets = st["cands"] if st else [c for c, _ in self._bulk_card_widgets]
                for c in targets:
                    c.decision = decision
                for i in range(len(self._bulk_card_widgets)):
                    self._bulk_refresh_card_visual(i)
                self._bulk_update_stats()

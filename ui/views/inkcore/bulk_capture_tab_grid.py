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
import customtkinter as ctk

from ui import theme

try:
    from PIL import ImageTk  # noqa: F401 (chequeo)
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class BulkCaptureGridMixin:
    """Render del grid de candidatos + interacción teclado/mouse."""

    DECISION_BG = {
        "pending":  theme.BG_TERTIARY,
        "approved": "#1A3A1A",
        "rejected": "#3A1A1A",
    }
    DECISION_BORDER = {
        "pending":  theme.BORDER,
        "approved": theme.ACCENT_GREEN,
        "rejected": theme.ACCENT_RED,
    }
    DECISION_ICON = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    GRID_COLS = 7

    def _bulk_render_grid(self):
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

        row_frame = None
        for i, cand in enumerate(candidates):
            if i % self.GRID_COLS == 0:
                row_frame = ctk.CTkFrame(self._bulk_grid_scroll, fg_color="transparent")
                row_frame.pack(fill="x", pady=2)
            card = self._bulk_make_card(row_frame, cand, i)
            card.pack(side="left", padx=3, pady=2)
            self._bulk_card_widgets.append((cand, card))

        self._bulk_approve_all_btn.configure(state="normal")
        self._bulk_commit_btn.configure(state="normal")
        self._bulk_grid_scroll.focus_set()

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

        ctk.CTkLabel(
            card, text=cand.display_char,
            font=("Segoe UI", 18, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack()

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

        ctk.CTkLabel(card, text=self.DECISION_ICON.get(cand.decision, ""),
                     font=("Segoe UI", 10)).pack()

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
        self._bulk_render_grid()
        self._bulk_update_stats()
        if idx < len(self._bulk_card_widgets):
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
            self._bulk_render_grid()
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
            self._bulk_select(min(n - 1, (idx or 0) + 1))
        elif key in ("left", "up"):
            self._bulk_select(max(0, (idx or 0) - 1))
        elif key == "a" and idx is not None:
            cand, _ = self._bulk_card_widgets[idx]
            cand.decision = "approved"
            self._bulk_render_grid()
            self._bulk_update_stats()
            self._bulk_select(min(n - 1, idx + 1))
        elif key == "r" and idx is not None:
            cand, _ = self._bulk_card_widgets[idx]
            cand.decision = "rejected"
            self._bulk_render_grid()
            self._bulk_update_stats()
            self._bulk_select(min(n - 1, idx + 1))
        elif key == "e" and idx is not None:
            self._bulk_edit_char_popup(idx)
        elif key == "space" and idx is not None:
            self._bulk_toggle_decision(idx)
        elif key == "escape":
            self._bulk_select(-1)
            self._bulk_selected_idx = None
        elif event.state & 0x4:  # Ctrl
            if key == "a":
                for c, _ in self._bulk_card_widgets:
                    c.decision = "approved"
                self._bulk_render_grid()
                self._bulk_update_stats()
            elif key == "d":
                for c, _ in self._bulk_card_widgets:
                    c.decision = "rejected"
                self._bulk_render_grid()
                self._bulk_update_stats()

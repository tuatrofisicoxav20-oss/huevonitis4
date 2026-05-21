import contextlib

import customtkinter as ctk

import config
from ui import theme
from ui.animations import animate_width


class CollapsibleSidebar(ctk.CTkFrame):
    def __init__(self, parent, on_navigate, **kwargs):
        super().__init__(
            parent,
            width=config.SIDEBAR_EXPANDED_WIDTH,
            fg_color=theme.BG_SECONDARY,
            corner_radius=0,
            border_width=0,
            **kwargs,
        )
        self.on_navigate = on_navigate
        self._expanded = True
        self._active_view = "dashboard"
        self._buttons: dict = {}
        self._indicators: dict = {}
        self._icon_badges: dict = {}
        self._tooltips: dict = {}
        self._build()
        self.pack_propagate(False)

    def _build(self):
        # ── Logo area ──────────────────────────────────────────────
        logo_frame = ctk.CTkFrame(
            self,
            fg_color=theme.BG_PRIMARY,
            height=72,
            corner_radius=0,
        )
        logo_frame.pack(fill="x")
        logo_frame.pack_propagate(False)

        # Coloured pill behind the logo text
        logo_pill = ctk.CTkFrame(
            logo_frame,
            fg_color=theme.ACCENT_ORANGE,
            corner_radius=10,
            width=48, height=38,
        )
        logo_pill.place(relx=0.5, rely=0.5, anchor="center")
        logo_pill.pack_propagate(False)

        self._logo_label = ctk.CTkLabel(
            logo_pill,
            text="H4",
            font=("Segoe UI", 18, "bold"),
            text_color="#FFFFFF",
        )
        self._logo_label.place(relx=0.5, rely=0.5, anchor="center")

        self._logo_pill = logo_pill   # keep ref for collapse

        # Thin accent line at the bottom of the logo area
        ctk.CTkFrame(self, height=2, fg_color=theme.ACCENT_ORANGE, corner_radius=0).pack(fill="x")

        # ── Nav items ──────────────────────────────────────────────
        self._nav_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._nav_frame.pack(fill="both", expand=True, pady=10)

        for view_id, icon, label in theme.NAV_ITEMS:
            btn, indicator = self._make_nav_btn(view_id, icon, label)
            self._buttons[view_id] = btn
            self._indicators[view_id] = indicator

        # ── Bottom separator + toggle ──────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER, corner_radius=0).pack(fill="x", padx=0)

        self._toggle_btn = ctk.CTkButton(
            self,
            text="◀  Colapsar",
            font=("Segoe UI", 10),
            fg_color="transparent",
            hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_MUTED,
            anchor="w",
            command=self.toggle,
            height=38,
            corner_radius=0,
        )
        self._toggle_btn.pack(fill="x", padx=0, pady=6)

    def _make_nav_btn(self, view_id: str, icon: str, label: str):
        accent_color = theme.NAV_ACCENT.get(view_id, theme.ACCENT_BLUE)

        row = ctk.CTkFrame(self._nav_frame, fg_color="transparent", height=48)
        row.pack(fill="x", padx=6, pady=2)
        row.pack_propagate(False)

        # Left coloured indicator bar (3 px)
        indicator = ctk.CTkFrame(row, fg_color="transparent", width=3, corner_radius=2)
        indicator.pack(side="left", fill="y", padx=(2, 0))
        indicator.pack_propagate(False)

        btn = ctk.CTkButton(
            row,
            text=f"   {icon}   {label}",
            font=theme.FONT_SIDEBAR,
            anchor="w",
            fg_color="transparent",
            hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_SECONDARY,
            height=46,
            corner_radius=8,
            command=lambda v=view_id: self._on_click(v),
        )
        btn.pack(side="left", fill="both", expand=True, padx=(2, 6))
        btn._icon = icon
        btn._label = label
        btn._row = row
        btn._accent = accent_color

        def on_enter(e, v=view_id, r=row, b=btn, ac=accent_color):
            if self._active_view != v:
                r.configure(fg_color=theme.BG_TERTIARY)
                b.configure(text_color=theme.TEXT_PRIMARY)
                self._show_tooltip(v, icon, label)

        def on_leave(e, v=view_id, r=row, b=btn):
            if self._active_view != v:
                r.configure(fg_color="transparent")
                b.configure(text_color=theme.TEXT_SECONDARY)
            self._hide_tooltip(v)

        for widget in (row, btn):
            widget.bind("<Enter>", on_enter, add="+")
            widget.bind("<Leave>", on_leave, add="+")

        return btn, indicator

    # ── Tooltip ────────────────────────────────────────────────────

    def _show_tooltip(self, view_id: str, icon: str, label: str):
        if self._expanded:
            return
        btn = self._buttons.get(view_id)
        if not btn:
            return
        self._hide_tooltip(view_id)
        try:
            x = self.winfo_rootx() + self.winfo_width() + 6
            y = btn.winfo_rooty() + btn.winfo_height() // 2 - 14
            tip = ctk.CTkToplevel(self)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tip.attributes("-topmost", True)
            inner = ctk.CTkFrame(
                tip, fg_color=theme.BG_TERTIARY, corner_radius=6,
                border_width=1, border_color=theme.BORDER,
            )
            inner.pack()
            ctk.CTkLabel(
                inner, text=f"  {label}  ",
                font=theme.FONT_BODY, text_color=theme.TEXT_PRIMARY,
            ).pack(padx=4, pady=4)
            self._tooltips[view_id] = tip
        except Exception:
            pass

    def _hide_tooltip(self, view_id: str):
        tip = self._tooltips.pop(view_id, None)
        if tip:
            with contextlib.suppress(Exception):
                tip.destroy()

    # ── Active state ───────────────────────────────────────────────

    def _on_click(self, view_id: str):
        self.set_active(view_id)
        self.on_navigate(view_id)

    def set_active(self, view_id: str):
        self._active_view = view_id
        for vid, btn in self._buttons.items():
            indicator = self._indicators[vid]
            row = btn._row
            accent = btn._accent
            if vid == view_id:
                # Active: coloured bg strip, white text, coloured indicator
                row.configure(fg_color=self._active_bg(accent))
                btn.configure(text_color=theme.TEXT_PRIMARY)
                indicator.configure(fg_color=accent)
            else:
                row.configure(fg_color="transparent")
                btn.configure(text_color=theme.TEXT_SECONDARY)
                indicator.configure(fg_color="transparent")

    @staticmethod
    def _active_bg(accent: str) -> str:
        """Return a very dark, tinted version of accent for the active row bg."""
        # Map known accents to their dark tint
        tints = {
            theme.ACCENT_BLUE:   "#0F2040",
            theme.ACCENT_GREEN:  "#0A2A18",
            theme.ACCENT_ORANGE: "#2A1200",
            theme.ACCENT_PURPLE: "#1A0F30",
            theme.ACCENT_YELLOW: "#221A00",
        }
        return tints.get(accent, "#1A2540")

    # ── Collapse / expand ──────────────────────────────────────────

    def toggle(self):
        if self._expanded:
            self._collapse()
        else:
            self._expand()

    def _collapse(self):
        self._expanded = False
        self._toggle_btn.configure(text="▶")
        self._logo_label.configure(text="H")
        self._logo_pill.configure(width=34)
        for btn in self._buttons.values():
            btn.configure(text=f"   {btn._icon}")
        animate_width(self, config.SIDEBAR_EXPANDED_WIDTH, config.SIDEBAR_COLLAPSED_WIDTH)

    def _expand(self):
        self._expanded = True
        self._toggle_btn.configure(text="◀  Colapsar")
        self._logo_label.configure(text="H4")
        self._logo_pill.configure(width=48)
        for btn in self._buttons.values():
            btn.configure(text=f"   {btn._icon}   {btn._label}")
        animate_width(self, config.SIDEBAR_COLLAPSED_WIDTH, config.SIDEBAR_EXPANDED_WIDTH)

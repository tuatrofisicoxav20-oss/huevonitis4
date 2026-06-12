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
        from ui import icons

        # ── Logo area (U3: marca orbital dibujada con PIL) ─────────
        logo_frame = ctk.CTkFrame(
            self,
            fg_color=theme.BG_PRIMARY,
            height=72,
            corner_radius=0,
        )
        logo_frame.pack(fill="x")
        logo_frame.pack_propagate(False)

        self._logo_label = ctk.CTkLabel(
            logo_frame, text="", image=icons.get_logo(46),
        )
        self._logo_label.place(relx=0.5, rely=0.5, anchor="center")

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

        from ui import icons as _icons
        self._toggle_btn = ctk.CTkButton(
            self,
            text="  Colapsar",
            image=_icons.get_icon("chevron-l", 14, theme.TEXT_MUTED),
            compound="left",
            font=theme.get_font(size=10),
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
        from ui import icons
        accent_color = theme.NAV_ACCENT.get(view_id, theme.ACCENT_BLUE)

        row = ctk.CTkFrame(self._nav_frame, fg_color="transparent", height=48)
        row.pack(fill="x", padx=6, pady=2)
        row.pack_propagate(False)

        # Left coloured indicator bar (3 px)
        indicator = ctk.CTkFrame(row, fg_color="transparent", width=3, corner_radius=2)
        indicator.pack(side="left", fill="y", padx=(2, 0))
        indicator.pack_propagate(False)

        # U3: icono vectorial + texto (el emoji se fue)
        btn = ctk.CTkButton(
            row,
            text=f"  {label}",
            image=icons.get_icon(icon, 18),
            compound="left",
            font=theme.FONT_SIDEBAR,
            anchor="w",
            fg_color="transparent",
            hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_SECONDARY,
            height=46,
            corner_radius=theme.RADIUS["m"],
            command=lambda v=view_id: self._on_click(v),
        )
        btn.pack(side="left", fill="both", expand=True, padx=(2, 6))
        btn._icon = icon
        btn._label = label
        btn._row = row
        btn._accent = accent_color

        def on_enter(e, v=view_id, r=row, b=btn):
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
        """Fondo de la fila activa (U2: acento único — tinte ámbar del tema)."""
        return theme.ACCENT_BG

    # ── Collapse / expand ──────────────────────────────────────────

    def toggle(self):
        if self._expanded:
            self._collapse()
        else:
            self._expand()

    def _collapse(self):
        from ui import icons, motion
        self._expanded = False
        self._toggle_btn.configure(
            text="", image=icons.get_icon("chevron-r", 14, theme.TEXT_MUTED))
        self._logo_label.configure(image=icons.get_logo(30, mini=True))

        # U8/M11: fade-out de los labels ANTES de animar el ancho
        def _fade_then_shrink():
            for btn in self._buttons.values():
                btn.configure(text="", text_color=theme.TEXT_SECONDARY)
            animate_width(self, config.SIDEBAR_EXPANDED_WIDTH,
                          config.SIDEBAR_COLLAPSED_WIDTH)

        if motion.should_animate("color"):
            for btn in self._buttons.values():
                motion.animate(
                    btn,
                    lambda t, b=btn: b.configure(text_color=motion.lerp_color(
                        theme.TEXT_SECONDARY, theme.BG_SECONDARY, t)),
                    steps=6, step_ms=16, kind="color", key="label_fade")
            self.after(110, _fade_then_shrink)
        else:
            _fade_then_shrink()

    def _expand(self):
        from ui import icons
        self._expanded = True
        self._toggle_btn.configure(
            text="  Colapsar", image=icons.get_icon("chevron-l", 14, theme.TEXT_MUTED))
        self._logo_label.configure(image=icons.get_logo(46))
        for btn in self._buttons.values():
            btn.configure(text=f"  {btn._label}")
        animate_width(self, config.SIDEBAR_COLLAPSED_WIDTH, config.SIDEBAR_EXPANDED_WIDTH)

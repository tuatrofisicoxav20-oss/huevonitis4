"""AppLayoutMixin — construcción del layout raíz de HuevonitisApp.

Separado de app.py. Agrupa el armado de la grilla principal, el topbar y el
statusbar. Depende de:
  • self (ctk.CTk) — para grid/columnconfigure
  • self.navigate — callback de navegación para el sidebar
  • crea: self._sidebar, self._topbar, self._content, self._statusbar y los
    widgets internos (_topbar_icon, _view_title, _search_bar, _unsaved_label,
    _spinner_label, _status_label, _status_project)
"""
import customtkinter as ctk

import config
from ui import theme
from ui.components.sidebar import CollapsibleSidebar


class AppLayoutMixin:
    """Armado de la ventana: grilla, topbar y statusbar."""

    # ── Layout ──────────────────────────────────────────────────────────────

    def _build(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=0)

        self._sidebar = CollapsibleSidebar(self, on_navigate=self.navigate)
        self._sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")

        self._topbar = self._make_topbar()
        self._topbar.grid(row=0, column=1, sticky="ew")

        self._content = ctk.CTkFrame(self, fg_color=theme.BG_PRIMARY, corner_radius=0)
        self._content.grid(row=1, column=1, sticky="nsew")

        self._statusbar = self._make_statusbar()
        self._statusbar.grid(row=2, column=1, sticky="ew")

    def _make_topbar(self) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(
            self,
            fg_color=theme.BG_SECONDARY,
            height=52,
            corner_radius=0,
        )
        bar.pack_propagate(False)

        # Accent line at the very bottom of the topbar (U1/UI-22: referencia
        # directa — navigate ya no escanea hijos buscando height==2)
        self._topbar_accent = ctk.CTkFrame(bar, fg_color=theme.ACCENT_ORANGE, height=2, corner_radius=0)
        self._topbar_accent.pack(side="bottom", fill="x")

        # View icon + title
        self._topbar_icon = ctk.CTkLabel(
            bar,
            text="🏠",
            font=("Segoe UI", 18),
        )
        self._topbar_icon.pack(side="left", padx=(18, 4))

        self._view_title = ctk.CTkLabel(
            bar, text="Dashboard",
            font=theme.FONT_HEADING, text_color=theme.TEXT_PRIMARY,
        )
        self._view_title.pack(side="left", padx=(0, 16))

        # Separator
        ctk.CTkFrame(bar, width=1, fg_color=theme.BORDER, corner_radius=0).pack(
            side="left", fill="y", pady=12,
        )

        self._search_bar = ctk.CTkEntry(
            bar, placeholder_text="🔍  Buscar...",
            width=240, height=32,
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.BORDER,
        )
        self._search_bar.pack(side="left", padx=14)

        self._unsaved_label = ctk.CTkLabel(
            bar, text="",
            font=theme.FONT_SMALL, text_color=theme.ACCENT_ORANGE,
        )
        self._unsaved_label.pack(side="left")

        ctk.CTkLabel(
            bar, text=f"v{config.VERSION}",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(side="right", padx=20)

        return bar

    def _make_statusbar(self) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(
            self,
            fg_color=theme.BG_PRIMARY,
            height=26,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER,
        )
        bar.pack_propagate(False)

        self._spinner_label = ctk.CTkLabel(
            bar, text="",
            font=theme.FONT_MONO, text_color=theme.ACCENT_ORANGE, width=20,
        )
        self._spinner_label.pack(side="left", padx=(10, 0))

        self._status_label = ctk.CTkLabel(
            bar, text="Listo",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._status_label.pack(side="left", padx=(4, 14))

        self._status_project = ctk.CTkLabel(
            bar, text="",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._status_project.pack(side="right", padx=14)

        return bar

"""BankTabMixin — tab 🗂 Banco de InkCoreView."""
import logging

import customtkinter as ctk

from ui import theme
from ui.views.inkcore.bank_tab_edit import BankTabEditMixin
from ui.views.inkcore.bank_tab_render import BankTabRenderMixin

logger = logging.getLogger(__name__)


class BankTabMixin(BankTabRenderMixin, BankTabEditMixin):
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

        from ui import icons
        ctk.CTkButton(
            top, text="Recargar", width=100, height=30,
            image=icons.get_icon("refresh", 14), compound="left",
            fg_color=theme.BG_TERTIARY, font=theme.FONT_SMALL,
            hover_color=theme.BORDER,
            command=self._refresh_bank,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            top, text="Ver informe", width=130, height=30,
            image=icons.get_icon("doc", 14, theme.ACCENT_TEXT_ON), compound="left",
            fg_color=theme.ACCENT_PRIMARY,
            hover_color=theme.ACCENT_PRIMARY_HOVER,
            text_color=theme.ACCENT_TEXT_ON,
            font=theme.FONT_SMALL,
            command=self._show_report,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            top, text="Agregar desde imagen", width=180, height=30,
            image=icons.get_icon("plus", 14, theme.ACCENT_TEXT_ON), compound="left",
            fg_color=theme.ACCENT_PRIMARY,
            hover_color=theme.ACCENT_PRIMARY_HOVER,
            text_color=theme.ACCENT_TEXT_ON,
            font=theme.FONT_SMALL,
            command=self._add_glyph_manual,
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

        # Selection mode toggle
        self._bank_select_mode = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            filter_row, text="Selección múltiple",
            variable=self._bank_select_mode,
            onvalue=True, offvalue=False,
            progress_color=theme.ACCENT_BLUE,
            font=theme.FONT_SMALL,
            command=self._refresh_bank,
        ).pack(side="right", padx=8)

        self._bank_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._bank_scroll.pack(fill="both", expand=True, padx=8, pady=4)

        # Batch action bar — visible solo cuando hay items seleccionados
        self._bank_batch_bar = ctk.CTkFrame(
            parent, fg_color=theme.BG_SECONDARY, corner_radius=8,
            border_width=1, border_color=theme.BORDER,
        )
        # No se empaqueta inicialmente; se hace pack/forget según selección
        self._bank_selection_count_lbl = ctk.CTkLabel(
            self._bank_batch_bar, text="",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        )
        self._bank_selection_count_lbl.pack(side="left", padx=12, pady=8)

        self._bank_batch_delete_btn = ctk.CTkButton(
            self._bank_batch_bar, text="Eliminar seleccionados",
            image=icons.get_icon("trash", 14), compound="left",
            width=200, height=30,
            fg_color=theme.ACCENT_RED, hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_SMALL,
            command=self._bank_batch_delete,
        )
        self._bank_batch_delete_btn.pack(side="left", padx=4, pady=8)

        # Mover a perfil — disabled hasta F3
        self._bank_batch_move_btn = ctk.CTkButton(
            self._bank_batch_bar, text="Mover a perfil…",
            image=icons.get_icon("folder", 14), compound="left",
            width=160, height=30,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            text_color=theme.TEXT_MUTED, font=theme.FONT_SMALL,
            state="disabled",
        )
        self._bank_batch_move_btn.pack(side="left", padx=4, pady=8)

        ctk.CTkLabel(
            self._bank_batch_bar,
            text="(Disponible al activar perfiles)",
            font=theme.get_font(size=8), text_color=theme.TEXT_MUTED,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            self._bank_batch_bar, text="Limpiar selección",
            image=icons.get_icon("x", 14), compound="left",
            width=140, height=30,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            font=theme.FONT_SMALL,
            command=self._bank_clear_selection,
        ).pack(side="right", padx=12, pady=8)

        # Estado de selección — image_path → BooleanVar
        self._bank_selection_vars: dict[str, ctk.BooleanVar] = {}

    # ── Logic ──────────────────────────────────────────────────────

    def _refresh_bank(self):
        # Viene de guardar desde el Extractor (otro tab): los datos cambiaron
        # en disco, así que aquí sí releemos. La revisión queda desactualizada,
        # se marca sucia para refrescarse al abrirse.
        self._pipeline.reload_bank()
        self._do_refresh_bank_ui()
        self._tabs_dirty.add(self._REVIEW_TAB)

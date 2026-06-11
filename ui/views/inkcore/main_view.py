"""InkCoreView — vista principal del módulo de tinta manuscrita.

Hereda comportamiento por tab de mixins separados:
  BulkCaptureTabMixin → bulk_capture_tab.py
  BankTabMixin        → bank_tab.py
  WriterTabMixin      → writer_tab.py
  ReviewTabMixin      → review_tab.py
  TemplateTabMixin    → template_tab.py

Sus helpers propios viven en sub-mixins separados:
  InkCoreViewHelpersMixin → main_view_helpers.py (thumbs, on_show, tabs, texto)
  InkCoreViewProfileMixin → main_view_profile.py (barra de perfiles v4.2)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from core.inkcore.pipeline import InkCorePipeline
from core.inkcore.reporter import InkCoreReporter
from ui import theme
from ui.views.base_view import BaseView
from ui.views.inkcore.bank_tab import BankTabMixin
from ui.views.inkcore.bulk_capture_tab import BulkCaptureTabMixin
from ui.views.inkcore.bulk_capture_tab_filters import BulkCaptureFiltersMixin
from ui.views.inkcore.bulk_capture_tab_grid import BulkCaptureGridMixin
from ui.views.inkcore.main_view_helpers import InkCoreViewHelpersMixin
from ui.views.inkcore.main_view_profile import InkCoreViewProfileMixin
from ui.views.inkcore.review_tab import ReviewTabMixin
from ui.views.inkcore.review_tab_row import ReviewTabRowMixin
from ui.views.inkcore.template_tab import TemplateTabMixin
from ui.views.inkcore.writer_tab import WriterTabMixin

if TYPE_CHECKING:
    from PIL import ImageTk


class InkCoreView(
    InkCoreViewHelpersMixin,
    InkCoreViewProfileMixin,
    BulkCaptureTabMixin,
    BulkCaptureGridMixin,
    BulkCaptureFiltersMixin,
    BankTabMixin,
    WriterTabMixin,
    ReviewTabMixin,
    ReviewTabRowMixin,
    TemplateTabMixin,
    BaseView,
):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._pipeline: InkCorePipeline = app.inkcore
        self._reporter = InkCoreReporter()
        self._preview_photo = None
        self._image_path: str | None = None
        self._glyph_photos: list = []
        self._review_photos: list = []
        self._review_checkboxes: list = []
        self._review_check_vars: list = []
        self._thumb_cache: dict[tuple, ImageTk.PhotoImage] = {}
        self._writer_page_photos: list = []
        # PERF: tabs cuyo contenido quedó desactualizado y se refrescarán de
        # forma diferida la próxima vez que se muestren (evita reconstruir grids
        # no visibles en cada micro-acción del banco/revisión).
        self._tabs_dirty: set[str] = set()
        self._build()

    def _build(self):
        from ui import perf
        with perf.measure("inkcore:_build_profile_bar"):
            self._build_profile_bar()
        self._tabs = ctk.CTkTabview(
            self,
            fg_color="transparent",
            segmented_button_fg_color=theme.BG_SECONDARY,
            segmented_button_selected_color=theme.ACCENT_ORANGE,
            segmented_button_unselected_color=theme.BG_SECONDARY,
            segmented_button_selected_hover_color=theme.ACCENT_ORANGE_HOVER,
            segmented_button_unselected_hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            command=self._on_tab_change,
        )
        self._tabs.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        # Pestañas en ORDEN DE FLUJO (izquierda → derecha = de crear el banco a
        # usarlo). Los pasos 1-2-3 son el flujo de captura de glifos; Banco y
        # Escritor son la etapa de "usar" el banco ya creado.
        #   1·Plantilla (generar hoja) → 2·Captura (cargar foto) →
        #   3·Revisión (aprobar) → Banco (ver) → Escritor (usar)
        self._tabs.add("1 · 🧩 Plantilla")
        self._tabs.add("2 · 📦 Captura masiva")
        self._tabs.add("3 · ✅ Revisión")
        self._tabs.add("🗂 Banco")
        self._tabs.add("✍️ Escritor")
        # Estado de sesión bulk — ANTES de cualquier builder (con lazy tabs
        # los builders pueden correr en cualquier orden).
        self._bulk_session = None
        self._bulk_cancel_event = None
        self._bulk_selected_idx: int | None = None
        self._bulk_card_widgets: list = []
        self._bulk_filter_conf_val: str = "Todos"
        self._bulk_filter_status_val: str = "Pendientes"
        self._bulk_filter_char_val: str = "(todos)"
        # U1/UI-02: lazy tabs — el contenido de cada tab se construye la
        # PRIMERA vez que se muestra (skeleton mientras tanto); al entrar solo
        # se construye el tab visible. Los refresh diferidos siguen el patrón
        # _tabs_dirty existente (ver _ensure_tab_built/_on_tab_change).
        self._tab_builders = {
            "1 · 🧩 Plantilla": self._build_template,
            "2 · 📦 Captura masiva": self._build_bulk_capture,
            "3 · ✅ Revisión": self._build_review,
            "🗂 Banco": self._build_bank,
            "✍️ Escritor": self._build_writer,
        }
        self._tabs_built: set[str] = set()
        self._ensure_tab_built(self._tabs.get(), defer=False)

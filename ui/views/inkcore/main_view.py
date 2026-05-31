"""InkCoreView — vista principal del módulo de tinta manuscrita.

Hereda comportamiento por tab de mixins separados:
  PipelinePanelMixin  → pipeline_panel.py
  ExtractorTabMixin   → extractor_tab.py
  BulkCaptureTabMixin → bulk_capture_tab.py
  BankTabMixin        → bank_tab.py
  WriterTabMixin      → writer_tab.py
  ReviewTabMixin      → review_tab.py

Sus helpers propios viven en sub-mixins separados:
  InkCoreViewHelpersMixin → main_view_helpers.py (thumbs, on_show, tabs, texto)
  InkCoreViewProfileMixin → main_view_profile.py (barra de perfiles v4.2)
"""
import customtkinter as ctk

from core.inkcore.pipeline import InkCorePipeline
from core.inkcore.reporter import InkCoreReporter
from core.models import GlyphEntry
from ui import theme
from ui.views.base_view import BaseView
from ui.views.inkcore.bank_tab import BankTabMixin
from ui.views.inkcore.bulk_capture_tab import BulkCaptureTabMixin
from ui.views.inkcore.bulk_capture_tab_filters import BulkCaptureFiltersMixin
from ui.views.inkcore.bulk_capture_tab_grid import BulkCaptureGridMixin
from ui.views.inkcore.extractor_tab import ExtractorTabMixin
from ui.views.inkcore.extractor_tab_build import ExtractorTabBuildMixin
from ui.views.inkcore.extractor_tab_grid import ExtractorTabGridMixin
from ui.views.inkcore.main_view_helpers import InkCoreViewHelpersMixin
from ui.views.inkcore.main_view_profile import InkCoreViewProfileMixin
from ui.views.inkcore.pipeline_panel import PipelinePanelMixin
from ui.views.inkcore.replicator_tab import ReplicatorTabMixin
from ui.views.inkcore.review_tab import ReviewTabMixin
from ui.views.inkcore.review_tab_row import ReviewTabRowMixin
from ui.views.inkcore.writer_tab import WriterTabMixin


class InkCoreView(
    InkCoreViewHelpersMixin,
    InkCoreViewProfileMixin,
    PipelinePanelMixin,
    ExtractorTabBuildMixin,
    ExtractorTabMixin,
    ExtractorTabGridMixin,
    BulkCaptureTabMixin,
    BulkCaptureGridMixin,
    BulkCaptureFiltersMixin,
    BankTabMixin,
    WriterTabMixin,
    ReviewTabMixin,
    ReviewTabRowMixin,
    ReplicatorTabMixin,
    BaseView,
):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._pipeline: InkCorePipeline = app.inkcore
        self._reporter = InkCoreReporter()
        self._extracted: list[GlyphEntry] = []
        self._preview_photo = None
        self._image_path: str | None = None
        self._glyph_photos: list = []
        self._review_photos: list = []
        self._original_img = None
        self._adj_collapsed = False
        self._review_checkboxes: list = []
        self._review_check_vars: list = []
        self._thumb_cache: dict[tuple, "ImageTk.PhotoImage"] = {}
        self._writer_page_photos: list = []
        # PERF: tabs cuyo contenido quedó desactualizado y se refrescarán de
        # forma diferida la próxima vez que se muestren (evita reconstruir grids
        # no visibles en cada micro-acción del banco/revisión).
        self._tabs_dirty: set[str] = set()
        self._build()

    def _build(self):
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
        self._tabs.add("📷 Extractor")
        self._tabs.add("📦 Captura masiva")
        self._tabs.add("🗂 Banco")
        self._tabs.add("✍️ Escritor")
        self._tabs.add("✅ Revisión")
        self._tabs.add("🔁 Reproducir")
        self._build_extractor(self._tabs.tab("📷 Extractor"))
        self._build_bulk_capture(self._tabs.tab("📦 Captura masiva"))
        self._build_bank(self._tabs.tab("🗂 Banco"))
        self._build_writer(self._tabs.tab("✍️ Escritor"))
        self._build_review(self._tabs.tab("✅ Revisión"))
        self._build_replicator(self._tabs.tab("🔁 Reproducir"))
        # Estado de sesión bulk
        self._bulk_session = None
        self._bulk_cancel_event = None
        self._bulk_selected_idx: int | None = None
        self._bulk_card_widgets: list = []
        self._bulk_filter_conf_val: str = "Todos"
        self._bulk_filter_status_val: str = "Pendientes"
        self._bulk_filter_char_val: str = "(todos)"

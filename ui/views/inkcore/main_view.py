"""InkCoreView — vista principal del módulo de tinta manuscrita.

Hereda comportamiento por tab de mixins separados:
  PipelinePanelMixin  → pipeline_panel.py
  ExtractorTabMixin   → extractor_tab.py
  BulkCaptureTabMixin → bulk_capture_tab.py
  BankTabMixin        → bank_tab.py
  WriterTabMixin      → writer_tab.py
  ReviewTabMixin      → review_tab.py
"""
import logging
from pathlib import Path

import customtkinter as ctk

from core.inkcore.pipeline import InkCorePipeline
from core.inkcore.reporter import InkCoreReporter
from core.models import GlyphEntry
from ui import theme
from ui.views.base_view import BaseView
from ui.views.inkcore.bank_tab import BankTabMixin
from ui.views.inkcore.bulk_capture_tab import BulkCaptureTabMixin
from ui.views.inkcore.extractor_tab import ExtractorTabMixin
from ui.views.inkcore.pipeline_panel import PipelinePanelMixin
from ui.views.inkcore.review_tab import ReviewTabMixin
from ui.views.inkcore.writer_tab import WriterTabMixin

logger = logging.getLogger(__name__)

try:
    from PIL import ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False


class InkCoreView(
    PipelinePanelMixin,
    ExtractorTabMixin,
    BulkCaptureTabMixin,
    BankTabMixin,
    WriterTabMixin,
    ReviewTabMixin,
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
        self._build()

    def _get_thumb(self, path: str, w: int, h: int) -> "ImageTk.PhotoImage | None":
        """Carga y cachea thumbnail de un glifo PNG."""
        key = (path, w, h)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        if not PIL_OK or not Path(path).exists():
            return None
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            bg = Image.new("RGBA", img.size, (22, 32, 50, 255))
            bg.paste(img, mask=img.split()[3])
            thumb = bg.convert("RGB")
            thumb.thumbnail((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self._thumb_cache[key] = photo
            if len(self._thumb_cache) > 300:
                oldest = next(iter(self._thumb_cache))
                del self._thumb_cache[oldest]
            return photo
        except Exception:
            return None

    def _build(self):
        self._tabs = ctk.CTkTabview(
            self,
            fg_color="transparent",
            segmented_button_fg_color=theme.BG_SECONDARY,
            segmented_button_selected_color=theme.ACCENT_ORANGE,
            segmented_button_unselected_color=theme.BG_SECONDARY,
            segmented_button_selected_hover_color=theme.ACCENT_ORANGE_HOVER,
            segmented_button_unselected_hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
        )
        self._tabs.pack(fill="both", expand=True, padx=16, pady=16)
        self._tabs.add("📷 Extractor")
        self._tabs.add("📦 Captura masiva")
        self._tabs.add("🗂 Banco")
        self._tabs.add("✍️ Escritor")
        self._tabs.add("✅ Revisión")
        self._build_extractor(self._tabs.tab("📷 Extractor"))
        self._build_bulk_capture(self._tabs.tab("📦 Captura masiva"))
        self._build_bank(self._tabs.tab("🗂 Banco"))
        self._build_writer(self._tabs.tab("✍️ Escritor"))
        self._build_review(self._tabs.tab("✅ Revisión"))
        # Estado de sesión bulk
        self._bulk_session = None
        self._bulk_cancel_event = None
        self._bulk_selected_idx: int | None = None
        self._bulk_card_widgets: list = []
        self._bulk_filter_conf_val: str = "Todos"
        self._bulk_filter_status_val: str = "Pendientes"
        self._bulk_filter_char_val: str = "(todos)"

    def on_show(self):
        self._reload_and_refresh_all()
        self._maybe_load_pending_text()

    def _maybe_load_pending_text(self) -> None:
        """Carga texto pendiente de Study si el escritor está vacío."""
        try:
            st = self.app.app_state
        except AttributeError:
            return
        pending = getattr(st, "study_text", None)
        if not pending:
            return
        current = self._writer_text.get("0.0", "end").strip()
        if not current:
            self._writer_text.delete("0.0", "end")
            self._writer_text.insert("0.0", pending)
            try:
                self._tabs.set("✍️ Escritor")
            except Exception:
                pass
            self.toast("Texto importado desde Estudio", "success")
        st.study_text = ""

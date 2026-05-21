"""
ExtractorTab — Tab "📷 Extractor" de InkCoreView.

Este módulo contiene la clase ExtractorTab que encapsula toda la lógica
del tab de extracción de glifos. Actualmente es un stub de migración:
la lógica real vive en InkCoreView para mantener estabilidad.

Uso futuro:
    from ui.views.inkcore_extractor_tab import ExtractorTab
    tab = ExtractorTab(parent_frame, pipeline=pipeline, app=app)
    tab.on_bank_changed = lambda: ...  # callback
"""
import logging
import threading
import customtkinter as ctk
from tkinter import filedialog
from pathlib import Path
from ui import theme
from core.inkcore.extractor import ExtractionOptions
from core.models import GlyphEntry

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk, ImageEnhance
    PIL_OK = True
except ImportError:
    PIL_OK = False


class ExtractorTab(ctk.CTkFrame):
    """Frame del tab Extractor. Recibe pipeline y app en __init__.

    on_bank_changed: callable que se invoca cuando se guardan glifos al banco.
    """

    def __init__(self, parent, pipeline, app, on_bank_changed=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._pipeline = pipeline
        self._app = app
        self.on_bank_changed = on_bank_changed or (lambda: None)
        self._extracted: list[GlyphEntry] = []
        self._image_path: str | None = None
        self._original_img = None
        self._adj_collapsed = False
        self._glyph_photos: list = []
        # Referencia al cache de thumbnails del InkCoreView padre
        self._thumb_cache_ref: dict | None = None

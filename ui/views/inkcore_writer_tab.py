"""
WriterTab — Tab "✍️ Escritor" de InkCoreView.

Stub de migración. La lógica real vive en InkCoreView._build_writer(),
_preview_handwriting(), _show_preview_pages() y _export_png()
para mantener estabilidad en esta versión.

Uso futuro:
    from ui.views.inkcore_writer_tab import WriterTab
    tab = WriterTab(parent_frame, pipeline=pipeline)
"""
import logging

import customtkinter as ctk

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False


class WriterTab(ctk.CTkFrame):
    """Frame del tab Escritor. Incluye selector de fondo y soporte de páginas."""

    def __init__(self, parent, pipeline, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._pipeline = pipeline
        self._bg_style_var = ctk.StringVar(value="hoja_blanca")
        self._writer_page_photos: list = []

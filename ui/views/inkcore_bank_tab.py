"""
BankTab — Tab "🗂 Banco" de InkCoreView.

Stub de migración. La lógica real vive en InkCoreView._build_bank() y
_do_refresh_bank_ui() para mantener estabilidad en esta versión.

Uso futuro:
    from ui.views.inkcore_bank_tab import BankTab
    tab = BankTab(parent_frame, pipeline=pipeline, thumb_cache=cache)
"""
import logging
import customtkinter as ctk
from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False


class BankTab(ctk.CTkFrame):
    """Frame del tab Banco. Recibe pipeline y cache de thumbnails en __init__."""

    def __init__(self, parent, pipeline, thumb_cache: dict, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._pipeline = pipeline
        self._thumb_cache = thumb_cache

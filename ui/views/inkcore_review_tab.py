"""
ReviewTab — Tab "✅ Revisión" de InkCoreView.

Stub de migración. La lógica real vive en InkCoreView._build_review(),
_do_refresh_review_ui(), _review_approve(), _review_reject(), etc.
para mantener estabilidad en esta versión.

Uso futuro:
    from ui.views.inkcore_review_tab import ReviewTab
    tab = ReviewTab(parent_frame, pipeline=pipeline, thumb_cache=cache,
                    on_action=reload_callback)
"""
import logging

import customtkinter as ctk

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False


class ReviewTab(ctk.CTkFrame):
    """Frame del tab Revisión.

    on_action: callable invocado tras aprobar/rechazar para recargar banco + revisión.
    """

    def __init__(self, parent, pipeline, thumb_cache: dict, on_action=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._pipeline = pipeline
        self._thumb_cache = thumb_cache
        self.on_action = on_action or (lambda: None)
        self._review_photos: list = []
        self._review_checkboxes: list = []
        self._review_check_vars: list = []

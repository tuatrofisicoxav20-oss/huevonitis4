"""Detector EasyOCR (CRAFT) — moderno y mantenido, reemplaza al craft-text-detector
muerto en Python 3.14.

EasyOCR usa CRAFT por dentro. Lo configuramos a nivel CARÁCTER (link_threshold y
width_ths bajos) para que NO agrupe las letras en palabras: queremos los bordes
de cada carácter como hints de alineación, no cajas de palabra.

El modelo de detección (~80 MB) se baja la primera vez. El de reconocimiento NO
se carga (`recognizer=False`): sólo nos interesa DÓNDE hay caracteres, no qué son.
"""
import importlib.util
import logging
from typing import ClassVar

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

# Chequeo de disponibilidad SIN importar easyocr: importarlo arrastra
# torch+torchvision (pesado) y frenaría el arranque de la app. La carga real
# ocurre lazy en _get_reader, sólo si el detector se activa de verdad.
_EASY_OK = importlib.util.find_spec("easyocr") is not None

from core.inkcore.glyph_detectors.base import GlyphDetector


class EasyOCRDetector(GlyphDetector):
    """Detección de caracteres con el CRAFT de EasyOCR."""

    name = "easyocr"
    available = _EASY_OK and _CV2_OK

    # Parámetros char-level: link bajo = no une trazos vecinos en una palabra.
    _DETECT_KW: ClassVar[dict] = dict(
        text_threshold=0.6, link_threshold=0.10, low_text=0.3,
        width_ths=0.1, ycenter_ths=0.5, height_ths=0.7, add_margin=0.0,
    )

    def __init__(self):
        self._reader = None  # lazy

    def _get_reader(self):
        if self._reader is None and _EASY_OK:
            import easyocr

            from core.inkcore.model_cache import ModelCache
            self._reader = ModelCache.get(
                "easyocr_det_es",
                lambda: easyocr.Reader(
                    ["es"], gpu=False, recognizer=False, verbose=False,
                ),
            )
        return self._reader

    @staticmethod
    def _prep(image_bgr: "np.ndarray") -> "np.ndarray":
        """CRAFT espera tinta oscura sobre fondo claro. La pipeline le pasa una
        máscara binaria (tinta blanca sobre negro): la invertimos a negro/blanco.
        Una foto normal se deja como está.
        """
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr
        # ¿Parece máscara? (casi todo 0/255 y fondo mayoritariamente negro)
        dark_ratio = float(np.mean(gray < 16))
        if dark_ratio > 0.5:
            gray = 255 - gray
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def detect(self, image_bgr: "np.ndarray") -> list:
        if not self.available:
            return []
        try:
            from core.inkcore.extractor import BBox
            reader = self._get_reader()
            if reader is None:
                return []
            prepped = self._prep(image_bgr)
            horizontal, _free = reader.detect(prepped, **self._DETECT_KW)
            # horizontal: lista (1 elem por imagen) de cajas [x1, x2, y1, y2]
            raw = horizontal[0] if horizontal else []
            boxes = []
            for b in raw:
                try:
                    x1, x2, y1, y2 = int(b[0]), int(b[1]), int(b[2]), int(b[3])
                except (TypeError, ValueError, IndexError):
                    continue
                w = x2 - x1
                h = y2 - y1
                if w > 0 and h > 0:
                    boxes.append(BBox(x1, y1, w, h))
            boxes.sort(key=lambda bb: (bb.y, bb.x))
            return boxes
        except Exception as exc:
            logger.error("EasyOCRDetector error: %s", exc)
            return []

    def install_hint(self) -> str:
        return (
            "EasyOCR no disponible.\n"
            "pip install easyocr torchvision  (torchvision desde el índice CPU "
            "de PyTorch para que empareje con tu torch: "
            "--index-url https://download.pytorch.org/whl/cpu)"
        )

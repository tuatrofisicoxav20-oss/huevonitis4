"""
Detector clásico por componentes conectados — método original de Huevonitis.
"""
import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

from core.inkcore.glyph_detectors.base import GlyphDetector

_MIN_COMP_AREA = 10
_MIN_CHAR_W = 2
_MIN_CHAR_H = 3


class ClassicCVDetector(GlyphDetector):
    """
    Detección por componentes conectados con CLAHE + Otsu.
    No requiere dependencias extra — siempre disponible si cv2 está instalado.
    """

    name = "classic_cv"
    available = _CV2_OK

    def detect(self, image_bgr: "np.ndarray") -> list:
        if not _CV2_OK:
            return []
        try:
            from core.inkcore.extractor import BBox
            gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
            # Salto 5 — multibinarización: Otsu solo se invierte en bajo contraste
            # (marca toda la página como tinta → 1 blob). best_binary elige por
            # contenido la candidata más sana (descarta degeneradas, maximiza
            # componentes tipo-letra). Cae a Otsu+CLAHE si el módulo no está.
            try:
                from core.inkcore.binarization import best_binary
                _, mask = best_binary(gray)
            except Exception:
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                enhanced = clahe.apply(gray)
                _, mask = cv2.threshold(
                    enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
                )
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

            num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
            boxes = []
            for i in range(1, num):
                area = int(stats[i, cv2.CC_STAT_AREA])
                w = int(stats[i, cv2.CC_STAT_WIDTH])
                h = int(stats[i, cv2.CC_STAT_HEIGHT])
                if area < _MIN_COMP_AREA or w < _MIN_CHAR_W or h < _MIN_CHAR_H:
                    continue
                x = int(stats[i, cv2.CC_STAT_LEFT])
                y = int(stats[i, cv2.CC_STAT_TOP])
                boxes.append(BBox(x, y, w, h))
            boxes.sort(key=lambda b: (b.y, b.x))
            return boxes
        except Exception as e:
            logger.error(f"ClassicCVDetector error: {e}")
            return []

    def install_hint(self) -> str:
        return "ClassicCVDetector requiere opencv-python (ya incluido en requirements.txt)"

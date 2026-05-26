"""Fronteras X auxiliares para alineación: Tesseract + detector alternativo.

Estas funciones devuelven posiciones (x) donde Tesseract o el detector
opcional vieron bordes de carácter. La pipeline las usa como "snap hints":
si el corte calculado está cerca de una frontera observada, se ajusta a ella.

Separado de extractor.py para mantenerlo más liviano.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    _CV_OK = True
except ImportError:
    _CV_OK = False

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    import pytesseract
    _TESS_OK = True
except ImportError:
    _TESS_OK = False


def get_detector_boundaries(detector, line_mask) -> list[int]:
    """Fronteras X via detector alternativo (CRAFT / Paddle).

    Convierte la máscara binaria a BGR, llama al detector y extrae los
    bordes izquierdo/derecho de cada bbox como hints. Devuelve lista vacía
    si el detector no está activo o falla.
    """
    if detector is None or not _CV_OK:
        return []
    try:
        line_bgr = cv2.cvtColor(line_mask, cv2.COLOR_GRAY2BGR)
        boxes = detector.detect(line_bgr)
        if not boxes:
            return []
        boundaries: set[int] = set()
        w = line_mask.shape[1]
        for b in boxes:
            if 0 <= b.x < w:
                boundaries.add(b.x)
            if 0 < b.x2 <= w:
                boundaries.add(b.x2)
        result = sorted(boundaries)
        if result:
            logger.debug(
                f"Detector '{detector.name}': "
                f"{len(result)} fronteras en línea de {w}px"
            )
        return result
    except Exception as exc:
        logger.debug(f"get_detector_boundaries error: {exc}")
        return []


def tesseract_boundaries(line_mask) -> list[int]:
    """Fronteras X de caracteres via Tesseract (varias estrategias).

    Escala a 3× la altura (mín. 200 px), añade borde blanco amplio,
    invierte para Tesseract y prueba PSM 7 + PSM 13. Toma la UNIÓN
    de fronteras detectadas (no nos interesa qué letra detectó Tesseract,
    solo dónde vio bordes).
    """
    if not _TESS_OK or not _CV_OK or not _PIL_OK:
        return []
    try:
        h, w = line_mask.shape[:2]

        target_h = max(200, h * 3)
        scale = target_h / max(1, h)
        scaled_w = int(w * scale)
        lm = cv2.resize(
            line_mask, (scaled_w, target_h),
            interpolation=cv2.INTER_LINEAR,
        )
        _, lm = cv2.threshold(lm, 127, 255, cv2.THRESH_BINARY)

        border = 50
        lm = cv2.copyMakeBorder(
            lm, border, border, border, border,
            cv2.BORDER_CONSTANT, value=0,
        )

        # Tesseract espera tinta oscura sobre fondo claro
        tess_in = 255 - lm
        pil_in = Image.fromarray(tess_in, mode="L")

        all_boundaries: set[int] = set()

        import io as _io
        import sys as _sys
        for psm in [7, 13]:
            try:
                # Suprime warnings de Tesseract a stderr
                _old_stderr = _sys.stderr
                _sys.stderr = _io.StringIO()
                try:
                    raw = pytesseract.image_to_boxes(
                        pil_in,
                        lang="spa",
                        config=f"--psm {psm} --oem 3",
                    )
                finally:
                    _sys.stderr = _old_stderr
                for ln in raw.strip().split("\n"):
                    parts = ln.split()
                    if len(parts) < 5:
                        continue
                    try:
                        bx1 = int(parts[1])
                        bx2 = int(parts[3])
                    except ValueError:
                        continue
                    orig_x1 = max(0, int((bx1 - border) / scale))
                    orig_x2 = max(0, int((bx2 - border) / scale))
                    if orig_x2 > orig_x1 and orig_x1 < w:
                        all_boundaries.add(min(orig_x1, w))
                        all_boundaries.add(min(orig_x2, w))
            except Exception:
                continue

        result = sorted(all_boundaries)
        if result:
            logger.info(
                f"Tesseract: {len(result)} fronteras "
                f"(PSM 7+13, escala×{scale:.1f})"
            )
        return result
    except Exception as e:
        logger.debug(f"Tesseract boundary error: {e}")
        return []

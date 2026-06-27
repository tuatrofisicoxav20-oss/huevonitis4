"""Orientación de imágenes para el preprocesamiento del extractor.

Cluster auto-contenido de funciones de orientación (lectura con EXIF, rotación en
múltiplos de 90°, detección por Tesseract OSD). Separado de
``extractor_preprocess`` para acotar ese módulo: estas funciones sólo dependen de
cv2/numpy/PIL/pytesseract y de ninguna otra del preprocesador, así que
``extractor_preprocess`` las importa y re-exporta sin ciclos. Lógica idéntica;
sólo cambió de archivo.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False


def imread_oriented(path: str):
    """Lee una imagen como BGR respetando la orientación EXIF (F5).

    cv2.imread ignora el tag de orientación, así que las fotos de celular (que
    guardan la imagen apaisada + un flag "rotar 90°") entran giradas y los glifos
    salen acostados. Abrimos con PIL, aplicamos exif_transpose y convertimos a
    BGR para el resto del pipeline. Si algo falla, cae a cv2.imread.
    """
    if not CV2_OK:
        return None
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
        arr = np.asarray(im)[:, :, ::-1]  # RGB → BGR
        return np.ascontiguousarray(arr)
    except Exception as exc:  # pragma: no cover - fallback robusto
        logger.debug("imread_oriented: fallback a cv2.imread (%s)", exc)
        return cv2.imread(path)


def _rotate_90s(img, degrees: int):
    """Rota la imagen en múltiplos de 90° (clockwise)."""
    d = degrees % 360
    if d == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if d == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if d == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _osd_rotation(img) -> int | None:
    """Ángulo (clockwise) que Tesseract OSD sugiere para enderezar, o None.

    Requiere osd.traineddata. WhatsApp/redes borran el EXIF al rotar los píxeles,
    así que exif_transpose NO endereza esas fotos; OSD detecta la orientación por
    CONTENIDO. Si OSD no está instalado o no hay confianza, devuelve None.
    """
    try:
        import pytesseract
        from PIL import Image
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(
            Image.fromarray(gray), output_type=pytesseract.Output.DICT,
        )
        rotate = int(osd.get("rotate", 0))
        conf = float(osd.get("orientation_conf", 0.0))
        if rotate % 360 != 0 and conf >= 1.0:
            logger.info("OSD: rotando %d° (conf=%.1f)", rotate, conf)
            return rotate
        return 0
    except Exception as exc:
        logger.debug("OSD no disponible/aplicable: %s", exc)
        return None


def orient_by_content(img, manual_orientation: int | None = None):
    """Endereza la imagen a 0/90/180/270 ANTES del deskew fino.

    Prioridad:
      1. `manual_orientation` (0/90/180/270) si el usuario lo fija — 100% fiable.
      2. Tesseract OSD (detección por contenido) si osd.traineddata está instalado.
      3. Si no hay ninguno, NO rota (deja la imagen como está): un heurístico
         geométrico para letra manuscrita suelta es poco fiable y rotar por error
         una foto que YA está derecha la empeora. Mejor dejar el override manual.
    """
    if img is None:
        return img
    if manual_orientation:
        return _rotate_90s(img, int(manual_orientation))
    rot = _osd_rotation(img)
    if rot:
        return _rotate_90s(img, rot)
    return img

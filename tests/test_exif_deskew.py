"""F5 — orientación EXIF y deskew robusto a rayas de cuaderno."""
import importlib.util

import pytest

_DEPS = all(importlib.util.find_spec(m) for m in ("PIL", "cv2", "numpy"))
pytestmark = pytest.mark.skipif(not _DEPS, reason="faltan PIL/cv2/numpy")


def test_imread_oriented_aplica_exif(tmp_path):
    """Una imagen apaisada con EXIF orientation=6 se lee ENDEREZADA (vertical).

    (En esta build cv2.imread también respeta EXIF; imread_oriented lo garantiza
    de forma explícita, independiente de la versión/flags de OpenCV.)
    """
    from PIL import Image
    from core.inkcore.extractor_preprocess import imread_oriented
    # imagen apaisada 120x40 marcada para rotar 90° al mostrarse
    img = Image.new("RGB", (120, 40), "white")
    exif = img.getexif()
    exif[274] = 6   # tag 0x0112 Orientation = 6
    p = tmp_path / "rot.jpg"
    img.save(p, exif=exif)

    oriented = imread_oriented(str(p))
    assert oriented is not None
    # orientation 6 → la imagen lógica es VERTICAL: alto (120) > ancho (40)
    assert oriented.shape[0] > oriented.shape[1], (
        f"no se enderezó por EXIF: {oriented.shape}")
    assert oriented.shape[0] == 120 and oriented.shape[1] == 40


def test_imread_oriented_sin_exif_no_cambia(tmp_path):
    """Sin EXIF, imread_oriented coincide en dimensiones con cv2.imread."""
    import cv2
    from PIL import Image
    from core.inkcore.extractor_preprocess import imread_oriented
    img = Image.new("RGB", (80, 50), "white")
    p = tmp_path / "plain.png"
    img.save(p)
    oriented = imread_oriented(str(p))
    raw = cv2.imread(str(p))
    assert oriented.shape[:2] == raw.shape[:2]


def test_deskew_ignora_rayas_horizontales(tmp_path):
    """El deskew no debe inventar un ángulo por las rayas perfectamente horizontales."""
    import numpy as np
    from core.inkcore.extractor_preprocess import ImagePreprocessor
    # lienzo con SOLO rayas horizontales largas (como un cuaderno en blanco)
    mask = np.zeros((200, 400), np.uint8)
    for y in range(20, 200, 30):
        mask[y:y + 2, 10:390] = 255
    pp = ImagePreprocessor()
    angle = pp._estimate_skew(mask, 400)
    # con puras rayas horizontales el skew debe ser ~0 o None (no un ángulo espurio)
    assert angle is None or abs(angle) < 1.5, f"deskew se enganchó a las rayas: {angle}"

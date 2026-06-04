"""Quinta tanda Paso 2 — orientación por contenido/manual.

El override manual (0/90/180/270) es el camino fiable y testeable. El path OSD
(detección por contenido) requiere osd.traineddata y se prueba a mano cuando está.
"""
import numpy as np
import pytest

pytest.importorskip("cv2")

from core.inkcore.extractor_preprocess import _rotate_90s, orient_by_content


def _tall_img():
    # 100 alto × 40 ancho, con una marca asimétrica para distinguir rotaciones.
    img = np.zeros((100, 40, 3), np.uint8)
    img[0:10, :] = 255  # banda arriba
    return img


def test_manual_90_swaps_dimensions():
    img = _tall_img()
    out = orient_by_content(img, 90)
    assert out.shape[:2] == (40, 100)  # alto<->ancho


def test_manual_180_keeps_dimensions():
    img = _tall_img()
    out = orient_by_content(img, 180)
    assert out.shape[:2] == (100, 40)
    # 180° = la banda blanca de arriba queda abajo
    assert out[-10:, :].mean() > out[:10, :].mean()


def test_manual_270_swaps_dimensions():
    img = _tall_img()
    out = orient_by_content(img, 270)
    assert out.shape[:2] == (40, 100)


def test_no_manual_no_osd_leaves_image_unchanged(monkeypatch):
    """Sin override manual y sin OSD, NO rota (no arruina imágenes ya derechas)."""
    import core.inkcore.extractor_preprocess as pp
    monkeypatch.setattr(pp, "_osd_rotation", lambda img: None)
    img = _tall_img()
    out = orient_by_content(img, None)
    assert out.shape == img.shape
    assert np.array_equal(out, img)


def test_osd_rotation_applied_when_available(monkeypatch):
    import core.inkcore.extractor_preprocess as pp
    monkeypatch.setattr(pp, "_osd_rotation", lambda img: 270)
    img = _tall_img()
    out = orient_by_content(img, None)
    assert out.shape[:2] == (40, 100)  # rotó 270 según OSD


def test_rotate_90s_identity_on_zero():
    img = _tall_img()
    assert np.array_equal(_rotate_90s(img, 0), img)

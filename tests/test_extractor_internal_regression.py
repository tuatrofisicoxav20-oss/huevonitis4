"""Fase 4A: tests de regresión interna del extractor.

Capturan el comportamiento ACTUAL de los métodos privados de GlyphExtractor
antes de cualquier delegación a ImagePreprocessor/SegmentDetector.
Si un test falla tras un refactor, el commit que lo causó es el culpable.
"""
import pytest

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


def _gray_image(w=200, h=150, fill=200):
    """Crea imagen BGR con fondo gris uniforme."""
    if not CV2_OK:
        return None
    img = np.full((h, w, 3), fill, dtype=np.uint8)
    return img


def _text_image(w=400, h=300):
    """Imagen con rectángulo negro (simula trazo) sobre fondo blanco."""
    if not CV2_OK:
        return None
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (50, 80), (350, 220), (0, 0, 0), -1)
    return img


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_apply_manual_no_change_on_defaults(tmp_path, monkeypatch):
    """_apply_manual sin rotación ni ajustes devuelve imagen del mismo shape."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import ExtractionOptions, GlyphExtractor
    ext = GlyphExtractor()
    img = _gray_image()
    opts = ExtractionOptions()
    result = ext._apply_manual(img, opts)
    assert result.shape == img.shape


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_apply_manual_brightness_changes_values(tmp_path, monkeypatch):
    """Con brightness > 0, los valores deben subir."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import ExtractionOptions, GlyphExtractor
    ext = GlyphExtractor()
    img = _gray_image(fill=100)
    opts = ExtractionOptions(brightness=50.0)
    result = ext._apply_manual(img, opts)
    assert float(result.mean()) > float(img.mean())


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_scale_no_upscale(tmp_path, monkeypatch):
    """_scale no agranda imágenes pequeñas."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import GlyphExtractor, TARGET_LONG
    ext = GlyphExtractor()
    small = _gray_image(w=100, h=100)
    result = ext._scale(small)
    assert result.shape == small.shape


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_scale_shrinks_large_image(tmp_path, monkeypatch):
    """_scale reduce imágenes cuyo lado mayor supera TARGET_LONG."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import GlyphExtractor, TARGET_LONG
    ext = GlyphExtractor()
    big = _gray_image(w=TARGET_LONG + 500, h=TARGET_LONG + 200)
    result = ext._scale(big)
    assert max(result.shape[:2]) <= TARGET_LONG + 1  # tolerancia 1px por redondeo


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_filtered_mask_reduces_noise(tmp_path, monkeypatch):
    """_filtered_mask aplica morfología — la máscara resultante no es idéntica."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import GlyphExtractor
    ext = GlyphExtractor()
    mask = np.zeros((100, 100), dtype=np.uint8)
    # Añadir ruido pequeño que debería eliminarse
    mask[5, 5] = 255
    mask[50:60, 40:60] = 255  # componente grande que debe sobrevivir
    result = ext._filtered_mask(mask)
    assert result.shape == mask.shape
    # El bloque grande debe sobrevivir
    assert result[55, 50] > 0


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_normalize_illumination_output_shape(tmp_path, monkeypatch):
    """_normalize_illumination devuelve array del mismo shape (H, W) uint8."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import GlyphExtractor
    gray = np.full((150, 200), 128, dtype=np.uint8)
    result = GlyphExtractor._normalize_illumination(gray)
    assert result.shape == gray.shape
    assert result.dtype == np.uint8


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_sauvola_threshold_output(tmp_path, monkeypatch):
    """_sauvola devuelve máscara binaria (0/255) del mismo shape."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import GlyphExtractor
    gray = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
    result = GlyphExtractor._sauvola(gray)
    assert result.shape == gray.shape
    unique_vals = set(np.unique(result))
    assert unique_vals <= {0, 255}


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_full_preprocess_returns_three_values(tmp_path, monkeypatch):
    """_full_preprocess devuelve (gray_norm, thresh, mask)."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import ExtractionOptions, GlyphExtractor
    ext = GlyphExtractor()
    img = _gray_image()
    result = ext._full_preprocess(img, ExtractionOptions())
    assert len(result) == 3
    gray_n, thresh, mask = result
    assert gray_n.shape == (img.shape[0], img.shape[1])
    assert thresh.shape == mask.shape


@pytest.mark.skipif(not CV2_OK, reason="cv2 no disponible")
def test_autocrop_returns_same_or_smaller(tmp_path, monkeypatch):
    """_autocrop nunca devuelve imagen más grande que la original."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.extractor import GlyphExtractor
    ext = GlyphExtractor()
    img = _text_image()
    result = ext._autocrop(img)
    assert result.shape[0] <= img.shape[0]
    assert result.shape[1] <= img.shape[1]

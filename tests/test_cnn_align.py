"""Tests del alineador juez-de-cortes (extractor_cnn_align) y su integración.

El modelo CNN se distribuye en el repo (core/inkcore/ai/models/), así que estos
tests pueden ejercitarlo de verdad; si faltara torch/modelo, degradan a skip.
"""
import importlib.util

import pytest

_DEPS = all(importlib.util.find_spec(m) for m in ("numpy", "cv2", "torch", "PIL"))
pytestmark = pytest.mark.skipif(not _DEPS, reason="faltan numpy/cv2/torch/PIL")


def _wf(ch):
    from core.inkcore.extractor_alignment import wf
    return wf(ch)


def _line_with_letters(text, cell=64):
    """Renglón sintético: una letra de fuente por celda, separadas. Máscara 255=tinta."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    n = len(text)
    img = Image.new("L", (cell * n, cell), 0)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 40)
    except Exception:
        font = ImageFont.load_default()
    for i, ch in enumerate(text):
        d.text((i * cell + 14, 8), ch, fill=255, font=font)
    return np.asarray(img)


def test_align_sin_clasificador_devuelve_none():
    from core.inkcore.extractor_cnn_align import align_by_classifier
    mask = _line_with_letters("abc")
    assert align_by_classifier(mask, ["a", "b", "c"], None, 64.0, _wf) is None

    class _Off:
        available = False
    assert align_by_classifier(mask, ["a", "b", "c"], _Off(), 64.0, _wf) is None


def test_align_n_chico_devuelve_none():
    from core.inkcore.ai.char_cnn import EMNISTCharClassifier
    from core.inkcore.extractor_cnn_align import align_by_classifier
    clf = EMNISTCharClassifier()
    if not clf.available:
        pytest.skip("modelo CNN no disponible")
    mask = _line_with_letters("a")
    assert align_by_classifier(mask, ["a"], clf, 64.0, _wf) is None


def test_align_devuelve_fronteras_ordenadas():
    from core.inkcore.ai.char_cnn import EMNISTCharClassifier
    from core.inkcore.extractor_cnn_align import align_by_classifier
    clf = EMNISTCharClassifier()
    if not clf.available:
        pytest.skip("modelo CNN no disponible")
    mask = _line_with_letters("abc")
    bounds = align_by_classifier(mask, ["a", "b", "c"], clf, 64.0, _wf)
    # Puede devolver None si no encuentra partición, pero si devuelve algo debe
    # ser n+1 fronteras estrictamente crecientes dentro del ancho.
    if bounds is not None:
        assert len(bounds) == 4
        assert all(bounds[i] < bounds[i + 1] for i in range(3))
        assert bounds[-1] <= mask.shape[1]


def test_clasificador_reconoce_letra_de_fuente():
    """El CNN sobre una letra nítida de fuente debe acertar razonablemente."""
    from core.inkcore.ai.char_cnn import EMNISTCharClassifier
    clf = EMNISTCharClassifier()
    if not clf.available:
        pytest.skip("modelo CNN no disponible")
    hits = 0
    for ch in "aehkotuw":
        mask = _line_with_letters(ch, cell=64)
        top = clf.predict_topk(mask, k=3)
        if top and ch in [c for c, _ in top]:
            hits += 1
    # No exigimos perfección (es OOD), pero sí señal clara sobre fuente nítida.
    assert hits >= 4, f"sólo {hits}/8 letras de fuente reconocidas en top-3"


def test_extraccion_con_cnn_no_crashea(tmp_path, monkeypatch):
    """Integración: con el CNN forzado, extraer de una imagen sintética no rompe."""
    import config
    monkeypatch.setattr(config, "USE_CNN_ALIGN", True, raising=False)
    from core.inkcore.ai.char_cnn import EMNISTCharClassifier
    if not EMNISTCharClassifier().available:
        pytest.skip("modelo CNN no disponible")
    from PIL import Image
    _line_with_letters("abcde", cell=70)
    # negro sobre blanco para que parezca foto real
    import numpy as np
    page = 255 - np.asarray(_line_with_letters("abcde", cell=70))
    p = tmp_path / "linea.png"
    Image.fromarray(page).convert("RGB").save(p)
    from core.inkcore.extractor import ExtractionOptions, GlyphExtractor
    ex = GlyphExtractor()
    glyphs = ex.extract_from_image(str(p), "abcde", ExtractionOptions())
    assert isinstance(glyphs, list)  # no crashea; el conteo puede variar

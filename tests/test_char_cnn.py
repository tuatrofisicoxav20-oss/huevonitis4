"""Tests del clasificador de caracteres (preproceso + degradación elegante).

No dependen del modelo entrenado: validan el encuadre EMNIST y que sin modelo
todo degrada a 'no disponible' sin romper el extractor.
"""
import importlib.util

import pytest

_DEPS = all(importlib.util.find_spec(m) for m in ("numpy", "cv2"))
pytestmark = pytest.mark.skipif(not _DEPS, reason="faltan numpy/cv2")


def test_label_char_roundtrip():
    from core.inkcore.ai.char_cnn import char_to_label, label_to_char
    for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz", start=1):
        assert char_to_label(ch) == i
        assert label_to_char(i) == ch
    # ñ no existe en EMNIST → None
    assert char_to_label("ñ") is None
    assert char_to_label("") is None
    # mayúsculas se fusionan con minúsculas
    assert char_to_label("A") == 1


def test_preprocess_encuadre_emnist():
    import numpy as np
    from core.inkcore.ai.char_cnn import preprocess_to_emnist
    # mancha de tinta en una esquina de una imagen grande
    mask = np.zeros((120, 80), np.uint8)
    mask[10:60, 12:40] = 255
    out = preprocess_to_emnist(mask)
    assert out is not None
    assert out.shape == (28, 28)
    assert out.dtype == np.float32
    assert 0.0 <= float(out.min()) and float(out.max()) <= 1.0
    # la tinta queda centrada (los bordes del lienzo quedan vacíos)
    assert float(out[0].sum()) == 0.0 and float(out[-1].sum()) == 0.0


def test_preprocess_vacio_devuelve_none():
    import numpy as np
    from core.inkcore.ai.char_cnn import preprocess_to_emnist
    assert preprocess_to_emnist(np.zeros((30, 30), np.uint8)) is None
    assert preprocess_to_emnist(None) is None


def test_clasificador_sin_modelo_degrada(tmp_path):
    import numpy as np
    from core.inkcore.ai.char_cnn import EMNISTCharClassifier
    clf = EMNISTCharClassifier(model_path=str(tmp_path / "no_existe.pt"))
    assert clf.available is False
    mask = np.zeros((30, 30), np.uint8)
    mask[5:25, 8:22] = 255
    assert clf.score(mask, "a") is None
    assert clf.predict_topk(mask) == []

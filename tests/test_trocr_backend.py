"""Tests del TrOCRBackend (Fase 0.5) que NO descargan el modelo.

La inferencia real requiere bajar ~400MB y CPU lento, así que acá se prueba sólo
lo que no necesita el modelo: registro del backend y la segmentación de líneas
por proyección horizontal (la lógica propia, no TrOCR).
"""
import importlib.util

import pytest

_CV = importlib.util.find_spec("cv2") is not None
_NP = importlib.util.find_spec("numpy") is not None


def test_backend_registrado():
    from core.ocr.backends import REGISTRY
    assert "trocr" in REGISTRY


@pytest.mark.skipif(not (_CV and _NP), reason="cv2/numpy no instalados")
def test_segment_lines_cuenta_renglones():
    import numpy as np

    from core.ocr.backends.trocr import TrOCRBackend
    # Lienzo blanco con 3 bandas de "tinta" (renglones) separadas por espacio.
    gray = np.full((300, 400), 255, np.uint8)
    for cy in (50, 150, 250):
        gray[cy - 8:cy + 8, 40:360] = 30  # banda oscura ancha
    bands = TrOCRBackend._segment_lines(gray)
    assert len(bands) == 3
    # Cada banda en orden y dentro del lienzo.
    ys = [(a + b) // 2 for a, b in bands]
    assert ys == sorted(ys)
    assert all(0 <= a < b <= 300 for a, b in bands)


@pytest.mark.skipif(not (_CV and _NP), reason="cv2/numpy no instalados")
def test_segment_lines_vacio_sin_tinta():
    import numpy as np

    from core.ocr.backends.trocr import TrOCRBackend
    assert TrOCRBackend._segment_lines(np.full((100, 100), 255, np.uint8)) == []

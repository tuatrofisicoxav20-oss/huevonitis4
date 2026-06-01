"""EasyOCRDetector: registro y lógica de preprocesado (sin bajar el modelo CRAFT).

Hallazgo registrado: se integró un detector moderno (EasyOCR/CRAFT) pero MEDIDO
no mejora la extracción de letra suelta (CRAFT agrupa por línea/palabra, no por
carácter: 2-4 cajas por imagen, no ~27). Queda OPCIONAL y apagado por defecto
(config.GLYPH_DETECTOR="classic_cv"). Estos tests sólo validan el cableado, no
disparan inferencia.
"""
import importlib.util

import pytest

_CV2 = importlib.util.find_spec("cv2") is not None


def test_easyocr_registrado():
    from core.inkcore import glyph_detectors as gd
    assert "easyocr" in gd.REGISTRY
    det = gd.get_detector("easyocr")
    assert det.name == "easyocr"
    # get_available no debe romper aunque easyocr no esté instalado
    assert "easyocr" in gd.get_available()


def test_get_detector_desconocido_cae_a_classic():
    from core.inkcore import glyph_detectors as gd
    det = gd.get_detector("no_existe_xyz")
    assert det.name == "classic_cv"


@pytest.mark.skipif(not _CV2, reason="cv2 no instalado")
def test_prep_invierte_mascara_binaria():
    """Una máscara (tinta blanca sobre negro) se invierte a tinta oscura sobre
    blanco, que es lo que CRAFT espera. Una foto normal no se invierte."""
    import numpy as np

    from core.inkcore.glyph_detectors.easyocr_det import EasyOCRDetector
    # Máscara: fondo negro (0), poca tinta blanca → debe invertirse
    mask = np.zeros((40, 120, 3), dtype=np.uint8)
    mask[10:30, 10:30] = 255
    out = EasyOCRDetector._prep(mask)
    # Tras invertir, el fondo (antes negro) queda claro
    assert out[0, 0, 0] > 200
    # Imagen clara (foto) no se invierte
    photo = np.full((40, 120, 3), 240, dtype=np.uint8)
    photo[15:25, 50:70] = 20
    out2 = EasyOCRDetector._prep(photo)
    assert out2[0, 0, 0] > 200

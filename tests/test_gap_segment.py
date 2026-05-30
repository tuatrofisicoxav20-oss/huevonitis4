"""Tests de segmentación por espacios reales entre letras."""
import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from core.inkcore.extractor_gap_segment import segment_by_gaps  # noqa: E402


def _vpp_groups(centers, width=6, length=100, height=10.0):
    vpp = np.zeros(length, dtype=np.float32)
    for c in centers:
        vpp[max(0, c - width // 2):c + width // 2] = height
    return vpp


def test_letras_separadas_da_n_mas_1_fronteras():
    """5 grupos de tinta bien separados → 5 letras, 6 fronteras."""
    vpp = _vpp_groups([10, 30, 50, 70, 90])
    bounds = segment_by_gaps(vpp, 5, 95, 5)
    assert bounds is not None
    assert len(bounds) == 6
    assert bounds == sorted(bounds)  # crecientes


def test_ligado_sin_gaps_devuelve_none():
    """Tinta continua (cursiva ligada) → no segmenta por gaps, cae a posicional."""
    vpp = np.full(100, 10.0, dtype=np.float32)
    assert segment_by_gaps(vpp, 0, 100, 5) is None


def test_fragmentos_se_fusionan_a_n():
    """6 grupos para 4 letras (2 fragmentadas en 2 trozos) → fusiona a 4."""
    # Pares muy juntos (fragmentos) + 2 letras sueltas
    vpp = _vpp_groups([10, 14, 40, 60, 84, 88], width=4)
    bounds = segment_by_gaps(vpp, 5, 95, 4)
    assert bounds is not None
    assert len(bounds) == 5


def test_letras_pegadas_se_parten_a_n():
    """2 grupos para 3 letras (dos pegadas con valle interno) → parte a 3."""
    vpp = np.zeros(120, dtype=np.float32)
    vpp[10:30] = 10            # letra 1
    # bloque ancho con valle interno (dos letras pegadas)
    vpp[50:70] = 10
    vpp[70:74] = 1            # valle (frontera real)
    vpp[74:94] = 10
    bounds = segment_by_gaps(vpp, 5, 110, 3)
    assert bounds is not None
    assert len(bounds) == 4


def test_desajuste_enorme_devuelve_none():
    """1 solo grupo para 8 letras (desajuste >2x) → None (no son letras separadas)."""
    vpp = _vpp_groups([50], width=8)
    assert segment_by_gaps(vpp, 5, 95, 8) is None

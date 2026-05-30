"""Tests de assess_glyph: la cobertura de tinta sale del canal correcto."""
import pytest


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_assess_glyph_opaco_no_infla_cobertura(tmp_path):
    """Un glifo OPACO (alpha=255) con poca tinta no debe dar ink_coverage=1.0.

    Regresión: assess_glyph medía el canal alpha; en un glifo opaco (bulk/legacy)
    alpha=255 en todo daba ink_coverage=1.0 y tier Gold falso. Ahora la cobertura
    sale de la tinta real (luminancia) cuando el alpha es uniforme.
    """
    import numpy as np
    from PIL import Image

    from core.inkcore.quality import assess_glyph
    # 40x40 opaco (alpha=255), fondo blanco, cuadrado negro = 25% del área = tinta
    arr = np.full((40, 40, 4), 255, dtype=np.uint8)
    arr[10:30, 10:30, :3] = 0
    p = tmp_path / "opaco.png"
    Image.fromarray(arr).save(p)
    m = assess_glyph(str(p))
    assert m["ink_coverage"] < 0.40, f"cobertura inflada para glifo opaco: {m['ink_coverage']}"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_assess_glyph_extractor_alpha_se_mide_bien(tmp_path):
    """Un glifo del extractor (forma en alpha, RGB blanco) se mide por el alpha."""
    import numpy as np
    from PIL import Image

    from core.inkcore.quality import assess_glyph
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :, :3] = 255            # RGB blanco uniforme
    arr[10:30, 10:30, 3] = 255     # forma (25% del área) solo en el alpha
    p = tmp_path / "extractor.png"
    Image.fromarray(arr).save(p)
    m = assess_glyph(str(p))
    assert 0.15 < m["ink_coverage"] < 0.40, f"cobertura inesperada: {m['ink_coverage']}"

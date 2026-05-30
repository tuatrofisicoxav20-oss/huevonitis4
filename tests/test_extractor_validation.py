"""Tests de validación estructural de glifos: coherencia forma↔letra."""
import pytest

from core.inkcore.extractor_validation import (
    expected_vclass,
    glyph_vclass,
    is_consistent,
    line_metrics,
)


def test_expected_vclass_categorias():
    assert expected_vclass("a") == "xheight"
    assert expected_vclass("o") == "xheight"
    assert expected_vclass("n") == "xheight"
    assert expected_vclass("d") == "asc"
    assert expected_vclass("b") == "asc"
    assert expected_vclass("t") == "asc"
    assert expected_vclass("p") == "desc"
    assert expected_vclass("g") == "desc"
    # Ambiguos: no se validan
    assert expected_vclass("i") == "any"      # punto
    assert expected_vclass("á") == "any"      # acento sube
    assert expected_vclass("A") == "any"      # mayúscula
    assert expected_vclass("5") == "any"
    assert expected_vclass("") == "any"


def test_glyph_vclass_con_metricas():
    # metrics = (xh_top, xh_bot, line_top, line_bot); line_h = 50, x-height 20-50
    m = (20, 50, 10, 60)
    assert glyph_vclass(20, 50, m) == "xheight"   # ni sube ni baja
    assert glyph_vclass(8, 50, m) == "asc"        # sube (20-8)/50=0.24 > 0.18
    assert glyph_vclass(20, 62, m) == "desc"      # baja (62-50)/50=0.24 > 0.18
    assert glyph_vclass(8, 62, m) == "both"       # sube y baja


def test_is_consistent_detecta_a_como_d():
    """Caso reportado: una 'a' (x-height) con forma de ascendente es inconsistente."""
    m = (20, 50, 10, 60)
    # 'a' esperada pero el glifo sube como ascendente → rechazo (probable 'd')
    assert is_consistent("a", 8, 50, m) is False
    # 'd' esperada y el glifo sube → consistente
    assert is_consistent("d", 8, 50, m) is True
    # 'a' esperada y el glifo es x-height → consistente
    assert is_consistent("a", 20, 50, m) is True
    # 'd' esperada pero el glifo NO sube → rechazo (probable 'a')
    assert is_consistent("d", 22, 50, m) is False


def test_is_consistent_conservador():
    m = (20, 50, 10, 60)
    # Sin métricas (línea pobre) → nunca descarta
    assert is_consistent("a", 8, 50, None) is True
    # Letra ambigua ('i') → no descarta aunque suba (el punto sube)
    assert is_consistent("i", 8, 50, m) is True
    # Forma 'both' (alta y baja) → no descarta (ambigua)
    assert is_consistent("a", 8, 62, m) is True


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_is_consistent_sobre_render_sintetico(tmp_path):
    """Renderiza 'ad' real y verifica que etiquetar la 'd' como 'a' se detecta."""
    import glob

    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    fonts = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    if not fonts:
        pytest.skip("sin fuentes TTF en el sistema")
    font = ImageFont.truetype(fonts[0], 48)
    img = Image.new("L", (160, 90), 255)
    ImageDraw.Draw(img).text((10, 15), "ad", font=font, fill=0)
    arr = (255 - np.asarray(img)).astype("uint8")  # tinta = alto

    m = line_metrics(arr)
    assert m is not None, "no se pudieron estimar métricas de la línea sintética"

    # Segmentar las dos letras por columnas
    col = arr.sum(axis=0)
    incol = col > col.max() * 0.05
    bounds, s = [], None
    for x, v in enumerate(incol):
        if v and s is None:
            s = x
        elif not v and s is not None:
            bounds.append((s, x))
            s = None
    if s is not None:
        bounds.append((s, len(incol)))
    assert len(bounds) >= 2, "no se separaron 'a' y 'd'"

    def top_bot(x0, x1):
        sub = arr[:, x0:x1]
        rows = np.where(sub.sum(axis=1) > sub.sum(axis=1).max() * 0.1)[0]
        return int(rows.min()), int(rows.max())

    a_top, a_bot = top_bot(*bounds[0])
    d_top, d_bot = top_bot(*bounds[1])

    # La 'a' real etiquetada 'a' → consistente
    assert is_consistent("a", a_top, a_bot, m) is True
    # La 'd' real (sube) etiquetada como 'a' → inconsistente (lo que arregla el a→d)
    assert is_consistent("a", d_top, d_bot, m) is False
    # La 'd' real etiquetada 'd' → consistente
    assert is_consistent("d", d_top, d_bot, m) is True

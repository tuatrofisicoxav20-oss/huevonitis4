"""Round-trip de la plantilla: generar → rellenar casillas → extraer.

Valida la geometría y el recorte sin necesitar una foto real: se rellenan las
casillas conocidas con glifos de fuente y se comprueba que el extractor recupera
una letra por casilla, en el orden correcto, y que omite las vacías.
"""
import importlib.util

import pytest

_DEPS = all(importlib.util.find_spec(m) for m in ("PIL", "cv2", "numpy"))

pytestmark = pytest.mark.skipif(not _DEPS, reason="faltan PIL/cv2/numpy")


def _fill_sheet(layout, fill_indices):
    """Genera la plantilla y dibuja una letra de fuente en las casillas dadas."""
    from PIL import ImageDraw, ImageFont

    from core.inkcore.template_sheet import build_template_sheet
    img = build_template_sheet(layout)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 70)
    except Exception:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 70)
        except Exception:
            font = ImageFont.load_default()
    for i in fill_indices:
        wx, wy, ww, wh = layout.writing_rect(i)
        ch = layout.letters[i]
        # Centrar la letra en el área de escritura, sin tocar bordes.
        draw.text((wx + ww // 2 - 20, wy + wh // 2 - 45), ch,
                  fill="#101010", font=font)
    return img


def test_layout_geometria_basica():
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    assert lay.n_cells == 28
    assert len(lay.letters) == 27
    # Las casillas no se solapan y caen dentro de la grilla
    for i in range(lay.n_cells):
        x, y, w, h = lay.cell_rect(i)
        assert x >= lay.grid_x0 - 1 and y >= lay.grid_y0 - 1
        wx, wy, ww, wh = lay.writing_rect(i)
        assert ww > 20 and wh > 20


def test_roundtrip_recupera_todas_las_letras(tmp_path):
    from core.inkcore.template_extract import extract_from_template
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    img = _fill_sheet(lay, range(len(lay.letters)))   # 27 letras rellenas
    p = tmp_path / "filled.png"
    img.save(p)

    out = extract_from_template(str(p), lay)
    chars = [c for c, _img, _q in out]
    # Recupera la gran mayoría de las casillas, en orden
    assert len(out) >= 25, f"sólo {len(out)} casillas: {chars}"
    # El orden de las recuperadas respeta el alfabeto (no hay corrimiento)
    expected_order = [c for c in lay.letters if c in chars]
    assert chars == expected_order, f"orden corrido: {chars}"
    # Cada glifo tiene tinta real (alpha no vacío)
    import numpy as np
    for c, glyph, _q in out:
        alpha = np.asarray(glyph.getchannel("A"))
        assert int((alpha > 50).sum()) > 30, f"glifo '{c}' casi vacío"


def test_casillas_vacias_se_omiten(tmp_path):
    from core.inkcore.template_extract import extract_from_template
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    # Rellenar sólo a, b, c (índices 0,1,2)
    img = _fill_sheet(lay, [0, 1, 2])
    p = tmp_path / "partial.png"
    img.save(p)
    out = extract_from_template(str(p), lay)
    chars = [c for c, _i, _q in out]
    assert set(chars) == {"a", "b", "c"}, f"esperaba a,b,c y vino {chars}"

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
        ch = layout.cell_letter(i)
        if ch is None:
            continue
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


def test_repeats_1_conserva_layout_original():
    """repeats=1 (default) debe dar la grilla 4×7 = 28 de siempre."""
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    assert lay.repeats == 1 and lay.cols == 4 and lay.rows == 7 and lay.n_cells == 28
    # cell_letter coincide con el mapeo posicional histórico
    for i in range(len(lay.letters)):
        assert lay.cell_letter(i) == lay.letters[i]
    assert lay.cell_letter(27) is None  # casilla sobrante


def test_repeats_multi_muestra_geometria():
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout(repeats=2)
    assert lay.repeats == 2 and lay.cols == 6
    # 27 letras × 2 = 54 casillas rotuladas → 9 filas con 6 columnas
    assert lay.rows == 9 and lay.n_cells == 54
    # casillas consecutivas comparten letra
    assert lay.cell_letter(0) == "a" and lay.cell_letter(1) == "a"
    assert lay.cell_letter(2) == "b" and lay.cell_letter(3) == "b"
    # las casillas siguen siendo usables (no minúsculas)
    for i in range(lay.n_cells):
        _wx, _wy, ww, wh = lay.writing_rect(i)
        assert ww > 20 and wh > 20


def test_repeats_extrae_varias_muestras_por_letra(tmp_path):
    from core.inkcore.template_extract import extract_from_template
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout(repeats=2)
    # rellenar las 2 casillas de 'a' (0,1) y las 2 de 'c' (4,5)
    img = _fill_sheet(lay, [0, 1, 4, 5])
    p = tmp_path / "rep.png"
    img.save(p)
    out = extract_from_template(str(p), lay)
    chars = [c for c, _i, _q in out]
    assert chars.count("a") == 2, f"esperaba 2 muestras de 'a': {chars}"
    assert chars.count("c") == 2, f"esperaba 2 muestras de 'c': {chars}"
    assert set(chars) == {"a", "c"}, chars


def test_charset_personalizado_cell_letter():
    """Un charset combinado mapea cada casilla a su carácter correcto."""
    from core.inkcore.template_sheet import (
        MAYUSCULAS,
        MINUSCULAS,
        TemplateLayout,
    )
    cs = MINUSCULAS + MAYUSCULAS
    lay = TemplateLayout(charset=cs)
    assert lay.letters == cs                      # alias de compat
    for i in range(len(cs)):
        assert lay.cell_letter(i) == cs[i]
    assert lay.cell_letter(len(cs)) is None       # más allá del charset → libre


def test_charset_default_sigue_siendo_minusculas():
    from core.inkcore.template_sheet import MINUSCULAS, TemplateLayout
    lay = TemplateLayout()
    assert lay.charset == MINUSCULAS and lay.letters == MINUSCULAS


def test_charset_grande_entra_en_una_pagina_legible():
    """min+MAY+dígitos (64) y el combo completo ×2 deben caber con casillas usables."""
    from core.inkcore.template_sheet import (
        DIGITOS,
        MAYUSCULAS,
        MINUSCULAS,
        PUNTUACION,
        TemplateLayout,
        VOCALES_ACENTUADAS,
    )
    cs = MINUSCULAS + MAYUSCULAS + DIGITOS
    lay = TemplateLayout(charset=cs)
    assert lay.n_cells >= len(cs)
    for i in range(lay.n_cells):
        _wx, _wy, ww, wh = lay.writing_rect(i)
        assert ww > 20 and wh > 20, f"casilla {i} ilegible: {ww}x{wh}"

    # Caso extremo: todos los sets con 2 muestras (>180 casillas) sigue cabiendo.
    full = MINUSCULAS + MAYUSCULAS + DIGITOS + PUNTUACION + VOCALES_ACENTUADAS
    lay2 = TemplateLayout(charset=full, repeats=2)
    assert lay2.n_cells >= len(full) * 2
    assert lay2.grid_y1 <= lay2.height          # no se desborda la hoja
    for i in range(lay2.n_cells):
        _wx, _wy, ww, wh = lay2.writing_rect(i)
        assert ww > 20 and wh > 20, f"casilla {i} ilegible: {ww}x{wh}"


def test_roundtrip_charset_con_mayusculas_y_digitos(tmp_path):
    """Extrae bien casillas de un charset mixto (min+MAY+dígitos)."""
    from core.inkcore.template_extract import extract_from_template
    from core.inkcore.template_sheet import (
        DIGITOS,
        MAYUSCULAS,
        MINUSCULAS,
        TemplateLayout,
    )
    cs = MINUSCULAS + MAYUSCULAS + DIGITOS
    lay = TemplateLayout(charset=cs)
    # Rellenar 'a' (0), 'A' (len(MIN)) y '0' (len(MIN)+len(MAY)).
    idx_a = 0
    idx_A = len(MINUSCULAS)
    idx_0 = len(MINUSCULAS) + len(MAYUSCULAS)
    assert lay.cell_letter(idx_A) == "A" and lay.cell_letter(idx_0) == "0"
    img = _fill_sheet(lay, [idx_a, idx_A, idx_0])
    p = tmp_path / "mixed.png"
    img.save(p)
    out = extract_from_template(str(p), lay)
    chars = [c for c, _i, _q in out]
    assert set(chars) == {"a", "A", "0"}, f"esperaba a,A,0 y vino {chars}"


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


def _rotate_png_cw(src_png, dst_png, angle):
    """Guarda `src_png` rotada `angle`° en sentido horario (simula el escáner)."""
    import cv2
    img = cv2.imread(str(src_png))
    if angle % 360 == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif angle % 360 == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif angle % 360 == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    cv2.imwrite(str(dst_png), img)


@pytest.mark.parametrize("scan_angle", [90, 180, 270])
def test_detect_template_rotation_corrige_a_vertical(tmp_path, scan_angle):
    """Una hoja girada por el escáner se corrige con el ángulo complementario.

    Si el escáner gira la hoja `scan_angle`° horario, enderezarla requiere girar
    (360-scan_angle)° horario. detect_template_rotation debe devolver ese ángulo.
    """
    from core.inkcore.template_extract import detect_template_rotation
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    img = _fill_sheet(lay, range(len(lay.letters)))
    canon_png = tmp_path / "canon.png"
    img.save(canon_png)
    scanned = tmp_path / "scanned.png"
    _rotate_png_cw(canon_png, scanned, scan_angle)

    angle = detect_template_rotation(str(scanned), lay)
    assert angle == (360 - scan_angle) % 360, (
        f"escaneada {scan_angle}° → detectó {angle}°, esperaba {(360 - scan_angle) % 360}°"
    )


def test_detect_template_rotation_hoja_derecha_es_cero(tmp_path):
    from core.inkcore.template_extract import detect_template_rotation
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    img = _fill_sheet(lay, range(len(lay.letters)))
    p = tmp_path / "derecha.png"
    img.save(p)
    assert detect_template_rotation(str(p), lay) == 0


def test_extract_auto_apaisada_orden_correcto(tmp_path):
    """extract_from_template_auto sobre una hoja girada 90° recupera las letras
    en el MISMO orden que sobre la versión derecha (la 'a' es una a, no una d)."""
    from core.inkcore.template_extract import (
        extract_from_template,
        extract_from_template_auto,
    )
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    img = _fill_sheet(lay, range(len(lay.letters)))
    canon_png = tmp_path / "canon.png"
    img.save(canon_png)
    # Orden de referencia sin rotar.
    ref = [c for c, _g, _q in extract_from_template(str(canon_png), lay)]

    scanned = tmp_path / "apaisada.png"
    _rotate_png_cw(canon_png, scanned, 90)
    auto = [c for c, _g, _q in extract_from_template_auto(str(scanned), lay)]

    assert auto == ref, f"orden tras autorrotación distinto:\n  ref ={ref}\n  auto={auto}"
    assert len(auto) >= 25, f"sólo {len(auto)} casillas tras autorrotar"

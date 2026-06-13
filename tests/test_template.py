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
        x, y, _w, _h = lay.cell_rect(i)
        assert x >= lay.grid_x0 - 1 and y >= lay.grid_y0 - 1
        _wx, _wy, ww, wh = lay.writing_rect(i)
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
        VOCALES_ACENTUADAS,
        TemplateLayout,
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


def test_fiducials_con_iluminacion_despareja():
    """E1: una sombra fuerte de un lado no debe romper la detección.

    Con Otsu global el umbral único (medido ~182 en este sintético) binariza
    rota la mitad oscura de la foto y los marcadores no aparecen como cuadrados
    sólidos. La binarización adaptativa los recupera. Reproduce la causa raíz 1
    del lote real de fotos de celular (0/29 páginas con fiduciales).
    """
    import cv2
    import numpy as np

    from core.inkcore.template_extract import _detect_fiducials
    from core.inkcore.template_sheet import TemplateLayout, build_template_sheet
    lay = TemplateLayout()
    sheet = np.asarray(build_template_sheet(lay).convert("L")).astype(np.float64)
    ramp = np.linspace(0.45, 1.0, sheet.shape[1])[None, :]   # sombra izq→der
    base = np.where(sheet < 128, 90.0, 255.0)
    grad = np.clip(base * ramp, 0, 255).astype(np.uint8)
    # Sanity del sintético: el Otsu global de esta imagen está por encima del
    # papel sombreado (es el escenario que rompía al detector viejo).
    thr_val, _ = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    assert thr_val > 115, f"sintético no reproduce el caso (otsu={thr_val})"

    fid = _detect_fiducials(grad, lay)
    assert fid is not None, "fiduciales no detectados con iluminación despareja"
    expected = lay.fiducial_centers()
    for (cx, cy), (ex, ey) in zip(fid, expected, strict=True):
        assert abs(cx - ex) < 10 and abs(cy - ey) < 10, (
            f"centro corrido: ({cx:.0f},{cy:.0f}) vs ({ex},{ey})")


def test_fiducials_foto_con_perspectiva_y_fondo():
    """E1: hoja en perspectiva leve sobre fondo de mesa → detecta los 4.

    El área mínima del candidato es absoluta (no relativa a la foto): el fondo
    alrededor de la hoja no debe descalificar los marcadores encogidos.
    """
    import cv2
    import numpy as np

    from core.inkcore.template_extract import _detect_fiducials
    from core.inkcore.template_sheet import TemplateLayout, build_template_sheet
    lay = TemplateLayout()
    sheet = np.asarray(build_template_sheet(lay).convert("L"))
    h, w = sheet.shape[:2]
    canvas_w, canvas_h = 2000, 2600                    # "foto" más grande que la hoja
    src = np.array([(0, 0), (w, 0), (0, h), (w, h)], dtype=np.float32)
    dst = np.array([(330, 300), (1700, 360), (290, 2300), (1730, 2210)],
                   dtype=np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    photo = cv2.warpPerspective(sheet, M, (canvas_w, canvas_h),
                                flags=cv2.INTER_LINEAR, borderValue=140)  # mesa gris
    fid = _detect_fiducials(photo, lay)
    assert fid is not None, "no detectó los marcadores en la foto con fondo"
    # Los centros detectados deben caer cerca de la proyección de los reales.
    real = cv2.perspectiveTransform(
        np.array([lay.fiducial_centers()], dtype=np.float32), M)[0]
    for (cx, cy), (ex, ey) in zip(fid, real, strict=True):
        assert abs(cx - ex) < 15 and abs(cy - ey) < 15, (
            f"esquina corrida: ({cx:.0f},{cy:.0f}) vs ({ex:.0f},{ey:.0f})")


def test_fiducials_marcador_cortado_no_inventa_esquina():
    """E1: con 3 marcadores en encuadre y una palabra oscura, devolver None.

    Reproduce el falso positivo medido en el lote real: la foto cortó un
    marcador y una palabra en negrita del título pasaba como cuarta esquina →
    rectificación basura. Mejor 'sin fiduciales' (cae a grilla) que eso.
    """
    import numpy as np

    from core.inkcore.template_extract import _detect_fiducials
    from core.inkcore.template_sheet import TemplateLayout, build_template_sheet
    lay = TemplateLayout()
    sheet = np.asarray(build_template_sheet(lay).convert("L")).copy()
    # "Cortar" el marcador BR: taparlo con papel.
    cx, cy = lay.fiducial_centers()[3]
    half = lay.fiducial // 2 + 4
    sheet[cy - half:cy + half, cx - half:cx + half] = 255
    # Palabra corta y oscura cerca del título (como "UNA" en negrita).
    sheet[150:185, 800:842] = 20
    assert _detect_fiducials(sheet, lay) is None


def test_fiducials_rechaza_motas_centrales():
    """E1: 4 manchas en el centro NO deben pasar por marcadores (cuadrilátero chico)."""
    import numpy as np

    from core.inkcore.template_extract import _detect_fiducials
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    img = np.full((1754, 1240), 255, np.uint8)
    for (cx, cy) in ((580, 820), (660, 820), (580, 900), (660, 900)):
        img[cy - 20:cy + 20, cx - 20:cx + 20] = 30
    assert _detect_fiducials(img, lay) is None


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


def test_grid_bbox_descarta_bordes_y_titulo():
    """E4: el bbox de la grilla excluye una sombra de borde y la banda de título.

    Reproduce las dos causas del Bug C (medidas en el lote real): una sombra
    pegada al borde derecho estiraba el bbox a todo el ancho (desalineando la
    última columna) y el título arriba corría la grilla (perdiendo la fila 0).
    """
    import numpy as np

    from core.inkcore.template_extract import _grid_content_bbox
    from core.inkcore.template_sheet import TemplateLayout, build_template_sheet
    lay = TemplateLayout()
    img = np.asarray(build_template_sheet(lay).convert("L")).copy()
    _h, w = img.shape
    img[:, w - 6:] = 20            # sombra de borde derecho (como en las fotos)
    _x0, y0, x1, _y1 = _grid_content_bbox(img)
    assert x1 < w - 6, f"el bbox se estiró al borde (x1={x1}, w={w})"
    # El título canónico está por encima de la grilla (grid_y0); el bbox debe
    # empezar cerca de la primera fila de casillas, no en el título.
    assert y0 >= lay.grid_y0 - lay.cell_h, f"bbox incluye el título (y0={y0}, grid_y0={lay.grid_y0})"


def test_cell_ink_mask_conserva_trazo_delgado():
    """E4: un trazo fino (como una 'i' con punto) ya no se descarta como vacío.

    El piso de tinta viejo (h·w·0.004 ≈ 264px en esta celda) rechazaba trazos
    delgados; el nuevo max(25, h·w·0.0015 ≈ 99px) los conserva. El trazo se hace
    corto (110px, < 0.55·alto) para no disparar el supresor de líneas de grilla.
    """
    import numpy as np

    from core.inkcore.template_extract import _cell_ink_mask
    cell = np.full((300, 220), 255, np.uint8)     # celda clara (66000 px)
    cell[90:200, 104:114] = 30                     # asta fina (~10px ancho, 110 alto)
    cell[70:80, 105:113] = 30                      # punto de la 'i'
    mask = _cell_ink_mask(cell)
    assert mask is not None, "el trazo delgado se descartó como vacío"
    assert int((mask > 0).sum()) > 80


def test_estimate_grid_dims_distingue_acentos_de_digitos():
    """Auto non-az: la autocorrelación separa 6 columnas (acentos) de 9 (dígitos).

    Es la señal que score_layout_cheap NO da (premia grillas finas). Sobre hojas
    sintéticas rellenas, el nº de columnas estimado debe coincidir con el preset.
    """
    import numpy as np

    from core.inkcore.template_extract import (
        _deskew,
        _estimate_grid_dims,
        _estimate_skew,
        _grid_content_bbox,
    )
    from core.inkcore.template_sheet import TEMPLATE_PRESETS
    for name, exp_cols in (("acentuadas_x12", 6), ("digitos_signos_x8", 9)):
        lay = TEMPLATE_PRESETS[name]
        img = _fill_sheet(lay, range(lay.cols * lay.rows))
        gray = np.asarray(img.convert("L"))
        dk = _deskew(gray, _estimate_skew(gray))
        dims = _estimate_grid_dims(dk, _grid_content_bbox(dk))
        assert dims is not None, f"{name}: sin periodicidad"
        cols, _rows, conf = dims
        assert abs(cols - exp_cols) <= 1, f"{name}: cols={cols} esperaba {exp_cols}"
        assert conf > 0.3


def test_estimate_grid_dims_hoja_vacia_devuelve_none():
    """Auto non-az: sin tinta (hoja en blanco) no hay periodicidad → None."""
    import numpy as np

    from core.inkcore.template_extract import _estimate_grid_dims
    blank = np.full((1400, 1000), 255, np.uint8)
    assert _estimate_grid_dims(blank, (50, 50, 950, 1350)) is None


def test_extract_pdf_pages_auto_identifica_acentos(tmp_path):
    """Auto non-az: una hoja de acentos se identifica como acentuadas_x12.

    Antes quedaba siempre suspect (el CNN no cubre á/é/ñ). Ahora la rama non-az
    la identifica por geometría (6 columnas) y la extrae sin marcarla suspect.

    Se fuerza el camino non-az pasando clf=None: con una fuente sintética las
    vocales acentuadas (á,é,í) son casi idénticas a sus bases (a,e,i) a 28×28 y
    el CNN las colaría por la rama a-z — en la foto REAL del usuario eso no pasa
    (la tilde manuscrita es más marcada), pero el test debe aislar la lógica
    nueva, no la confusión del CNN con una fuente.
    """
    from core.inkcore.ai.char_cnn import char_to_label
    from core.inkcore.template_extract import extract_pdf_pages
    from core.inkcore.template_sheet import TEMPLATE_PRESETS
    lay = TEMPLATE_PRESETS["acentuadas_x12"]
    img = _fill_sheet(lay, range(lay.cols * lay.rows))
    p = tmp_path / "acentos.png"
    img.save(p)
    meta = extract_pdf_pages([str(p)], clf=None, char_to_label=char_to_label)[0]
    assert meta["preset"] == "acentuadas_x12", meta["preset"]
    assert meta["suspect"] is False
    assert len(meta["results"]) >= 50


def test_presets_geometrias_conocidas():
    """E3: el registro reproduce las geometrías medidas contra los PDF reales."""
    from core.inkcore.template_sheet import TEMPLATE_PRESETS
    esperado = {
        "minusculas_x1": (4, 7), "acentuadas_x12": (6, 12),
        "digitos_signos_x8": (9, 16), "comunes_ltcdmp_x12": (6, 16),
    }
    for name, (cols, rows) in esperado.items():
        lay = TEMPLATE_PRESETS[name]
        assert (lay.cols, lay.rows) == (cols, rows), f"{name}: {lay.cols}x{lay.rows}"


def test_rotation_candidates_por_aspecto():
    """E3: retrato → {0,180}; apaisada → {90,270}."""
    import numpy as np

    from core.inkcore.template_extract import _rotation_candidates
    assert _rotation_candidates(np.zeros((1754, 1240), np.uint8)) == (0, 180)
    assert _rotation_candidates(np.zeros((1240, 1754), np.uint8)) == (90, 270)


def test_score_layout_cheap_premia_grilla_alineada(tmp_path):
    """E3: el scoring estructural da más casillas sanas a la grilla correcta."""
    import numpy as np

    from core.inkcore.template_extract import score_layout_cheap
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    img = _fill_sheet(lay, range(len(lay.letters)))
    gray = np.asarray(img.convert("L"))
    sc = score_layout_cheap(gray, lay)
    assert sc["n_inked"] > 0 and sc["n_healthy"] > 0
    assert sc["score"] > 0.5, f"grilla correcta debería puntuar alto: {sc}"


def test_extract_pdf_pages_identifica_minusculas(tmp_path):
    """E3: una hoja de minúsculas se identifica como minusculas_x1, no suspect.

    Sin fiduciales (hoja sintética rellena con fuente), el orquestador debe
    elegir el preset de minúsculas por agreement CNN y extraer las letras. Si el
    CNN no está disponible en el entorno, el agreement es None: igual no debe
    romper (se acepta cualquiera de los dos desenlaces documentados).
    """
    from core.inkcore.template_extract import _load_template_cnn, extract_pdf_pages
    from core.inkcore.template_sheet import TemplateLayout
    lay = TemplateLayout()
    img = _fill_sheet(lay, range(len(lay.letters)))
    p = tmp_path / "minus.png"
    img.save(p)
    clf, c2l = _load_template_cnn()
    metas = extract_pdf_pages([str(p)], clf=clf, char_to_label=c2l)
    assert len(metas) == 1
    meta = metas[0]
    assert set(meta) >= {"results", "preset", "rotation", "suspect", "reason"}
    if clf is not None:
        # Con CNN, identifica minúsculas y no la marca suspect.
        assert meta["preset"] == "minusculas_x1", meta["preset"]
        assert meta["suspect"] is False
        chars = [c for c, _g, _s in meta["results"]]
        assert len(chars) >= 20, f"pocas casillas: {chars}"


def _glyph_from_char(ch, size=64):
    """Glifo RGBA con una letra de fuente (alpha = tinta), para el gate sintético."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 48)
    except Exception:
        font = ImageFont.load_default()
    draw.text((12, 4), ch, fill=(255, 255, 255, 255), font=font)
    return img


class _ScriptedCNN:
    """CNN falso: score(mask, ch) devuelve un valor fijo por carácter."""

    available = True

    def __init__(self, per_char):
        self._per_char = per_char

    def score(self, _mask, ch):
        return self._per_char.get(ch)


def test_gate_frena_pagina_con_etiquetas_cruzadas():
    """E2: una página con acuerdo CNN ínfimo (mapeo cruzado) se marca suspect."""
    from core.inkcore.ai.char_cnn import char_to_label
    from core.inkcore.template_extract import assess_page_agreement
    results = [(c, _glyph_from_char(c), 0.5) for c in "abcdefg"]
    # CNN ve casi cero probabilidad de la letra esperada (números disfrazados).
    clf = _ScriptedCNN({c: 0.03 for c in "abcdefg"})
    agreement, suspect, reason = assess_page_agreement(results, clf, char_to_label)
    assert suspect is True
    assert agreement is not None and agreement < 0.12
    assert "no confiable" in reason


def test_gate_deja_pasar_pagina_bien_mapeada():
    """E2: acuerdo alto → no suspect."""
    from core.inkcore.ai.char_cnn import char_to_label
    from core.inkcore.template_extract import assess_page_agreement
    results = [(c, _glyph_from_char(c), 0.8) for c in "abcdefg"]
    clf = _ScriptedCNN({c: 0.55 for c in "abcdefg"})
    agreement, suspect, reason = assess_page_agreement(results, clf, char_to_label)
    assert suspect is False and reason == ""
    assert agreement is not None and agreement >= 0.12


def test_gate_sin_cnn_no_bloquea_pero_avisa():
    """E2: sin CNN no se bloquea al usuario, pero el reason lo deja explícito."""
    from core.inkcore.ai.char_cnn import char_to_label
    from core.inkcore.template_extract import assess_page_agreement
    results = [(c, _glyph_from_char(c), 0.5) for c in "abc"]
    agreement, suspect, reason = assess_page_agreement(results, None, char_to_label)
    assert agreement is None and suspect is False
    assert "sin validación CNN" in reason


def test_gate_pagina_de_digitos_no_es_suspect_por_cobertura():
    """E2: una página de SOLO dígitos (sin casillas a-z) no se marca suspect.

    El CNN EMNIST solo cubre a-z; sin casillas puntuables la decisión la toma la
    señal estructural del preset (E3), no este gate. Marcarla suspect sería un
    falso positivo que bloquearía una captura legítima de números.
    """
    from core.inkcore.ai.char_cnn import char_to_label
    from core.inkcore.template_extract import assess_page_agreement
    results = [(c, _glyph_from_char(c), 0.5) for c in "0123456789"]
    clf = _ScriptedCNN({})   # score() → None para no-a-z
    agreement, suspect, reason = assess_page_agreement(results, clf, char_to_label)
    assert agreement is None and suspect is False
    assert "sin casillas a-z" in reason


class _FakeCNN:
    """Clasificador falso disponible — el scorer real se monkeypatchea aparte."""
    available = True


def _patch_cnn_scores(monkeypatch, scores_por_angulo):
    """Hace que el fallback CNN use scores fijos por ángulo (0,90,180,270)."""
    from core.inkcore import template_extract as te
    monkeypatch.setattr(
        "core.inkcore.ai.char_cnn.EMNISTCharClassifier", _FakeCNN, raising=False,
    )
    seq = iter([scores_por_angulo[a] for a in (0, 90, 180, 270)])
    monkeypatch.setattr(te, "_rotation_cnn_score", lambda *a, **k: next(seq))


def test_rotacion_por_cnn_elige_ganador_claro(monkeypatch):
    """Sin fiduciales, el fallback CNN elige el ángulo con acuerdo dominante."""
    import numpy as np

    from core.inkcore.template_extract import _detect_rotation_by_cnn
    _patch_cnn_scores(monkeypatch, {0: 0.05, 90: 0.40, 180: 0.08, 270: 0.04})
    assert _detect_rotation_by_cnn(np.zeros((10, 10), np.uint8), None) == 90


def test_rotacion_por_cnn_ambiguo_devuelve_none(monkeypatch):
    """Sin margen claro (todos parecidos) no rota: devuelve None → caller default 0."""
    import numpy as np

    from core.inkcore.template_extract import _detect_rotation_by_cnn
    _patch_cnn_scores(monkeypatch, {0: 0.20, 90: 0.20, 180: 0.19, 270: 0.18})
    assert _detect_rotation_by_cnn(np.zeros((10, 10), np.uint8), None) is None


def test_rotacion_por_cnn_margen_insuficiente_devuelve_none(monkeypatch):
    """El mejor supera el piso pero no duplica al segundo → None (no arriesga)."""
    import numpy as np

    from core.inkcore.template_extract import _detect_rotation_by_cnn
    _patch_cnn_scores(monkeypatch, {0: 0.12, 90: 0.10, 180: 0.05, 270: 0.04})
    assert _detect_rotation_by_cnn(np.zeros((10, 10), np.uint8), None) is None

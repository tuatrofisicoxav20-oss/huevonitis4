"""Extractor de glifos desde la plantilla por grilla (Fase plantilla).

Dado una foto de la plantilla rellena (`template_sheet`), recupera un glifo por
casilla SIN segmentar: la casilla↔letra es fija. Pasos:

  1. Rectificar: detectar los 4 marcadores de esquina y aplicar una transformación
     de perspectiva al tamaño canónico (TemplateLayout). Así cada casilla cae en
     coordenadas conocidas, aunque la foto venga torcida o en ángulo.
  2. Por cada casilla, recortar el área de escritura (sin borde ni rótulo),
     binarizar la tinta, quitar restos del borde/rótulo (componentes que tocan el
     marco) y autocrop.
  3. Convertir a glifo RGBA en el formato del banco (`to_rgba_smooth`) y evaluar
     calidad. Devuelve (letra, imagen, calidad) por casilla con tinta suficiente.

No depende de la alineación posicional del extractor de renglón: por eso no hay
recortes a la mitad ni etiquetas corridas.
"""
from __future__ import annotations

import contextlib
import logging

from core.inkcore.template_sheet import TemplateLayout

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def _detect_fiducials(gray: np.ndarray, layout: TemplateLayout) -> np.ndarray | None:
    """Devuelve los centros de los 4 marcadores (TL,TR,BL,BR) o None.

    Busca cuadrados negros sólidos razonablemente grandes y los asigna a la
    esquina más cercana de la imagen.
    """
    h, w = gray.shape[:2]
    _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = (w * h) * 0.0004        # marcadores son chicos pero no motas
    max_area = (w * h) * 0.02
    cands: list[tuple[float, float, float]] = []  # (cx, cy, area)
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        ar = bw / max(1, bh)
        if not (0.6 <= ar <= 1.6):     # cuadrados
            continue
        # Densidad alta (sólido), no un anillo
        if area < 0.55 * bw * bh:
            continue
        cands.append((x + bw / 2.0, y + bh / 2.0, area))
    if len(cands) < 4:
        return None

    corners = [(0, 0), (w, 0), (0, h), (w, h)]  # TL, TR, BL, BR
    chosen: list[tuple[float, float]] = []
    used: set[int] = set()
    for (corner_x, corner_y) in corners:
        best_i, best_d = -1, None
        for i, (cx, cy, _a) in enumerate(cands):
            if i in used:
                continue
            d = (cx - corner_x) ** 2 + (cy - corner_y) ** 2
            if best_d is None or d < best_d:
                best_d, best_i = d, i
        if best_i < 0:
            return None
        used.add(best_i)
        chosen.append((cands[best_i][0], cands[best_i][1]))
    return np.array(chosen, dtype=np.float32)


def _rotate_cw(img: np.ndarray, angle: int) -> np.ndarray:
    """Rota `img` en sentido horario por `angle` ∈ {0,90,180,270} grados."""
    angle %= 360
    if angle == 0:
        return img
    if angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"_rotate_cw: ángulo no múltiplo de 90: {angle}")


def _title_band_signal(canon: np.ndarray, layout: TemplateLayout) -> float:
    """Mide cuánta tinta hay en la franja del título (arriba) vs el pie (abajo).

    En la plantilla canónica el título está pegado al margen superior y el pie
    queda vacío; las franjas viven FUERA de la grilla, así que la única tinta
    esperable es el título. Si la hoja está al revés (180° respecto a lo
    correcto) la rectificación deja el título abajo y esta diferencia se vuelve
    negativa. Sirve para desempatar 0 vs 180 y 90 vs 270 (los marcadores de
    esquina son simétricos y no distinguen esos casos por sí solos).
    """
    m = layout.margin
    top = canon[m:layout.grid_y0, layout.grid_x0:layout.grid_x1]
    bot_y0 = layout.grid_y1
    bot_y1 = min(layout.height, layout.height - m + (layout.grid_y0 - m))
    bot = canon[bot_y0:bot_y1, layout.grid_x0:layout.grid_x1]
    if top.size == 0 or bot.size == 0:
        return 0.0
    top_dark = float((top < 128).mean())
    bot_dark = float((bot < 128).mean())
    return top_dark - bot_dark


def detect_template_rotation(image_path: str, layout: TemplateLayout | None = None) -> int:
    """Ángulo horario (0/90/180/270) a aplicar para enderezar la plantilla.

    El escáner suele rotar 90° las hojas apaisadas; aquí se prueba cada rotación
    candidata y se elige la que (a) detecta los 4 marcadores de esquina, (b) deja
    la hoja vertical (alto>ancho, la forma canónica de TemplateLayout) y (c)
    coloca el título arriba (ver `_title_band_signal`, que desempata 90 vs 270 y
    0 vs 180).

    Si NINGUNA rotación detecta los marcadores (plantilla sin fiduciales: una
    grilla pelada, foto recortada al ras…) cae a un fallback por CNN: extrae las
    casillas en cada rotación y se queda con la que maximiza el acuerdo del
    clasificador con la letra esperada de cada casilla (la grilla canónica mapea
    casilla→letra por posición). Si el CNN no está disponible o el resultado es
    ambiguo, devuelve 0 con un warning y el usuario revisa en la grilla.
    """
    if not (_CV2_OK and _PIL_OK):
        logger.warning("detect_template_rotation: faltan cv2/PIL — sin rotación")
        return 0
    from pathlib import Path
    if not Path(image_path).exists():
        logger.warning("detect_template_rotation: no existe %s", image_path)
        return 0
    bgr = cv2.imread(image_path)
    if bgr is None:
        logger.warning("detect_template_rotation: cv2 no pudo leer %s", image_path)
        return 0
    lay = layout or TemplateLayout()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    best_angle = 0
    best_score = None
    any_fiducials = False
    for angle in (0, 90, 180, 270):
        rot = _rotate_cw(gray, angle)
        h, w = rot.shape[:2]
        fid = _detect_fiducials(rot, lay)
        has_fid = fid is not None
        any_fiducials = any_fiducials or has_fid
        portrait = h > w
        # La verticalidad domina (peso grande); entre verticales con marcadores,
        # el título arriba desempata. Sin marcadores, score muy bajo.
        score = (1000.0 if has_fid else 0.0) + (100.0 if portrait else 0.0)
        if has_fid:
            canon = _rectify(rot, lay)
            score += _title_band_signal(canon, lay)
        if best_score is None or score > best_score:
            best_score, best_angle = score, angle

    if not any_fiducials:
        cnn_angle = _detect_rotation_by_cnn(gray, lay)
        if cnn_angle is not None:
            logger.info(
                "detect_template_rotation: sin marcadores — CNN eligió %d° en %s",
                cnn_angle, image_path,
            )
            return cnn_angle
        logger.warning(
            "detect_template_rotation: sin marcadores y CNN no concluyente en %s — default 0°",
            image_path,
        )
        return 0
    logger.info("detect_template_rotation: %s → rotar %d° horario", image_path, best_angle)
    return best_angle


def _rotation_cnn_score(gray: np.ndarray, layout: TemplateLayout, clf) -> float:
    """Acuerdo medio del CNN entre cada casilla y su letra esperada (0..1).

    Rectifica (sin fiduciales cae a resize), recorta cada casilla rotulada y la
    puntúa contra el carácter que le corresponde por posición. Solo cuenta a-z
    (el CNN no cubre ñ ni mayúsculas/dígitos). Una orientación correcta hace que
    las letras caigan en su casilla → acuerdo alto; una rotada → acuerdo casi
    nulo. Devuelve 0.0 si no hay casillas puntuables.
    """
    from core.inkcore.ai.char_cnn import char_to_label
    canon = _rectify(gray, layout)
    n_labeled = min(layout.n_cells, len(layout.letters) * layout.repeats)
    scores: list[float] = []
    for i in range(n_labeled):
        ch = layout.cell_letter(i)
        if ch is None or char_to_label(ch) is None:
            continue
        wx, wy, ww, wh = layout.writing_rect(i)
        mask = _clean_cell(canon[wy:wy + wh, wx:wx + ww])
        if mask is None:
            continue
        try:
            s = clf.score(mask, ch)
        except Exception:
            s = None
        if s is not None:
            scores.append(float(s))
    return sum(scores) / len(scores) if scores else 0.0


def _detect_rotation_by_cnn(gray: np.ndarray, layout: TemplateLayout) -> int | None:
    """Elige la rotación (0/90/180/270) por acuerdo del CNN, o None si ambiguo.

    Fallback cuando no hay fiduciales. Requiere el clasificador EMNIST; si no
    está disponible devuelve None (el caller hace default 0). Solo devuelve un
    ángulo si gana con margen claro, para no rotar de más una hoja ya derecha
    cuando la señal es débil.
    """
    try:
        from core.inkcore.ai.char_cnn import EMNISTCharClassifier
        clf = EMNISTCharClassifier()
    except Exception as exc:
        logger.info("_detect_rotation_by_cnn: CNN no disponible (%s)", exc)
        return None
    if not getattr(clf, "available", False):
        return None
    scores = {a: _rotation_cnn_score(_rotate_cw(gray, a), layout, clf) for a in (0, 90, 180, 270)}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_a, best_s = ranked[0]
    second_s = ranked[1][1]
    logger.info("_detect_rotation_by_cnn: scores=%s", {a: round(s, 3) for a, s in scores.items()})
    # Margen claro: el mejor debe superar un piso mínimo y duplicar al segundo.
    if best_s >= 0.10 and best_s >= 1.8 * max(second_s, 1e-6):
        return best_a
    return None


def _rectify(gray: np.ndarray, layout: TemplateLayout) -> np.ndarray:
    """Rectifica la imagen al tamaño canónico usando los marcadores.

    Si no encuentra los 4 marcadores, hace fallback a un simple resize (la foto
    ya venía bastante derecha o es la plantilla canónica).
    """
    src = _detect_fiducials(gray, layout)
    dst = np.array(layout.fiducial_centers(), dtype=np.float32)
    if src is None:
        logger.info("template: marcadores no detectados — fallback a resize")
        return cv2.resize(gray, (layout.width, layout.height))
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(gray, M, (layout.width, layout.height),
                               flags=cv2.INTER_LINEAR, borderValue=255)


def _clean_cell(cell_gray: np.ndarray) -> np.ndarray | None:
    """Binariza una casilla y deja sólo la tinta central (sin borde/rótulo).

    Devuelve una máscara uint8 (255=tinta) ya recortada al bbox de la letra, o
    None si la casilla está prácticamente vacía.
    """
    if cell_gray.size == 0:
        return None
    # Binarización adaptativa: robusta a iluminación despareja en la foto.
    blur = cv2.GaussianBlur(cell_gray, (3, 3), 0)
    thr = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12,
    )
    # Quitar componentes que tocan el borde de la casilla (restos del marco/rótulo).
    h, w = thr.shape[:2]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(thr, connectivity=8)
    keep = np.zeros_like(thr)
    total_ink = 0
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < max(6, (h * w) * 0.0008):       # motas
            continue
        touches = (x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1)
        # Un trazo que toca el borde por poco puede ser parte de la letra; sólo
        # descartamos los componentes alargados pegados al marco (líneas del box).
        if touches and (bw > 0.85 * w or bh > 0.85 * h):
            continue
        keep[labels == i] = 255
        total_ink += int(area)
    if total_ink < (h * w) * 0.004:               # casilla vacía
        return None
    # Autocrop al bbox de la tinta con un pequeño padding.
    ys, xs = np.where(keep > 0)
    if len(xs) == 0:
        return None
    pad = 6
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + 1 + pad)
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + 1 + pad)
    return keep[y0:y1, x0:x1]


def _estimate_skew(gray: np.ndarray) -> float:
    """Ángulo (grados) del skew leve de la foto, por líneas casi-horizontales.

    Las fotos de plantilla suelen venir rotadas 0.3-1° (papel torcido). Ese tilt
    rompe la morfología de líneas rectas y desalinea las columnas, así que lo
    corregimos antes de detectar la grilla. Usa Hough sobre los bordes y toma la
    mediana del ángulo de los segmentos casi horizontales.
    """
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 720, threshold=120,
        minLineLength=gray.shape[1] // 4, maxLineGap=20,
    )
    if lines is None:
        return 0.0
    angs = []
    for x1, y1, x2, y2 in lines[:, 0]:
        a = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if abs(a) < 20:                 # casi horizontal
            angs.append(a)
    return float(np.median(angs)) if angs else 0.0


def _deskew(gray: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.05:
        return gray
    h, w = gray.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)


def _grid_content_bbox(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    """bbox de todo el contenido (tinta + líneas de grilla) por proyección.

    Robusto a líneas tenues: no depende de detectarlas, sólo del extent del
    contenido oscuro. Usa percentiles (no min/max) para ignorar motas de borde
    del escáner. Devuelve (x0, y0, x1, y1) o None si no hay contenido.
    """
    binv = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (3, 3), 0), 255,
        cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 41, 10,
    )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binv, connectivity=8)
    clean = np.zeros_like(binv)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= 25:    # descartar motas
            clean[labels == i] = 255
    ys, xs = np.where(clean > 0)
    if len(xs) == 0:
        return None
    x0, x1 = np.percentile(xs, [0.3, 99.7])
    y0, y1 = np.percentile(ys, [0.3, 99.7])
    return int(x0), int(y0), int(x1), int(y1)


def _strip_edge_lines(thr: np.ndarray, band: float = 0.20, frac: float = 0.45) -> np.ndarray:
    """Borra bandas de línea (separadores de grilla) en el margen de la celda.

    Tras el inset puede quedar el separador de fila/columna pegado a un borde de
    la celda. Si una fila del 20% superior/inferior (o columna izq/der) está
    rellena >45%, es una línea recta (no la letra, que vive centrada) → se borra.
    Robusto a tilt leve, donde la morfología recta no alcanza.
    """
    h, w = thr.shape[:2]
    out = thr.copy()
    bh, bw = int(band * h), int(band * w)
    rowfrac = (thr > 0).sum(axis=1) / max(1, w)
    colfrac = (thr > 0).sum(axis=0) / max(1, h)
    for y in list(range(0, bh)) + list(range(h - bh, h)):
        if rowfrac[y] > frac:
            out[y, :] = 0
    for x in list(range(0, bw)) + list(range(w - bw, w)):
        if colfrac[x] > frac:
            out[:, x] = 0
    return out


def _clean_cell_grid(cell: np.ndarray) -> np.ndarray | None:
    """Como `_clean_cell` pero quita líneas de grilla (morfología + bandas de borde).

    Pensado para la ruta SIN fiduciales, donde la celda se recorta de la foto
    cruda y puede arrastrar trozos de los separadores de la grilla.
    """
    if cell.size == 0:
        return None
    thr = cv2.adaptiveThreshold(
        cv2.GaussianBlur(cell, (3, 3), 0), 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12,
    )
    h, w = thr.shape[:2]
    # Líneas largas rectas (≥55% del lado): la letra no tiene runs así de largos.
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(8, int(0.55 * w)), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(8, int(0.55 * h))))
    lines = cv2.bitwise_or(
        cv2.morphologyEx(thr, cv2.MORPH_OPEN, hk),
        cv2.morphologyEx(thr, cv2.MORPH_OPEN, vk),
    )
    lines = cv2.dilate(lines, np.ones((3, 3), np.uint8))
    thr = cv2.subtract(thr, lines)
    thr = _strip_edge_lines(thr)
    # Recerrar pequeños gaps que dejó el borrado de líneas dentro de la letra.
    thr = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(thr, connectivity=8)
    keep = np.zeros_like(thr)
    ink = 0
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < max(6, h * w * 0.0008):
            continue
        touches = (x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1)
        if touches and (bw > 0.85 * w or bh > 0.85 * h):
            continue
        keep[labels == i] = 255
        ink += int(area)
    if ink < h * w * 0.004:
        return None
    ys, xs = np.where(keep > 0)
    if len(xs) == 0:
        return None
    pad = 6
    return keep[max(0, ys.min() - pad):ys.max() + 1 + pad,
                max(0, xs.min() - pad):xs.max() + 1 + pad]


def _sizable_components(mask: np.ndarray) -> int:
    """Cuenta componentes conexos no triviales de la máscara.

    Una letra manuscrita real tiene pocas piezas (1-5: el trazo, el punto de la
    i/j, la tilde de la ñ, los cruces de x/k). El TÍTULO/instrucciones de la
    plantilla ("Plantilla de letra", "Huevonitis"…), si la foto lo captó arriba
    de la grilla y cayó en una casilla, aparece como MUCHAS piezas (las letras de
    las palabras) → 10-30 componentes. Sirve para descartar esas casillas-texto
    sin tener que detectar la banda del título geométricamente.
    """
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    thr = max(10, mask.size * 0.001)
    return sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= thr)


def _extract_grid(gray, lay, clf, char_to_label):
    """Extracción para plantillas SIN fiduciales: detecta la grilla en la foto.

    En vez de asumir la geometría canónica (que sólo vale si rectificamos por los
    4 marcadores), deskewa la foto, halla el bbox del contenido y divide en
    lay.cols × lay.rows celdas uniformes, limpiando líneas de grilla por celda.
    Esto evita lo que rompía la ruta vieja (un simple resize desalineaba las
    casillas → recortes sobre líneas y letras partidas). Mismo formato de salida
    que extract_from_template: lista de (letra, glifo_RGBA, score).
    """
    from core.inkcore.extractor_glyph_ops import assess_quality, to_rgba_smooth

    ang = _estimate_skew(gray)
    gray = _deskew(gray, ang)
    # Extrae la grilla TAL CUAL en la orientación recibida (sin auto-rotar por
    # aspecto: eso arreglaba el alto/ancho pero no el arriba/abajo, y dejaba
    # páginas apaisadas dadas vuelta → letras en la casilla equivocada). La
    # orientación correcta la elige extract_from_template_auto probando las 4
    # rotaciones y quedándose con la de mayor acuerdo CNN (señal limpia sobre la
    # extracción de grilla, no sobre la canónica rota).
    bb = _grid_content_bbox(gray)
    if bb is None:
        logger.warning("_extract_grid: sin contenido detectable")
        return []
    gx0, gy0, gx1, gy1 = bb
    n_cols, n_rows = lay.cols, lay.rows
    xs = np.linspace(gx0, gx1, n_cols + 1)
    ys = np.linspace(gy0, gy1, n_rows + 1)
    inset = 0.13
    logger.info("_extract_grid: skew=%.2f° grilla %dx%d bbox=%s", ang, n_cols, n_rows, bb)

    results: list[tuple[str, Image.Image, float]] = []
    for r in range(n_rows):
        for c in range(n_cols):
            i = r * n_cols + c
            ch = lay.cell_letter(i)
            if ch is None:
                continue
            x0, x1 = xs[c], xs[c + 1]
            y0, y1 = ys[r], ys[r + 1]
            cw, chh = x1 - x0, y1 - y0
            ix0, ix1 = int(x0 + inset * cw), int(x1 - inset * cw)
            iy0, iy1 = int(y0 + inset * chh), int(y1 - inset * chh)
            mask = _clean_cell_grid(gray[iy0:iy1, ix0:ix1])
            if mask is None:
                continue
            # Descartar casillas-texto: si la foto captó el título/instrucciones
            # de la plantilla arriba de la grilla, el bbox de contenido lo incluye
            # y la fila 1 cae sobre ese texto. Una línea de título da MUCHAS piezas
            # conexas; una letra real, pocas (≤5). Umbral 8 separa limpio (validado:
            # ninguna letra manuscrita del banco supera 8).
            ncomp = _sizable_components(mask)
            if ncomp >= 8:
                logger.info(
                    "_extract_grid: casilla '%s' descartada (texto/título, %d componentes)",
                    ch, ncomp,
                )
                continue
            glyph = to_rgba_smooth(mask)
            try:
                q = assess_quality(glyph)
                score = float(q.get("quality_score", q.get("score", 0.5)))
            except Exception:
                score = 0.5
            if clf is not None and char_to_label is not None and char_to_label(ch) is not None:
                try:
                    cnn = clf.score(mask, ch)
                    if cnn is not None and cnn < 0.12:
                        score = min(score, 0.45)
                except Exception:
                    pass
            results.append((ch, glyph, score))
    logger.info("_extract_grid: %d casillas con tinta", len(results))
    return results


def extract_from_template(
    image_path: str, layout: TemplateLayout | None = None, *, pre_rotate: int = 0,
) -> list[tuple[str, Image.Image, float]]:
    """Extrae un glifo por casilla rellena. Lista de (letra, glifo_RGBA, calidad).

    Sólo devuelve casillas con tinta suficiente (las vacías se omiten). No hay
    segmentación: cada casilla se mapea a su letra por posición fija en la grilla.

    `pre_rotate` (0/90/180/270, horario) rota la imagen ANTES de rectificar: lo
    usa el flujo de PDF multipágina para enderezar hojas que el escáner giró 90°
    (ver `extract_from_template_auto`). Default 0 = sin cambios (los tests
    existentes lo invocan sin este argumento).
    """
    if not (_CV2_OK and _PIL_OK):
        logger.warning("extract_from_template: faltan cv2/PIL")
        return []
    from pathlib import Path

    from core.inkcore.extractor_glyph_ops import assess_quality, to_rgba_smooth
    if not Path(image_path).exists():
        logger.warning("extract_from_template: no existe %s", image_path)
        return []
    bgr = cv2.imread(image_path)
    if bgr is None:
        logger.warning("extract_from_template: cv2 no pudo leer %s", image_path)
        return []
    lay = layout or TemplateLayout()
    if pre_rotate % 360:
        bgr = _rotate_cw(bgr, pre_rotate)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Clasificador opcional: la casilla↔letra ya es correcta por construcción,
    # pero el CNN marca como dudosa la casilla donde se escribió OTRA letra (error
    # humano) o quedó ilegible → su score baja y la UI la resalta para revisar.
    clf = None
    char_to_label = None
    try:
        import config as _cfg
        if getattr(_cfg, "USE_CNN_ALIGN", False):
            from core.inkcore.ai.char_cnn import EMNISTCharClassifier, char_to_label
            _c = EMNISTCharClassifier()
            if _c.available:
                clf = _c
    except Exception as _exc:
        logger.info("extract_from_template: CNN no disponible (%s)", _exc)

    # Bifurcación CON / SIN fiduciales. Con marcadores: rectificación por
    # perspectiva exacta y geometría canónica (writing_rect). Sin marcadores
    # (grilla pelada, foto de celular): la canónica fallaba porque _rectify caía
    # a un resize que NO alinea las casillas → recortes sobre líneas y letras
    # partidas. En ese caso detectamos la grilla real en la foto (_extract_grid).
    if _detect_fiducials(gray, lay) is None:
        return _extract_grid(gray, lay, clf, char_to_label)
    canon = _rectify(gray, lay)

    results: list[tuple[str, Image.Image, float]] = []
    n_labeled = min(lay.n_cells, len(lay.letters) * lay.repeats)
    for i in range(n_labeled):
        ch = lay.cell_letter(i)
        if ch is None:
            continue
        wx, wy, ww, wh = lay.writing_rect(i)
        cell = canon[wy:wy + wh, wx:wx + ww]
        mask = _clean_cell(cell)
        if mask is None:
            continue
        glyph = to_rgba_smooth(mask)
        try:
            q = assess_quality(glyph)
            score = float(q.get("quality_score", q.get("score", 0.5)))
        except Exception:
            score = 0.5
        # Validación por CNN: si no reconoce la casilla como su letra (ni de
        # lejos), marcarla dudosa bajando el score (solo a-z; la ñ no aplica).
        if clf is not None and char_to_label is not None and char_to_label(ch) is not None:
            try:
                cnn = clf.score(mask, ch)
                if cnn is not None and cnn < 0.12:
                    score = min(score, 0.45)
            except Exception as _exc:
                logger.debug("validación CNN omitida para '%s': %s", ch, _exc)
        results.append((ch, glyph, score))
    logger.info("extract_from_template: %d/%d casillas con tinta (repeats=%d)",
                len(results), n_labeled, lay.repeats)
    return results


def _has_fiducials(image_path: str, lay: TemplateLayout) -> bool:
    """True si alguna de las 4 rotaciones detecta los 4 marcadores de esquina."""
    if not (_CV2_OK and _PIL_OK):
        return False
    bgr = cv2.imread(image_path)
    if bgr is None:
        return False
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    for angle in (0, 90, 180, 270):
        if _detect_fiducials(_rotate_cw(gray, angle), lay) is not None:
            return True
    return False


def _grid_cnn_agreement(results, clf, char_to_label) -> float:
    """Acuerdo medio del CNN entre cada casilla a-z y su letra esperada.

    Es la señal para elegir orientación sin fiduciales: la rotación correcta hace
    que cada letra caiga en su casilla → P(letra esperada) alto (~0.4-0.6); una
    rotación equivocada deja letras cruzadas → ~0.02. Diferencia de 10-15×, así
    que discrimina con claridad. Solo cuenta a-z (la ñ no la cubre el CNN).
    """
    scores = []
    for ch, glyph, _s in results:
        if char_to_label(ch) is None:
            continue
        try:
            a = np.asarray(glyph.convert("RGBA"))[:, :, 3]
            mask = (a > 30).astype(np.uint8) * 255
            v = clf.score(mask, ch)
        except Exception:
            v = None
        if v is not None:
            scores.append(v)
    return sum(scores) / len(scores) if scores else 0.0


def extract_from_template_auto(
    image_path: str, layout: TemplateLayout | None = None,
) -> list[tuple[str, Image.Image, float]]:
    """Como `extract_from_template`, pero detecta y corrige la rotación primero.

    CON fiduciales: usa `detect_template_rotation` (los marcadores y el título
    bastan para orientar) y extrae con ese `pre_rotate`.

    SIN fiduciales (grilla pelada, foto de celular): la rotación por CNN sobre la
    extracción canónica NO es fiable (la canónica está rota sin marcadores), y el
    escáner gira algunas hojas 90°. Por eso acá se prueban las 4 rotaciones con la
    extracción de GRILLA y se elige la de mayor acuerdo CNN casilla↔letra. Esto
    arregla las hojas apaisadas que antes quedaban mal mapeadas (la 'x' caía en la
    casilla de 'd', la 'w' en la de 'o', etc.). Si no hay CNN, cae a 0°.
    """
    lay = layout or TemplateLayout()
    if _has_fiducials(image_path, lay):
        angle = detect_template_rotation(image_path, lay)
        return extract_from_template(image_path, lay, pre_rotate=angle)

    # Sin fiduciales: búsqueda de orientación por acuerdo CNN sobre la grilla.
    clf = None
    char_to_label = None
    try:
        from core.inkcore.ai.char_cnn import EMNISTCharClassifier, char_to_label
        _c = EMNISTCharClassifier()
        if _c.available:
            clf = _c
    except Exception as exc:
        logger.info("extract_from_template_auto: CNN no disponible (%s)", exc)

    if clf is None:
        return extract_from_template(image_path, lay, pre_rotate=0)

    best_res, best_score, best_rot = [], -1.0, 0
    for rot in (0, 90, 180, 270):
        res = extract_from_template(image_path, lay, pre_rotate=rot)
        score = _grid_cnn_agreement(res, clf, char_to_label)
        if score > best_score:
            best_score, best_res, best_rot = score, res, rot
    logger.info(
        "extract_from_template_auto: sin fiduciales — rot %d° (acuerdo CNN=%.3f)",
        best_rot, best_score,
    )
    return best_res


def _quality_override_from_template(glyph, score, classify_tier) -> dict:
    """Arma el dict {score, tier, ink_coverage} para bank.add_glyph.

    Reutiliza el score de la plantilla (con la rebaja del CNN si la hubo) y mide
    ink_coverage barato del canal alpha del glifo (sin re-evaluar calidad). El
    tier sale de classify_tier con los umbrales del banco. Si algo falla, None
    para que add_glyph caiga a su assess_glyph habitual.
    """
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    s = max(0.0, min(1.0, s))
    ink_cov = 0.5
    try:
        alpha = np.asarray(glyph.getchannel("A"))
        if alpha.size:
            ink_cov = round(float((alpha > 64).mean()), 3)
    except Exception:
        pass
    return {"score": round(s, 3), "tier": classify_tier(s), "ink_coverage": ink_cov}


def save_template_glyphs_to_bank(results, bank, temp_dir=None) -> dict:
    """Guarda los glifos extraídos de la plantilla en el banco dado.

    Escribe cada glifo a un PNG temporal y lo manda a `bank.add_glyph` (que copia
    al banco y persiste). Devuelve {saved, dupes, total}. Pensado para llamarse
    desde la UI con el bank vivo de la app (NO desde un script suelto sobre el
    banco real con la app abierta — colisiona el manifest).

    Se pasa skip_dedup=True a add_glyph: las casillas de la plantilla con
    repeats>1 son intencionalmente la MISMA letra repetida para capturar la
    variación natural de la escritura, y vienen de posiciones distintas de la
    grilla. El dedup perceptual por hamming las rechazaría como duplicados,
    anulando el propósito de repeats y manteniendo el banco artificialmente
    chico — justo esa variación es la que mejora el render. El dedup sigue activo
    en el flujo de imagen suelta (extractor_tab), donde el solapamiento de cajas
    sí puede extraer dos veces el mismo glifo. Por eso saved == total salvo
    errores de I/O, y dupes queda en 0.

    También se pasa quality_override para conservar el score que ya calculó
    extract_from_template (incluida la rebaja a 0.45 del CNN en casillas dudosas)
    en vez de que add_glyph lo recalcule desde cero: así get_best_glyph elige las
    muestras buenas de otras hojas y no se pierde la bandera de baja confianza.
    """
    import tempfile
    from pathlib import Path

    from core.inkcore.quality import classify_tier
    if temp_dir is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="tpl_glyphs_"))
    else:
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
    saved = dupes = 0
    for i, (ch, glyph, q) in enumerate(results):
        safe = ch if ch.isalnum() else f"u{ord(ch)}"
        p = temp_dir / f"{safe}_{i:03d}.png"
        try:
            glyph.save(p)
        except Exception as exc:
            logger.warning("save_template: no se pudo escribir %s: %s", p, exc)
            continue
        # Conservar el score ya calculado por extract_from_template (incluida la
        # rebaja a 0.45 que el CNN aplica a las casillas dudosas) en vez de dejar
        # que add_glyph lo recalcule desde cero: así get_best_glyph prefiere las
        # muestras buenas de otras hojas y la bandera de baja confianza no se
        # pierde. ink_coverage se mide barato del alpha del glifo; el tier sale
        # del score con los mismos umbrales del banco.
        override = _quality_override_from_template(glyph, q, classify_tier)
        entry = bank.add_glyph(ch, str(p), skip_dedup=True, quality_override=override)
        if entry is None:
            dupes += 1
        else:
            saved += 1
    for f in temp_dir.glob("*.png"):
        with contextlib.suppress(OSError):
            f.unlink()
    logger.info("save_template_glyphs_to_bank: saved=%d dupes=%d total=%d",
                saved, dupes, len(results))
    return {"saved": saved, "dupes": dupes, "total": len(results)}

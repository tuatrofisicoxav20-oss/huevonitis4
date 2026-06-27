"""Detección de marcadores fiduciales y rectificación/rotación de la plantilla.

Cluster auto-contenido: detecta los 4 marcadores de esquina, rectifica por
perspectiva al tamaño canónico y elige la rotación correcta (por marcadores+título
o, sin marcadores, por acuerdo del CNN). Separado de template_extract para acotarlo;
sólo depende de cv2/numpy, de TemplateLayout y de dos helpers de template_imageops
(_clean_cell, _rotate_cw). template_extract lo importa y re-exporta.
"""
from __future__ import annotations

import logging

from core.inkcore.template_imageops import _clean_cell, _rotate_cw
from core.inkcore.template_sheet import TemplateLayout

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

try:
    from PIL import Image  # noqa: F401  (presencia de PIL la chequea el guard de rotación)
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def _detect_fiducials(gray: np.ndarray, layout: TemplateLayout) -> np.ndarray | None:
    """Centros de los 4 marcadores (TL,TR,BL,BR) o None.

    Robusto a iluminación despareja (binarización adaptativa, no Otsu global:
    en fotos de celular un umbral único deja gris-roto el marcador de la esquina
    iluminada), a perspectiva (área mínima ABSOLUTA por bbox, no relativa a la
    foto: el fondo de mesa y los marcadores lejanos encogidos rompían el área
    relativa) y a bordes rotos (densidad medida sobre la máscara dentro del
    bbox, no contourArea).

    NO filtrar por cercanía a las esquinas de la FOTO: si la hoja flota en el
    centro con mucha mesa alrededor, los marcadores reales caen lejos de las
    esquinas de la imagen. La sanidad la dan los filtros del final.

    Medido contra el lote real: las palabras en negrita del título ("UNA",
    "Tinta"…) pasan el filtro de forma/área a 300dpi (~35px) y un cuadrilátero
    con una de ellas como cuarta esquina rectifica basura. Por eso, además del
    cuadrilátero grande, se exige (a) oscuridad real en GRIS (un marcador es
    ≥70% oscuro; una palabra tiene blanco entre letras), (b) coherencia de
    tamaño entre los 4 elegidos (≤4× de área) y (c) orden geométrico TL/TR/
    BL/BR consistente. Una foto con solo 2-3 marcadores en encuadre devuelve
    None (correcto: mejor caer a la grilla que rectificar con una esquina falsa).
    """
    h, w = gray.shape[:2]
    thr = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (5, 5), 0), 255,
        cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 51, 15,
    )
    thr = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    # Romper puentes finos: con mesa visible alrededor, el borde hoja↔fondo se
    # binariza como un marco y puede conectarse a un marcador cercano formando
    # un único blob gigante que lo esconde. El open no afecta a los
    # marcadores (sólidos ≥30px) ni a sus anillos tras el close.
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    # Componentes conexos, NO findContours(RETR_EXTERNAL): ese marco hoja↔fondo
    # es un contorno cerrado y los marcadores quedan anidados en su hueco →
    # RETR_EXTERNAL los omite. Los componentes no sufren anidamiento.
    n_comp, _labels, stats, _cent = cv2.connectedComponentsWithStats(thr, connectivity=8)
    min_area = 900                      # absoluto: ~30×30 px; no depende del fondo
    max_area = (w * h) * 0.02
    page_med = float(np.median(gray))
    cands: list[tuple[float, float, float]] = []  # (cx, cy, area_bbox)
    for ci in range(1, n_comp):
        x, y, bw, bh = (stats[ci, cv2.CC_STAT_LEFT], stats[ci, cv2.CC_STAT_TOP],
                        stats[ci, cv2.CC_STAT_WIDTH], stats[ci, cv2.CC_STAT_HEIGHT])
        area = bw * bh
        if area < min_area or area > max_area:
            continue
        if not (0.6 <= bw / max(1, bh) <= 1.6):     # cuadrados
            continue
        fill = float(stats[ci, cv2.CC_STAT_AREA]) / max(1, area)
        if fill < 0.55:                 # sólido, no un anillo ni texto
            continue
        # Oscuridad real: la adaptativa ahueca los cuadrados grandes (interior
        # negro = media local negra), así que el sólido se verifica en gris.
        dark = float((gray[y:y + bh, x:x + bw] < page_med - 60).mean())
        if dark < 0.70:
            continue
        cands.append((x + bw / 2.0, y + bh / 2.0, float(area)))
    if len(cands) < 4:
        return None

    corners = [(0, 0), (w, 0), (0, h), (w, h)]  # TL, TR, BL, BR
    chosen: list[tuple[float, float, float]] = []
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
        chosen.append(cands[best_i])
    # Sanidad 1: cuadrilátero grande (evita que 4 motas del centro pasen).
    xs = [p[0] for p in chosen]
    ys = [p[1] for p in chosen]
    if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 0.30 * w * h:
        return None
    # Sanidad 2: tamaños coherentes (la perspectiva encoge, pero no 4×).
    areas = [p[2] for p in chosen]
    if max(areas) > 4.0 * min(areas):
        return None
    # Sanidad 3: orden geométrico consistente (TL,TR,BL,BR de verdad).
    (tl, tr, bl, br) = chosen
    sep_x, sep_y = 0.15 * w, 0.15 * h
    if not (tr[0] - tl[0] > sep_x and br[0] - bl[0] > sep_x
            and bl[1] - tl[1] > sep_y and br[1] - tr[1] > sep_y):
        return None
    return np.array([(cx, cy) for cx, cy, _a in chosen], dtype=np.float32)

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

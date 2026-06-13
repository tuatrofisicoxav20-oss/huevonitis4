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

from core.inkcore.glyph_metrics import (
    finalize_sheet_geometry,
    measure_ink_bbox,
    template_geometry,
)
from core.inkcore.template_sheet import TEMPLATE_PRESETS, TemplateLayout

logger = logging.getLogger(__name__)

# Gate anti-corrupción (E2): acuerdo medio mínimo del CNN (P de la letra
# esperada sobre las casillas a-z) para CONFIAR en el mapeo letra↔casilla de
# una página y dejar que sus glifos entren al banco. Calibrado contra el lote
# real de 29 fotos: páginas bien mapeadas dan 0.358-0.450; páginas con el
# layout equivocado (un número etiquetado como letra, acentos cruzados) dan
# 0.038-0.054 — separación de ~6.6×, así que 0.12 discrimina sin falsos
# positivos. Por debajo: página suspect, no se guarda (ver assess_page_agreement).
TEMPLATE_PAGE_MIN_CNN_AGREEMENT = 0.12

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


def _clean_cell(cell_gray: np.ndarray, geom_out: dict | None = None) -> np.ndarray | None:
    """Binariza una casilla y deja sólo la tinta central (sin borde/rótulo).

    Devuelve una máscara uint8 (255=tinta) ya recortada al bbox de la letra, o
    None si la casilla está prácticamente vacía.

    R1: si se pasa ``geom_out`` (dict), se rellena con ``ink_bbox`` = bbox de la
    tinta en coords de la CELDA (pre-autocrop) — lo necesita la medición de
    sidebearings sin re-segmentar. No cambia nada del comportamiento.
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
    if geom_out is not None:
        geom_out["ink_bbox"] = (int(xs.min()), int(ys.min()),
                                int(xs.max()) + 1, int(ys.max()) + 1)
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


def _strip_title_band(comps: list, gy0: int, gy1: int) -> int:
    """Sube `gy0` por debajo de la banda del título (texto impreso), si la hay.

    En la foto de una plantilla, el bbox de contenido suele empezar en el TÍTULO
    ("Plantilla de letra — Huevonitis" + instrucciones), no en la primera fila de
    casillas. Eso corre toda la grilla hacia arriba: la fila 0 cae sobre el texto
    y se descarta (medido en el lote: a/b/c perdidas). El título es una banda de
    MUCHOS componentes PEQUEÑOS (letras de imprenta); las casillas tienen pocas
    piezas GRANDES (letra manuscrita). Se recorta desde arriba mientras la franja
    parezca texto, parando en la primera de contenido grande (la grilla).
    `comps` = lista de (x,y,w,h,area) ya filtrados de bordes.
    """
    span = gy1 - gy0
    if span <= 0:
        return gy0
    nb = 40
    step = max(1, span // nb)
    small_thr = 0.05 * span          # "componente pequeño" (título) vs letra grande
    new_y0 = gy0
    for b in range(nb // 2):         # sólo la mitad superior puede ser título
        lo, hi = gy0 + b * step, gy0 + (b + 1) * step
        band = [c for c in comps if lo <= c[1] + c[3] / 2 < hi]
        n_small = sum(1 for c in band if c[3] < small_thr)
        # Franja de título: muchas piezas chicas alineadas. Si la franja ya tiene
        # contenido grande (letra manuscrita) o poca densidad, paramos.
        if len(band) >= 12 and n_small >= 0.6 * len(band):
            new_y0 = hi
        elif band and max(c[3] for c in band) >= small_thr:
            break                    # llegó la primera fila de letras
    return new_y0


def _grid_content_bbox(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    """bbox de la grilla de casillas (sin título ni bordes de la foto).

    Robusto a líneas tenues (no depende de detectarlas, sólo del extent del
    contenido oscuro) y a fotos de celular: descarta los componentes pegados al
    borde de la imagen (sombras/marco de la mesa, que estiraban el bbox hasta los
    bordes y desalineaban las columnas) y recorta la banda del título superior
    (que corría la grilla hacia arriba y hacía perder la primera fila). Devuelve
    (x0, y0, x1, y1) o None si no hay contenido.
    """
    h_img, w_img = gray.shape[:2]
    binv = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (3, 3), 0), 255,
        cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 41, 10,
    )
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(binv, connectivity=8)
    comps: list[tuple[int, int, int, int, int]] = []
    for i in range(1, n):
        x, y, bw, bh = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                        stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])
        if stats[i, cv2.CC_STAT_AREA] < 25:     # motas
            continue
        # Descartar componentes pegados al borde de la IMAGEN (sombras/marco de
        # la foto): estiraban el bbox a 0..ancho y desalineaban la grilla.
        if x <= 2 or y <= 2 or x + bw >= w_img - 2 or y + bh >= h_img - 2:
            continue
        comps.append((x, y, bw, bh, int(stats[i, cv2.CC_STAT_AREA])))
    if not comps:
        # Fallback: sin componentes interiores (p. ej. grilla que toca el borde),
        # volver al método simple por percentiles de píxel.
        ys, xs = np.where(binv > 0)
        if len(xs) == 0:
            return None
        x0, x1 = np.percentile(xs, [0.3, 99.7])
        y0, y1 = np.percentile(ys, [0.3, 99.7])
        return int(x0), int(y0), int(x1), int(y1)
    x0 = int(np.percentile([c[0] for c in comps], 1))
    x1 = int(np.percentile([c[0] + c[2] for c in comps], 99))
    y0 = int(np.percentile([c[1] for c in comps], 1))
    y1 = int(np.percentile([c[1] + c[3] for c in comps], 99))
    y0 = _strip_title_band(comps, y0, y1)
    return x0, y0, x1, y1


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


def _cell_ink_mask(cell: np.ndarray) -> np.ndarray | None:
    """Máscara de tinta de la celda (255=tinta), del MISMO tamaño que `cell`.

    Binariza, quita líneas de grilla (morfología + bandas de borde) y descarta
    motas y los separadores que cruzan toda la celda. NO autocrop: devuelve la
    máscara completa para poder medir el contacto con el borde (ver inset
    adaptativo en _extract_grid). None si la celda está prácticamente vacía.
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
    # Piso de tinta bajo (E4): trazos delgados ('i', 'l', 't', comas, puntos)
    # tienen poca área y el umbral viejo (h·w·0.004) los rechazaba como vacíos.
    # max(25, h·w·0.0015) los conserva; las motas ya las filtró el guard de área
    # de arriba, así que bajar el piso no reintroduce ruido.
    if ink < max(25, h * w * 0.0015):
        return None
    return keep


def _autocrop_mask(keep: np.ndarray, pad: int = 6) -> np.ndarray | None:
    ys, xs = np.where(keep > 0)
    if len(xs) == 0:
        return None
    h, w = keep.shape[:2]
    return keep[max(0, ys.min() - pad):min(h, ys.max() + 1 + pad),
                max(0, xs.min() - pad):min(w, xs.max() + 1 + pad)]


def _clean_cell_grid(cell: np.ndarray) -> np.ndarray | None:
    """Máscara de tinta de la celda, recortada al bbox de la letra (con padding)."""
    keep = _cell_ink_mask(cell)
    if keep is None:
        return None
    return _autocrop_mask(keep)


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


def score_layout_cheap(
    gray: np.ndarray, layout: TemplateLayout, *,
    deskewed: np.ndarray | None = None, bbox: tuple | None = None,
) -> dict:
    """Puntúa BARATO qué tan bien la grilla de `layout` calza con la foto.

    Sin CNN, sin to_rgba_smooth, sin assess_quality: sólo binariza y cuenta por
    casilla rotulada. Pensado para elegir el preset correcto entre muchos
    candidatos × 4 rotaciones sin reventar el i5 (<300ms/página/preset). La
    extracción completa (cara) corre sólo sobre el ganador.

    Idea: el preset CORRECTO alinea cada casilla con una celda real de la grilla
    impresa → las casillas con tinta tienen UNA letra (pocas piezas, tinta en un
    rango sano). Un preset con muy pocas columnas mete varias letras por celda
    (tinta alta, >7 piezas); con demasiadas, parte letras (tinta ínfima). Ambos
    desvíos bajan el score.

    `deskewed`/`bbox` se pueden inyectar (el deskew Hough y el bbox son lo caro)
    para reusarlos entre todos los presets de una misma rotación: el orquestador
    los computa UNA vez por rotación. Si no se pasan, se calculan acá.

    Devuelve {"score", "n_inked", "n_healthy", "n_crowded"} — el score en [−0.5,1]
    es (sanas − 0.5·sobrepobladas) / casillas_con_tinta, o 0 si no hay tinta.
    """
    g = deskewed if deskewed is not None else _deskew(gray, _estimate_skew(gray))
    bb = bbox if bbox is not None else _grid_content_bbox(g)
    if bb is None:
        return {"score": 0.0, "n_inked": 0, "n_healthy": 0, "n_crowded": 0}
    gx0, gy0, gx1, gy1 = bb
    xs = np.linspace(gx0, gx1, layout.cols + 1)
    ys = np.linspace(gy0, gy1, layout.rows + 1)
    n_inked = n_healthy = n_crowded = 0
    for i in range(min(layout.n_cells, len(layout.charset) * layout.repeats)):
        if layout.cell_letter(i) is None:
            continue
        r, c = divmod(i, layout.cols)
        x0, x1 = xs[c], xs[c + 1]
        y0, y1 = ys[r], ys[r + 1]
        cw, chh = x1 - x0, y1 - y0
        # Inset 13% para excluir los separadores de la grilla (como _extract_grid).
        ix0, ix1 = int(x0 + 0.13 * cw), int(x1 - 0.13 * cw)
        iy0, iy1 = int(y0 + 0.13 * chh), int(y1 - 0.13 * chh)
        cell = g[iy0:iy1, ix0:ix1]
        if cell.size == 0:
            continue
        thr = cv2.adaptiveThreshold(
            cv2.GaussianBlur(cell, (3, 3), 0), 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12,
        )
        ink_frac = float((thr > 0).mean())
        if ink_frac < 0.002:            # casilla vacía: no cuenta ni a favor ni en contra
            continue
        n_inked += 1
        if ink_frac > 0.25:             # demasiada tinta: celda abarca varias letras
            n_crowded += 1
            continue
        ncomp = _sizable_components(thr)
        if ncomp > 7:                   # muchas piezas: multi-letra / texto
            n_crowded += 1
        else:
            n_healthy += 1
    if n_inked == 0:
        return {"score": 0.0, "n_inked": 0, "n_healthy": 0, "n_crowded": 0}
    score = (n_healthy - 0.5 * n_crowded) / n_inked
    return {"score": score, "n_inked": n_inked,
            "n_healthy": n_healthy, "n_crowded": n_crowded}


def _extract_grid(gray, lay, clf, char_to_label):
    """Extracción para plantillas SIN fiduciales: detecta la grilla en la foto.

    En vez de asumir la geometría canónica (que sólo vale si rectificamos por los
    4 marcadores), deskewa la foto, halla el bbox del contenido y divide en
    lay.cols × lay.rows celdas uniformes, limpiando líneas de grilla por celda.
    Esto evita lo que rompía la ruta vieja (un simple resize desalineaba las
    casillas → recortes sobre líneas y letras partidas). Mismo formato de salida
    que extract_from_template: lista de (letra, glifo_RGBA, score).
    """
    from core.inkcore.glyph_ingest import assess_quality, to_rgba_smooth

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
    logger.info("_extract_grid: skew=%.2f° grilla %dx%d bbox=%s", ang, n_cols, n_rows, bb)

    def _crop(r, c, inset):
        x0, x1 = xs[c], xs[c + 1]
        y0, y1 = ys[r], ys[r + 1]
        cw, chh = x1 - x0, y1 - y0
        ix0, ix1 = int(x0 + inset * cw), int(x1 - inset * cw)
        iy0, iy1 = int(y0 + inset * chh), int(y1 - inset * chh)
        return gray[iy0:iy1, ix0:ix1]

    results: list[tuple[str, Image.Image, float]] = []
    for r in range(n_rows):
        for c in range(n_cols):
            i = r * n_cols + c
            ch = lay.cell_letter(i)
            if ch is None:
                continue
            # Inset adaptativo: arranca con 13% (excluye los separadores de la
            # grilla). Si la letra quedó RECORTADA por estar descentrada (p. ej. la
            # 'o' alta cuyo arco superior cae fuera del crop), un inset chico (4%)
            # captura MÁS tinta. Se adopta el inset chico sólo cuando (a) suma
            # ≥15% de tinta y (b) NO agrega componentes: la letra recuperada se
            # conecta a la existente (mismo nº de piezas), mientras que un
            # separador de grilla entraría como pieza NUEVA → se rechaza. Así sólo
            # se beneficia a las casillas recortadas, sin reintroducir grilla en
            # las centradas.
            inset_used = 0.13
            keep = _cell_ink_mask(_crop(r, c, 0.13))
            if keep is None:
                continue
            keep_big = _cell_ink_mask(_crop(r, c, 0.04))
            if (keep_big is not None
                    and (keep_big > 0).sum() >= 1.15 * (keep > 0).sum()
                    and _sizable_components(keep_big) <= _sizable_components(keep)):
                keep = keep_big
                inset_used = 0.04
            mask = _autocrop_mask(keep)
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
            # R1: geometría con la celda detectada como referencia. El "em"
            # descuenta la franja del rótulo en su proporción canónica (la
            # grilla detectada incluye el rótulo impreso dentro de la celda).
            cw_full = float(xs[c + 1] - xs[c])
            ch_full = float(ys[r + 1] - ys[r])
            em = round(ch_full * (1.0 - lay.label_strip / lay.cell_h))
            bb = measure_ink_bbox(keep)
            ins_x = inset_used * cw_full
            glyph.info["geometry"] = template_geometry(
                mask, ch, em_px=em,
                lsb=round(ins_x + bb[0]) if bb else 0,
                rsb=round(cw_full - (ins_x + bb[2])) if bb else 0,
            )
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
    finalize_sheet_geometry(results)  # R1: baselines de descendentes por hoja
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

    from core.inkcore.glyph_ingest import assess_quality, to_rgba_smooth
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
        geom: dict = {}
        mask = _clean_cell(cell, geom_out=geom)
        if mask is None:
            continue
        glyph = to_rgba_smooth(mask)
        # R1: geometría con el área de escritura de la casilla como referencia
        # (su alto = "em" de la hoja). Viaja en Image.info para no cambiar la
        # API (char, glifo, score); save_template_glyphs_to_bank la persiste.
        bb = geom.get("ink_bbox")
        glyph.info["geometry"] = template_geometry(
            mask, ch, em_px=wh,
            lsb=bb[0] if bb else 0,
            rsb=(ww - bb[2]) if bb else 0,
        )
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
    # R1: el baseline de las descendentes se reconstruye con la x-height
    # mediana de ESTA hoja (sólo se conoce con la extracción completa).
    finalize_sheet_geometry(results)
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
    return any(_detect_fiducials(_rotate_cw(gray, angle), lay) is not None
               for angle in (0, 90, 180, 270))


def _page_cnn_scores(results, clf, char_to_label) -> list[float]:
    """P(letra esperada) del CNN por cada casilla a-z extraída de la página.

    Solo a-z (la ñ, dígitos y signos no los cubre el CNN EMNIST). Devuelve la
    lista cruda — el promedio (orientación) y el conteo (gate anti-corrupción)
    la consumen distinto: una página de dígitos con su preset correcto da lista
    VACÍA (no hay a-z), que NO es lo mismo que acuerdo bajo.
    """
    scores: list[float] = []
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
            scores.append(float(v))
    return scores


def _grid_cnn_agreement(results, clf, char_to_label) -> float:
    """Acuerdo medio del CNN entre cada casilla a-z y su letra esperada.

    Es la señal para elegir orientación sin fiduciales: la rotación correcta hace
    que cada letra caiga en su casilla → P(letra esperada) alto (~0.4-0.6); una
    rotación equivocada deja letras cruzadas → ~0.02. Diferencia de 10-15×, así
    que discrimina con claridad. Solo cuenta a-z (la ñ no la cubre el CNN).
    """
    scores = _page_cnn_scores(results, clf, char_to_label)
    return sum(scores) / len(scores) if scores else 0.0


def assess_page_agreement(
    results, clf, char_to_label, *, min_agreement: float = TEMPLATE_PAGE_MIN_CNN_AGREEMENT,
) -> tuple[float | None, bool, str]:
    """Gate anti-corrupción: decide si una página es sospechosa de mapeo cruzado.

    Devuelve (page_agreement, suspect, reason). El acuerdo del CNN discrimina
    limpio entre una página bien mapeada (letras en su casilla → P alto) y una
    con el layout equivocado (un '5' manuscrito etiquetado 'g' → P ínfima):
    medido en el lote real, estándar ~0.4-0.6 vs cruzada ~0.02, 10-15× de
    separación. Por debajo de `min_agreement` la página NO debe guardarse: mejor
    fallar ruidosamente que envenenar el banco con etiquetas equivocadas.

    Casos límite, por seguridad:
      - Sin CNN disponible → (None, False, "sin validación CNN"): no se bloquea
        al usuario, pero el reporte avisa que vuela a ciegas.
      - Sin casillas a-z que puntuar (p. ej. una página de dígitos con su preset
        correcto) → (None, False, "sin casillas a-z para validar"): el CNN no
        aplica; la confianza la da la señal estructural del preset (Fase E3),
        no este gate. Esto evita marcar suspect una página legítima de dígitos.
    """
    if clf is None:
        return None, False, "sin validación CNN"
    scores = _page_cnn_scores(results, clf, char_to_label)
    if not scores:
        return None, False, "sin casillas a-z para validar"
    agreement = sum(scores) / len(scores)
    if agreement < min_agreement:
        return agreement, True, (
            f"mapeo letra↔casilla no confiable (acuerdo CNN {agreement:.2f} "
            f"< {min_agreement:.2f})"
        )
    return agreement, False, ""


def _load_template_cnn():
    """(clf, char_to_label) si el CNN EMNIST está disponible, si no (None, None).

    El CNN es señal opcional (orientación + gate anti-corrupción), nunca un
    requisito duro: sin torch/modelo se degrada con aviso, no se rompe.
    """
    try:
        from core.inkcore.ai.char_cnn import EMNISTCharClassifier, char_to_label
        clf = EMNISTCharClassifier()
        if clf.available:
            return clf, char_to_label
    except Exception as exc:
        logger.info("_load_template_cnn: CNN no disponible (%s)", exc)
    return None, None


def extract_from_template_auto_meta(
    image_path: str, layout: TemplateLayout | None = None, *, clf=None, char_to_label=None,
) -> dict:
    """Extrae una página con autorrotación Y el veredicto del gate anti-corrupción.

    Devuelve un dict rico:
        {"results": [(char, glyph, score), ...],   # casillas con tinta
         "rotation": int,                          # rotación horaria aplicada
         "page_agreement": float | None,           # acuerdo CNN medio (a-z)
         "suspect": bool,                          # True = NO guardar (mapeo dudoso)
         "reason": str}                            # por qué es suspect / aviso

    CON fiduciales: orienta por marcadores+título (`detect_template_rotation`).
    SIN fiduciales: prueba las 4 rotaciones con extracción de grilla y se queda
    con la de mayor acuerdo CNN casilla↔letra (la canónica está rota sin
    marcadores, por eso no se usa). En ambos caminos, al final, el gate evalúa el
    acuerdo de la página: una página con el layout equivocado (números/acentos
    extraídos como minúsculas) cae muy por debajo del umbral → suspect=True y la
    UI no la guarda. `clf`/`char_to_label` se pueden inyectar para no recargar el
    modelo por página (lo hace el orquestador de PDF).
    """
    lay = layout or TemplateLayout()
    if clf is None and char_to_label is None:
        clf, char_to_label = _load_template_cnn()

    if _has_fiducials(image_path, lay):
        angle = detect_template_rotation(image_path, lay)
        results = extract_from_template(image_path, lay, pre_rotate=angle)
        rot = angle
    elif clf is None:
        results = extract_from_template(image_path, lay, pre_rotate=0)
        rot = 0
    else:
        best_res, best_score, best_rot = [], -1.0, 0
        for r in (0, 90, 180, 270):
            res = extract_from_template(image_path, lay, pre_rotate=r)
            sc = _grid_cnn_agreement(res, clf, char_to_label)
            if sc > best_score:
                best_score, best_res, best_rot = sc, res, r
        results, rot = best_res, best_rot
        logger.info(
            "extract_from_template_auto: sin fiduciales — rot %d° (acuerdo CNN=%.3f)",
            best_rot, best_score,
        )

    agreement, suspect, reason = assess_page_agreement(results, clf, char_to_label)
    if suspect:
        logger.warning(
            "gate anti-corrupción: página DUDOSA (%s) — %d casillas NO se guardarán",
            reason, len(results),
        )
    return {"results": results, "rotation": rot, "page_agreement": agreement,
            "suspect": suspect, "reason": reason}


def extract_from_template_auto(
    image_path: str, layout: TemplateLayout | None = None,
) -> list[tuple[str, Image.Image, float]]:
    """Wrapper compat: como `extract_from_template_auto_meta` pero devuelve solo
    la lista (char, glifo, score). Conserva la firma histórica que usan los tests
    y cualquier llamador que no necesite el veredicto del gate. El flujo de la UI
    consume la versión `_meta` (o `extract_pdf_pages`) para respetar `suspect`.
    """
    return extract_from_template_auto_meta(image_path, layout)["results"]


# Score estructural mínimo (E3) para CONFIAR en que un preset identificó el
# layout de una página sin fiduciales. Por debajo: "layout no identificado" →
# suspect, no se guarda. Calibrado con el harness contra el lote real.
TEMPLATE_LAYOUT_MIN_SCORE = 0.45


def _unique_geometries(presets: dict) -> dict:
    """(cols, rows) → [nombres de presets con esa geometría].

    El scoring barato sólo ve la estructura, así que presets con igual geometría
    dan idéntico score: se agrupan para puntuar UNA vez por geometría y desempatar
    luego por CNN (las hojas de minúsculas parciales caen todas en 6×16).
    """
    geoms: dict[tuple[int, int], list[str]] = {}
    for name, lay in presets.items():
        geoms.setdefault((lay.cols, lay.rows), []).append(name)
    return geoms


def _downscale(gray: np.ndarray, target_w: int = 800) -> np.ndarray:
    """Reduce a `target_w` de ancho (para scoring estructural barato de rotación)."""
    h, w = gray.shape[:2]
    if w <= target_w:
        return gray
    s = target_w / w
    return cv2.resize(gray, (target_w, max(1, int(h * s))), interpolation=cv2.INTER_AREA)


# Ancho al que se reduce la foto para el ANÁLISIS (rotación + geometría) por
# agreement CNN. El CNN preprocesa a 28×28, así que ~1240px (resolución
# canónica) no le quita señal y acelera ~4× vs los 2481-3508px de la foto. La
# extracción FINAL del ganador corre a resolución completa (calidad de glifos).
_ANALYSIS_WIDTH = 1240


def _rotation_candidates(gray: np.ndarray) -> tuple[int, ...]:
    """Rotaciones plausibles según el aspecto: la hoja canónica es retrato.

    Una foto cargada en retrato (alto>ancho) está derecha o invertida → {0,180};
    una apaisada la giró el escáner 90° → {90,270}. Reduce el barrido de
    agreement de 4 a 2 candidatos (el agreement decide cuál de los 2, ya que la
    estructura no distingue una hoja de su versión 180°).
    """
    h, w = gray.shape[:2]
    return (0, 180) if h >= w else (90, 270)


def _layout_agreement_fast(deskewed, bbox, lay, clf, char_to_label) -> tuple[float, int]:
    """Acuerdo CNN (a-z) de un preset reusando deskew+bbox YA computados.

    No vuelve a deskewar ni a hallar el bbox (lo caro): el orquestador los pasa
    una vez por rotación y esta función sólo proyecta la grilla del preset y
    puntúa las casillas a-z con tinta. Devuelve (agreement, n_casillas_az). Sin
    to_rgba_smooth ni assess_quality — barato, sólo la máscara para el CNN.
    """
    if bbox is None or clf is None:
        return 0.0, 0
    gx0, gy0, gx1, gy1 = bbox
    xs = np.linspace(gx0, gx1, lay.cols + 1)
    ys = np.linspace(gy0, gy1, lay.rows + 1)
    scores: list[float] = []
    n_az = 0
    for i in range(min(lay.n_cells, len(lay.charset) * lay.repeats)):
        ch = lay.cell_letter(i)
        if ch is None or char_to_label(ch) is None:
            continue
        r, c = divmod(i, lay.cols)
        x0, x1 = xs[c], xs[c + 1]
        y0, y1 = ys[r], ys[r + 1]
        cw, chh = x1 - x0, y1 - y0
        ix0, ix1 = int(x0 + 0.13 * cw), int(x1 - 0.13 * cw)
        iy0, iy1 = int(y0 + 0.13 * chh), int(y1 - 0.13 * chh)
        mask = _clean_cell_grid(deskewed[iy0:iy1, ix0:ix1])
        if mask is None:
            continue
        n_az += 1
        v = clf.score(mask, ch)
        if v is not None:
            scores.append(float(v))
    return (sum(scores) / len(scores) if scores else 0.0), n_az


def _extract_page_multilayout(image_path, presets, hint_name, clf, char_to_label):
    """Elige el preset por página (barrido rotación×geometría por agreement CNN).

    El scoring ESTRUCTURAL no identifica la geometría de forma fiable (premia
    grillas finas) ni la orientación 0°/180° (la grilla se ve igual invertida).
    La señal confiable es el AGREEMENT CNN: la combinación (rotación, geometría)
    correcta pone cada letra en su casilla → acuerdo alto; distingue además
    minúsculas×1 de ×3 (con ×3 la casilla 1 se rotula 'a' pero contiene 'b').

    Pasos (todo el análisis a resolución reducida; la extracción final del
    ganador a resolución completa):
      1. Candidatos de rotación por aspecto (retrato→{0,180}, apaisada→{90,270}).
      2. Barrido (rotación × geometría a-z única) por agreement, reusando
         deskew+bbox por rotación. Mejor (rot, geom).
      3. Si la geometría ganadora es 6×16 (varias hojas la comparten), desempatar
         el charset por agreement en la rotación ganadora.
      4. Si el mejor agreement supera el umbral del gate → página de LETRAS:
         extracción completa + gate.
      5. Si no → no es página de letras (acentos/dígitos, que el CNN no puntúa):
         NO se extrae completo (sería caro e inútil; igual quedaría suspect). Se
         devuelve suspect con el preset tentativo por estructura para que el
         usuario reasigne a mano (E5) y recién ahí se extraiga.

    Devuelve el dict rico de la página. Ver `extract_pdf_pages`.
    """
    bgr = cv2.imread(image_path)
    if bgr is None:
        return {"results": [], "preset": None, "rotation": -1, "layout_score": 0.0,
                "page_agreement": None, "suspect": True, "reason": "no se pudo leer la imagen"}
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    small_base = _downscale(gray, _ANALYSIS_WIDTH)

    # Identificación en dos pasos para acotar el cómputo (deskew+bbox es lo caro):
    #   (1) ROTACIÓN: se prueba el preset de referencia (minúsculas×1, 27 casillas
    #       a-z, el más informativo) en las 2 rotaciones candidatas. El contenido
    #       manuscrito está en la orientación correcta aunque la página no sea de
    #       minúsculas, así que su agreement marca la rotación.
    #   (2) GEOMETRÍA/CHARSET: en la rotación ganadora se prueba el resto de
    #       presets a-z (los de 6×16 —aeiosnr/ltcdmp/resto— sólo difieren en el
    #       charset y sólo el correcto da agreement alto).
    az_names = [n for n, lay in presets.items()
                if any(char_to_label(c) for c in lay.charset)]
    ref_name = "minusculas_x1" if "minusculas_x1" in presets else (az_names[0] if az_names else None)

    cache: dict[int, tuple] = {}
    win_rot, ref_agr = _rotation_candidates(small_base)[0], -1.0
    if ref_name is not None:
        for rot in _rotation_candidates(small_base):
            g = _rotate_cw(small_base, rot)
            dk = _deskew(g, _estimate_skew(g))
            bb = _grid_content_bbox(dk)
            cache[rot] = (dk, bb)
            agr, n_az = _layout_agreement_fast(dk, bb, presets[ref_name], clf, char_to_label)
            if n_az >= 5 and agr > ref_agr:
                ref_agr, win_rot = agr, rot

    dk, bb = cache.get(win_rot, (None, None))
    if dk is None:
        g = _rotate_cw(small_base, win_rot)
        dk = _deskew(g, _estimate_skew(g))
        bb = _grid_content_bbox(dk)
        cache[win_rot] = (dk, bb)
    best = (ref_agr, ref_name) if ref_name is not None else (-1.0, None)
    for name in az_names:
        if name == ref_name:
            continue
        agr, n_az = _layout_agreement_fast(dk, bb, presets[name], clf, char_to_label)
        if n_az < 5:
            continue
        if agr > best[0]:
            best = (agr, name)

    if best[1] is not None and best[0] >= TEMPLATE_PAGE_MIN_CNN_AGREEMENT:
        win_agr, win_name = best
        results = extract_from_template(image_path, presets[win_name], pre_rotate=win_rot)
        agr2, suspect, reason = assess_page_agreement(results, clf, char_to_label)
        agreement = agr2 if agr2 is not None else win_agr
        if suspect:
            logger.warning("multilayout %s: DUDOSA (%s)", win_name, reason)
        else:
            logger.info("multilayout: preset=%s rot=%d° agreement=%.3f n=%d",
                        win_name, win_rot, agreement, len(results))
        return {"results": results, "preset": win_name, "rotation": win_rot,
                "layout_score": round(win_agr, 3), "page_agreement": agreement,
                "suspect": suspect, "reason": reason}

    # No es página de letras (acentos/dígitos): NO extraer completo (caro e
    # inútil — queda suspect igual). Preset tentativo por estructura; el usuario
    # reasigna en E5 y ahí se extrae.
    win_rot = _rotation_candidates(small_base)[0]
    g = _rotate_cw(small_base, win_rot)
    dk, bb = cache.get(win_rot, (None, None))
    if dk is None:
        dk = _deskew(g, _estimate_skew(g))
        bb = _grid_content_bbox(dk)
    non_az = {n: lay for n, lay in presets.items()
              if not any(char_to_label(c) for c in lay.charset)}
    best_struct = None
    for name, lay in non_az.items():
        sc = score_layout_cheap(g, lay, deskewed=dk, bbox=bb)
        if best_struct is None or sc["score"] > best_struct[0]:
            best_struct = (sc["score"], name)
    win_name = best_struct[1] if best_struct else max(presets, key=lambda n: presets[n].n_cells)
    struct_score = best_struct[0] if best_struct else 0.0
    reason = ("no parece página de letras (posibles acentos/dígitos, que el CNN "
              "no valida) — elegí el preset a mano para extraer y guardar")
    logger.warning("multilayout: página no-letras → tentativo=%s (suspect, sin extraer)",
                   win_name)
    return {"results": [], "preset": win_name, "rotation": win_rot,
            "layout_score": round(struct_score, 3), "page_agreement": None,
            "suspect": True, "reason": reason}


def extract_pdf_pages(
    image_paths: list[str], *, layout_hint: TemplateLayout | None = None,
    presets: dict | None = None, clf=None, char_to_label=None,
) -> list[dict]:
    """Orquestador multi-layout (E3): elige el preset correcto POR PÁGINA.

    Un PDF puede mezclar hojas de layouts distintos (minúsculas, acentos,
    dígitos…). Aplicar UN solo layout a todas envenena el banco (un número
    etiquetado como letra). Acá cada página se puntúa contra los presets
    conocidos con scoring estructural BARATO (4 rotaciones × geometrías únicas),
    se extrae completa sólo con el preset ganador y se valida con el gate
    anti-corrupción. El snapshot del usuario (`layout_hint`) es sólo una pista de
    prioridad (su preset se prueba primero ante empate), nunca una imposición.

    Devuelve un dict por página:
        {"results": [(char, glyph, score), ...],
         "preset": str | None,          # nombre del preset elegido
         "rotation": int,               # rotación horaria aplicada
         "layout_score": float,         # score estructural del ganador
         "page_agreement": float | None,# acuerdo CNN (a-z) del ganador
         "suspect": bool,               # True = NO guardar
         "reason": str}
    """
    if clf is None and char_to_label is None:
        clf, char_to_label = _load_template_cnn()
    presets = presets or TEMPLATE_PRESETS
    # Resolver el hint a un nombre de preset (si coincide con uno registrado).
    hint_name = None
    if layout_hint is not None:
        for name, lay in presets.items():
            if lay.charset == layout_hint.charset and lay.repeats == layout_hint.repeats:
                hint_name = name
                break
    out = []
    for path in image_paths:
        try:
            out.append(_extract_page_multilayout(path, presets, hint_name, clf, char_to_label))
        except Exception as exc:
            logger.error("extract_pdf_pages %s: %s", path, exc, exc_info=True)
            out.append({"results": [], "preset": None, "rotation": -1,
                        "layout_score": 0.0, "page_agreement": None,
                        "suspect": True, "reason": f"error: {exc}"})
    return out


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

    from core.inkcore.glyph_filters import capture_gate, measure_glyph
    from core.inkcore.quality import classify_tier
    if temp_dir is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="tpl_glyphs_"))
    else:
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
    saved = dupes = rejected = 0
    rejects: list[tuple[str, int, str]] = []
    # Gate de captura: los umbrales relativos se calibran con la mediana de lo
    # YA existente en el banco para ese char (medido una vez por char y tanda);
    # con un char nuevo solo aplican los umbrales absolutos de fallback.
    bank_metrics_cache: dict[str, list] = {}
    for i, (ch, glyph, q) in enumerate(results):
        cached = bank_metrics_cache.get(ch)
        if cached is None:
            cached = []
            for e in bank.get_all(char_filter=ch):
                try:
                    with Image.open(e.image_path) as im:
                        cached.append(measure_glyph(im.convert("RGBA")))
                except Exception:
                    continue
            bank_metrics_cache[ch] = cached
        ok, reason = capture_gate(glyph, ch, cached)
        if not ok:
            rejected += 1
            rejects.append((ch, i, reason))
            logger.info("gate de captura: '%s' celda #%d rechazado — %s", ch, i, reason)
            continue
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
        # R1: la geometría medida en la extracción viaja en Image.info; acá se
        # persiste al manifest junto con el glifo.
        entry = bank.add_glyph(ch, str(p), skip_dedup=True, quality_override=override,
                               geometry=glyph.info.get("geometry"))
        if entry is None:
            dupes += 1
        else:
            saved += 1
    for f in temp_dir.glob("*.png"):
        with contextlib.suppress(OSError):
            f.unlink()
    if rejects:
        _append_reject_log(rejects)
    logger.info("save_template_glyphs_to_bank: saved=%d dupes=%d rejected=%d total=%d",
                saved, dupes, rejected, len(results))
    return {"saved": saved, "dupes": dupes, "rejected": rejected,
            "total": len(results)}


def _append_reject_log(rejects: list[tuple[str, int, str]]) -> None:
    """extract_rechazados.csv: qué celdas de la tanda rebotó el gate y por qué.

    Vive junto al banco (TIPOGRAFIA_DIR) y es acumulativo por tanda, para que
    el usuario sepa qué casillas de la plantilla debe re-escribir.
    """
    import csv
    import time as _time

    import config as _config
    path = _config.TIPOGRAFIA_DIR / "extract_rechazados.csv"
    new = not path.exists()
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp", "char", "celda", "reason"])
            ts = _time.strftime("%Y-%m-%d %H:%M:%S")
            for ch, idx, reason in rejects:
                w.writerow([ts, ch, idx, reason])
    except OSError as exc:
        logger.warning("no se pudo escribir extract_rechazados.csv: %s", exc)

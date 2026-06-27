"""Operaciones de imagen de bajo nivel para la extracción por plantilla.

Cluster auto-contenido de helpers de visión (deskew, binarización de celda,
detección del bbox de la grilla, estimación de columnas/filas por
autocorrelación, limpieza de líneas de grilla). Se separó de ``template_extract``
(que pasaba de 1500 LOC) para acotar ese módulo: estas funciones sólo dependen de
cv2/numpy y de ninguna otra del extractor, así que ``template_extract`` las
importa y re-exporta sin ciclos. La lógica es idéntica; sólo cambió de archivo.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False


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

def _autocorr_period(proj: np.ndarray, span: int) -> tuple[int | None, float]:
    """Período dominante de una proyección 1D por autocorrelación, y su fuerza.

    La grilla impone periodicidad en la proyección de tinta (las letras caen
    centradas en columnas/filas regulares), aunque las LÍNEAS impresas sean
    demasiado tenues para detectarse. Devuelve (período_px, pico_normalizado) o
    (None, 0). Busca el primer máximo local fuerte tras el lag 0, en un rango de
    lags plausible (≥ span/20: hasta ~20 divisiones; ≤ span/3: ≥3 divisiones).
    """
    proj = proj.astype(float) - float(proj.mean())
    if proj.std() < 1e-6:
        return None, 0.0
    ac = np.correlate(proj, proj, "full")[len(proj) - 1:]
    ac /= ac[0]
    best_lag, best_val = None, 0.0
    for lag in range(max(2, span // 20), max(3, span // 3)):
        if ac[lag] > best_val and ac[lag] > ac[lag - 1] and ac[lag] >= ac[lag + 1]:
            best_val, best_lag = float(ac[lag]), lag
    return best_lag, best_val

def _estimate_grid_dims(deskewed: np.ndarray, bbox: tuple | None) -> tuple | None:
    """Estima (cols, rows, confianza) de la grilla por autocorrelación de tinta.

    Para las hojas que el CNN no puede identificar (acentos, dígitos), el número
    de COLUMNAS distingue su geometría: acentos=6, dígitos=9. No depende de ver
    las líneas de grilla (Bug D) — usa la periodicidad de la tinta manuscrita,
    que está centrada en cada celda por construcción. Confianza = el menor de los
    dos picos de autocorrelación (col y fila). Devuelve None si no hay periodicidad
    clara (hoja casi vacía o a medio llenar sin estructura).
    """
    if bbox is None:
        return None
    gx0, gy0, gx1, gy1 = bbox
    crop = deskewed[gy0:gy1, gx0:gx1]
    if crop.size == 0 or crop.shape[0] < 20 or crop.shape[1] < 20:
        return None
    binv = cv2.adaptiveThreshold(
        cv2.GaussianBlur(crop, (3, 3), 0), 255,
        cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 41, 10,
    )
    col_proj = (binv > 0).sum(axis=0)
    row_proj = (binv > 0).sum(axis=1)
    col_lag, col_ac = _autocorr_period(col_proj, crop.shape[1])
    row_lag, row_ac = _autocorr_period(row_proj, crop.shape[0])
    if col_lag is None or row_lag is None:
        return None
    cols = round(crop.shape[1] / col_lag)
    rows = round(crop.shape[0] / row_lag)
    return cols, rows, min(col_ac, row_ac)

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

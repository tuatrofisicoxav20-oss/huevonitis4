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


def _detect_fiducials(gray: "np.ndarray", layout: TemplateLayout) -> "np.ndarray | None":
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


def _rectify(gray: "np.ndarray", layout: TemplateLayout) -> "np.ndarray":
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


def _clean_cell(cell_gray: "np.ndarray") -> "np.ndarray | None":
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


def extract_from_template(
    image_path: str, layout: TemplateLayout | None = None,
) -> list[tuple[str, "Image.Image", float]]:
    """Extrae un glifo por casilla rellena. Lista de (letra, glifo_RGBA, calidad).

    Sólo devuelve casillas con tinta suficiente (las vacías se omiten). No hay
    segmentación: cada casilla se mapea a su letra por posición fija en la grilla.
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
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    canon = _rectify(gray, lay)

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
            cnn = clf.score(mask, ch)
            if cnn is not None and cnn < 0.12:
                score = min(score, 0.45)
        results.append((ch, glyph, score))
    logger.info("extract_from_template: %d/%d casillas con tinta (repeats=%d)",
                len(results), n_labeled, lay.repeats)
    return results


def save_template_glyphs_to_bank(results, bank, temp_dir=None) -> dict:
    """Guarda los glifos extraídos de la plantilla en el banco dado.

    Escribe cada glifo a un PNG temporal y lo manda a `bank.add_glyph` (que copia
    al banco y persiste). Devuelve {saved, dupes, total}. Pensado para llamarse
    desde la UI con el bank vivo de la app (NO desde un script suelto sobre el
    banco real con la app abierta — colisiona el manifest).
    """
    import tempfile
    from pathlib import Path
    if temp_dir is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="tpl_glyphs_"))
    else:
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
    saved = dupes = 0
    for i, (ch, glyph, _q) in enumerate(results):
        safe = ch if ch.isalnum() else f"u{ord(ch)}"
        p = temp_dir / f"{safe}_{i:03d}.png"
        try:
            glyph.save(p)
        except Exception as exc:
            logger.warning("save_template: no se pudo escribir %s: %s", p, exc)
            continue
        entry = bank.add_glyph(ch, str(p))
        if entry is None:
            dupes += 1
        else:
            saved += 1
    for f in temp_dir.glob("*.png"):
        try:
            f.unlink()
        except OSError:
            pass
    logger.info("save_template_glyphs_to_bank: saved=%d dupes=%d total=%d",
                saved, dupes, len(results))
    return {"saved": saved, "dupes": dupes, "total": len(results)}

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
    0 vs 180). Si ninguna rotación detecta los 4 marcadores se devuelve 0 con un
    warning: la grilla podría quedar mal etiquetada y el usuario lo verá al
    revisar.
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
        logger.warning(
            "detect_template_rotation: marcadores no detectados en %s — default 0°",
            image_path,
        )
        return 0
    logger.info("detect_template_rotation: %s → rotar %d° horario", image_path, best_angle)
    return best_angle


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


def extract_from_template_auto(
    image_path: str, layout: TemplateLayout | None = None,
) -> list[tuple[str, Image.Image, float]]:
    """Como `extract_from_template`, pero detecta y corrige la rotación primero.

    Llama a `detect_template_rotation` para saber cuántos grados girar (el
    escáner gira 90° las hojas apaisadas) y extrae con ese `pre_rotate`. Pensado
    para el flujo de PDF multipágina, donde cada página puede venir con una
    orientación distinta.
    """
    lay = layout or TemplateLayout()
    angle = detect_template_rotation(image_path, lay)
    return extract_from_template(image_path, lay, pre_rotate=angle)


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

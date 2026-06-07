"""Operaciones a nivel glifo: refine_char_region, tight_crop, to_rgba_smooth, assess_quality.

Separadas de extractor.py para mantener cada archivo manejable y permitir
reutilizar estas operaciones desde la pipeline ensemble sin importar todo
GlyphExtractor.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV_OK = True
except ImportError:
    _CV_OK = False

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# Tamaño mínimo de componente para considerar "no ruido"; coincide con
# la constante del extractor original.
MIN_COMP_AREA = 10
QUALITY_MIN = 0.18


def _is_ruled_line(w: int, h: int, frac_w: float) -> bool:
    """Heurística: ¿el componente parece un resto de línea de renglón?

    Una línea de cuaderno sobrevive a la limpieza como una franja MUY ancha y
    MUY fina (alta relación ancho/alto) que ocupa buena parte del ancho del
    recorte. Las letras y sus diacríticos no tienen esa forma, así que esto no
    debería tragarse trazos legítimos (la barra de la 't' o el guion son cortos
    en comparación con el ancho total del glifo).
    """
    if h <= 0:
        return False
    return h <= 3 and w >= 6 * h and frac_w >= 0.55


def _clean_mask_noise(mask: np.ndarray) -> np.ndarray:
    """Quita ruido del recorte conservando la letra y sus diacríticos.

    El recorte que llega es un rectángulo de la máscara limpia: puede arrastrar
    motas sueltas y restos de línea de renglón que cayeron dentro de la caja
    pero NO son parte de la letra. Estrategia:

      • Componente principal = el de mayor área (el cuerpo del trazo).
      • Se conservan además los componentes "satélite" plausibles: diacríticos
        (punto de i/j, tilde de ñ, acentos) y fragmentos del propio trazo que
        quedaron separados, identificados por cercanía al cuerpo principal y
        tamaño no despreciable.
      • Se descartan motas diminutas alejadas y franjas tipo renglón.

    Devuelve una máscara del mismo tamaño con solo lo conservado. Si algo sale
    mal (o no hay cv2), devuelve la máscara original sin tocar.
    """
    if not _CV_OK or mask is None or mask.size == 0:
        return mask
    binary = (mask > 0).astype(np.uint8)
    if not binary.any():
        return mask
    num, labels, stats, _cent = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if num < 2:
        return mask

    _h_img, w_img = binary.shape[:2]
    areas = stats[1:, cv2.CC_STAT_AREA]
    main_id = int(np.argmax(areas)) + 1
    main_area = int(stats[main_id, cv2.CC_STAT_AREA])
    mx = int(stats[main_id, cv2.CC_STAT_LEFT])
    my = int(stats[main_id, cv2.CC_STAT_TOP])
    mw = int(stats[main_id, cv2.CC_STAT_WIDTH])
    mh = int(stats[main_id, cv2.CC_STAT_HEIGHT])
    mcx = mx + mw / 2.0

    # Política: por defecto se DESCARTA cualquier componente que no sea el
    # cuerpo. Solo se conserva un satélite si es claramente parte de la letra:
    #   (A) un fragmento grande del propio trazo (área comparable al cuerpo), o
    #   (B) un diacrítico compacto bien colocado ARRIBA del cuerpo y centrado
    #       (punto de i/j, tilde de ñ, acento). Lo demás a esta escala es mota.
    # Umbrales relativos al cuerpo → robustos a la escala de la imagen.
    frag_area = max(MIN_COMP_AREA * 2, int(main_area * 0.18))   # (A) fragmento real
    dia_min = max(6, int(main_area * 0.03))                     # (B) tamaño mínimo de diacrítico
    dia_max = int(main_area * 0.55)                             # un diacrítico no es tan grande

    keep = {main_id}
    for i in range(1, num):
        if i == main_id:
            continue
        area = int(stats[i, cv2.CC_STAT_AREA])
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        cw = int(stats[i, cv2.CC_STAT_WIDTH])
        ch = int(stats[i, cv2.CC_STAT_HEIGHT])
        cx = x + cw / 2.0

        # Restos de renglón fuera siempre (franja ancha y fina).
        if _is_ruled_line(cw, ch, cw / max(1, w_img)):
            continue

        # (A) Fragmento grande del trazo, cerca del cuerpo → conservar.
        near = abs(cx - mcx) <= max(mw, mh) * 0.9
        if area >= frag_area and near:
            keep.add(i)
            continue

        # (B) Diacrítico: compacto, tamaño en banda, centrado en X y por encima
        # de la mitad superior del cuerpo (o justo sobre él).
        compact = cw <= mw * 0.9 and ch <= mh * 0.9
        centered = abs(cx - mcx) <= mw * 0.6
        above = (y + ch) <= my + mh * 0.5
        if dia_min <= area <= dia_max and compact and centered and above:
            keep.add(i)
            continue
        # Todo lo demás (motas, flecos laterales/inferiores pequeños) → fuera.

    out = np.zeros_like(mask)
    for i in keep:
        out[labels == i] = mask[labels == i]
    return out if out.any() else mask


def _strip_ruled_line(mask: np.ndarray) -> np.ndarray:
    """Borra la línea de renglón que CRUZA la letra (pegada al trazo).

    Cuando la línea del cuaderno toca el trazo queda unida al componente
    principal, así que no se puede quitar por componentes. Aquí se aísla por
    morfología: una apertura con kernel horizontal MUY ancho (≈60% del ancho del
    recorte) deja solo segmentos horizontales largos —la línea del renglón, que
    cruza casi todo el recorte—, no las barras cortas de la letra (cruz de t/f,
    barra de e). Se resta esa línea salvo donde coincide con un trazo vertical,
    para no abrir un hueco en la letra donde el trazo la atraviesa.

    Es conservador: si la línea detectada es una fracción grande de toda la
    tinta (probable falso positivo en una letra muy horizontal), no toca nada.
    """
    if not _CV_OK or mask is None or mask.size == 0:
        return mask
    binary = (mask > 0).astype(np.uint8)
    h, w = binary.shape[:2]
    total_ink = int(binary.sum())
    if total_ink == 0 or w < 12 or h < 5:
        return mask

    # 1) Segmentos horizontales: apertura con kernel ANCHO (≈60% del ancho del
    #    recorte). El renglón cruza casi todo el recorte; las barras de la letra
    #    (cruz de t/f, barra de e) son más cortas y NO se capturan → se prefiere
    #    dejar alguna línea antes que mutilar un trazo legítimo.
    kw = max(10, int(w * 0.60))
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, hk)
    if int(horizontal.sum()) == 0:
        return mask

    # 2) Trazos verticales del glifo, protegidos (dilatados en X) para no abrir
    #    hueco donde el trazo cruza la línea.
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, int(h * 0.35))))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vk)
    vertical = cv2.dilate(vertical, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1)))

    # 3) Línea a borrar = lo horizontal que NO está sostenido por un vertical,
    #    quedándonos solo con segmentos FINOS (un renglón es delgado; una zona
    #    horizontal gruesa es cuerpo de letra).
    line_cand = (horizontal.astype(bool) & ~vertical.astype(bool)).astype(np.uint8)
    if int(line_cand.sum()) == 0:
        return mask
    thin_h = max(3, int(h * 0.18))
    n_seg, seg_lab, seg_st, _c = cv2.connectedComponentsWithStats(line_cand, connectivity=8)
    line_only = np.zeros_like(binary)
    for i in range(1, n_seg):
        if int(seg_st[i, cv2.CC_STAT_HEIGHT]) <= thin_h:
            line_only[seg_lab == i] = 1
    line_ink = int(line_only.sum())
    if line_ink == 0:
        return mask
    # Guarda anti-falso-positivo: si la "línea" es demasiada de toda la tinta,
    # probablemente sea una letra legítimamente horizontal → no tocar.
    if line_ink > total_ink * 0.45:
        return mask

    out = mask.copy()
    out[line_only.astype(bool)] = 0
    return out if out.any() else mask


def _close_small_gaps(mask: np.ndarray) -> np.ndarray:
    """Cierra huecos finos del trazo sin engordar la letra.

    Un close morfológico (dilate→erode) con kernel chico (3x3, 1 iter) une
    discontinuidades de 1-2 px del trazo (típicas tras quitar la línea de
    renglón que lo cruzaba) y, al ser close, no aumenta el grosor neto del
    trazo. Devuelve uint8 0/255 alineado con el resto de la pipeline.
    """
    if not _CV_OK or mask is None or mask.size == 0:
        return mask
    binary = (mask > 0).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k, iterations=1)
    return closed


def refine_char_region(
    line_mask: np.ndarray, x1: int, x2: int,
) -> tuple[int, int, int, int]:
    """Reduce el recorte al blob dominante + diacríticos flotantes.

    Después de que VPP da los bordes aproximados, aquí encontramos el
    componente conectado más grande (= el carácter principal) y le sumamos
    los blobs pequeños situados sobre él que corresponden a puntos de i/j,
    acentos (á é í ó ú) y tildes de ñ. También adjunta descenders (g, p, q,
    y, j).

    Devuelve (bx1, by1, bx2, by2) en coordenadas de line_mask.
    """
    h, w = line_mask.shape[:2]
    pad = 4
    rx1 = max(0, x1 - pad)
    rx2 = min(w, x2 + pad)
    region = line_mask[:, rx1:rx2]

    if not np.any(region > 0):
        return x1, 0, x2, h

    num, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        region, connectivity=8,
    )
    if num < 2:
        return x1, 0, x2, h

    blobs = []
    for i in range(1, num):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < MIN_COMP_AREA:
            continue
        bx = int(stats[i, cv2.CC_STAT_LEFT]) + rx1
        by = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        cx = float(centroids[i][0]) + rx1
        cy = float(centroids[i][1])
        blobs.append({"area": area, "x": bx, "y": by, "w": bw, "h": bh,
                      "cx": cx, "cy": cy})

    if not blobs:
        return x1, 0, x2, h

    blobs.sort(key=lambda b: b["area"], reverse=True)
    region_w = max(1, rx2 - rx1)
    # El cuerpo del carácter es el mayor blob que NO sea una franja de renglón
    # (ancha y fina). Así un resto de línea grande no se toma por "la letra" y
    # arrastra la caja. Si todos parecen línea, se cae al mayor sin más.
    main = next(
        (b for b in blobs
         if not _is_ruled_line(b["w"], b["h"], b["w"] / region_w)),
        blobs[0],
    )
    char_span = max(1, x2 - x1)

    group = [main]
    for b in blobs:
        if b is main:
            continue
        # Restos de renglón nunca se adjuntan, aunque caigan cerca.
        if _is_ruled_line(b["w"], b["h"], b["w"] / region_w):
            continue
        is_diacritic = (
            b["area"] < main["area"] * 0.40
            and b["cy"] < main["cy"]
            and abs(b["cx"] - main["cx"]) < char_span * 0.55
        )
        is_descender = (
            b["area"] < main["area"] * 0.60
            and b["cy"] > main["cy"]
            and abs(b["cx"] - main["cx"]) < char_span * 0.50
            and b["y"] > main["y"] + main["h"] * 0.5
        )
        if is_diacritic or is_descender:
            group.append(b)

    gx1 = max(0, min(b["x"] for b in group))
    gy1 = max(0, min(b["y"] for b in group))
    gx2 = min(w, max(b["x"] + b["w"] for b in group))
    gy2 = min(h, max(b["y"] + b["h"] for b in group))

    expand_max = max(6, int((x2 - x1) * 0.18))
    gx1 = max(gx1, x1 - expand_max)
    gx2 = min(gx2, x2 + expand_max)
    return gx1, gy1, gx2, gy2


def tight_crop(mask: np.ndarray, padding: int = 3) -> np.ndarray | None:
    """Recorta apretado al trazo, quitando antes ruido y cerrando huecos finos.

    Pasos (todos sobre la máscara recibida, que es un rectángulo de la máscara
    limpia y puede arrastrar motas/renglón dentro de la caja):
      1) `_clean_mask_noise`: descarta motas y restos de línea ajenos a la letra
         (componentes sueltos), conservando el cuerpo y sus diacríticos.
      2) `_strip_ruled_line`: borra la línea de renglón que CRUZA el trazo
         (pegada al cuerpo), protegiendo los trazos verticales.
      3) `_close_small_gaps`: une discontinuidades de 1-2 px sin engordar.
      4) Recorte al bounding box de lo que quedó, con `padding` de margen.

    La firma (mask, padding) y el tipo de retorno no cambian: extractor.py y la
    pipeline ensemble la llaman igual.
    """
    if mask is None or mask.size == 0:
        return None
    cleaned = _clean_mask_noise(mask)
    cleaned = _strip_ruled_line(cleaned)
    # Tras quitar el renglón pueden quedar pedazos sueltos del propio ruido que
    # ya no tocan nada → segunda pasada de limpieza por componentes.
    cleaned = _clean_mask_noise(cleaned)
    cleaned = _close_small_gaps(cleaned)
    rows = np.any(cleaned > 0, axis=1)
    cols = np.any(cleaned > 0, axis=0)
    if not rows.any() or not cols.any():
        # Si la limpieza dejó todo en cero (no debería), caer a la máscara cruda.
        rows = np.any(mask > 0, axis=1)
        cols = np.any(mask > 0, axis=0)
        if not rows.any() or not cols.any():
            return None
        cleaned = mask
    r0, r1 = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
    c0, c1 = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
    h, w = cleaned.shape[:2]
    result = cleaned[max(0, r0 - padding):min(h, r1 + 1 + padding),
                     max(0, c0 - padding):min(w, c1 + 1 + padding)]
    if result.shape[0] < 1 or result.shape[1] < 1:
        return None
    return result


def to_rgba_smooth(mask: np.ndarray) -> Image.Image:
    """RGBA con bordes anti-aliased. RGB=blanco para que sea visible sobre fondos oscuros.

    El alpha sale de la máscara normalizada a 0/255 y suavizada con un Gaussian
    chico: así el interior del trazo queda totalmente opaco (255) y solo el
    contorno recibe el degradado anti-aliasing, evitando que un trazo tenue se
    vuelva semitransparente entero.
    """
    if mask.shape[0] < 1 or mask.shape[1] < 1:
        return Image.fromarray(np.zeros((1, 1, 4), dtype=np.uint8))
    # Normalizar a binario 0/255 antes de suavizar: la entrada puede traer
    # valores intermedios (p. ej. tras un threshold imperfecto) que dejarían el
    # cuerpo del trazo a medio alpha.
    binary = np.where(mask > 0, np.uint8(255), np.uint8(0))
    alpha = cv2.GaussianBlur(binary.astype(np.float32), (3, 3), 0.8)
    # Realzar el interior: lo que estaba "encendido" queda 100% opaco; el
    # degradado vive solo en el borde generado por el blur.
    alpha = np.where(binary > 0, np.float32(255.0), alpha)
    alpha = np.clip(alpha, 0, 255).astype(np.uint8)
    h, w = mask.shape[:2]
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = alpha
    return Image.fromarray(rgba)


def assess_quality(img: Image.Image, align_score: float = 0.5) -> dict:
    """Calidad integral: cobertura + ancho de trazo + forma + alineación + borde.

    Mide la calidad REAL del trazo para que el tier no se infle. Además de la
    cobertura asimétrica (penaliza más el char vacío que el estrecho bien
    recortado: i, l, 1, f), ahora castiga los casos que delatan un mal recorte:

      • Casi vacío / pura mota: poco ink absoluto → score bajo.
      • Dos letras pegadas o resto de renglón: aspect ratio (ancho/alto) muy
        ancho → penalización progresiva.
      • Trazo fragmentado / ruidoso: si el componente conexo más grande no
        concentra la mayor parte de la tinta, la "letra" son pedazos sueltos.

    Mantiene la firma (img, align_score) y las claves de retorno.
    """
    alpha = np.array(img.getchannel("A"))
    ink = int(np.sum(alpha > 50))
    h, w = alpha.shape[:2]
    if h == 0 or w == 0:
        return {"quality_score": 0.0, "coverage": 0.0, "ok": False, "score": 0.0}

    coverage = ink / max(1, w * h)
    bbox = Image.fromarray(alpha).getbbox()
    tw = (bbox[2] - bbox[0]) if bbox else 0
    th = (bbox[3] - bbox[1]) if bbox else 0

    touches = bool(
        np.any(alpha[0] > 50) or np.any(alpha[-1] > 50)
        or np.any(alpha[:, 0] > 50) or np.any(alpha[:, -1] > 50)
    )

    binary = (alpha > 50).astype(np.uint8) * 255
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    sv = dist[dist > 0]
    if len(sv) > 4:
        sw_mean = float(np.mean(sv))
        sw_std = float(np.std(sv))
        sw_consistency = max(0.0, 1.0 - sw_std / max(1.0, sw_mean))
        sw_score = min(1.0, sw_mean / 3.0) * 0.5 + sw_consistency * 0.5
    else:
        sw_score = 0.30

    # Solidez: fracción de tinta en el componente conexo dominante. Una letra
    # real es 1-2 componentes (cuerpo + diacrítico); un recorte ruidoso o dos
    # letras pegadas reparten la tinta en muchos blobs → fracción baja.
    num, _lab, comp_stats, _c = cv2.connectedComponentsWithStats(
        (binary > 0).astype(np.uint8), connectivity=8,
    )
    if num >= 2 and ink > 0:
        largest = int(np.max(comp_stats[1:, cv2.CC_STAT_AREA]))
        largest_ratio = largest / max(1, ink)
    else:
        largest_ratio = 1.0
    # 1 componente → 1.0; reparto en pedazos → cae hacia 0.
    solidity_score = max(0.0, min(1.0, (largest_ratio - 0.30) / 0.60))

    # Aspect ratio: ancho/alto del bounding box ajustado. Las minúsculas van de
    # ~0.15 (i/l) a ~1.4 (m/w). Más ancho que ~1.7 sugiere dos letras pegadas o
    # una franja horizontal (renglón); se penaliza de forma progresiva.
    aspect = (tw / th) if th > 0 else 0.0
    if aspect <= 1.5:
        aspect_score = 1.0
    elif aspect >= 3.0:
        aspect_score = 0.0
    else:
        aspect_score = max(0.0, 1.0 - (aspect - 1.5) / 1.5)

    if coverage < 0.22:
        cov_score = max(0.0, 1.0 - (0.22 - coverage) / 0.22)
    else:
        cov_score = max(0.0, 1.0 - (coverage - 0.22) / 0.60)
    ink_score = max(0.0, min(1.0, ink / 40.0))
    size_score = (1.0 if tw >= 4 and th >= 6
                  else 0.60 if tw >= 2 and th >= 3 else 0.10)
    border_score = 0.82 if touches else 1.0
    align_c = max(0.0, min(1.0, align_score))

    # Pesos: se baja el piso fijo (0.10→0.04) y se reparte peso a forma
    # (solidez + aspect) para que un glifo malo no llegue a Gold por inercia.
    qs = max(0.0, min(1.0,
        0.04
        + cov_score      * 0.20
        + ink_score      * 0.18
        + size_score     * 0.15
        + sw_score       * 0.14
        + solidity_score * 0.12
        + aspect_score   * 0.10
        + border_score   * 0.04
        + align_c        * 0.03
    ))
    # Penalización multiplicativa por forma, para que el tier refleje calidad
    # REAL y no se infle:
    #  • Solidez como factor SUAVE en todo el rango: un glifo con tinta detenida
    #    fuera del cuerpo (línea pegada, fragmento) baja proporcionalmente — un
    #    contaminado deja de ser Gold sin castigar al glifo limpio (ratio≈1).
    #    Calibrado para que ~25-30% de tinta dispersa baste para caer de Gold.
    #  • Aspect extremo (dos letras / franja) recorta fuerte.
    qs *= 0.47 + 0.53 * max(0.0, min(1.0, largest_ratio))
    if aspect_score < 0.6:
        qs *= 0.50 + 0.50 * aspect_score
    qs = float(max(0.0, min(1.0, qs)))

    ok = (ink >= 10 and coverage >= 0.004 and tw >= 2
          and th >= 3 and qs >= QUALITY_MIN)
    return {
        "ink_pixels": ink, "coverage": float(coverage),
        "tight_w": tw, "tight_h": th,
        "touches_border": touches, "sw_score": float(sw_score),
        "solidity": float(largest_ratio), "aspect": float(aspect),
        "quality_score": float(qs), "score": float(qs), "ok": bool(ok),
    }

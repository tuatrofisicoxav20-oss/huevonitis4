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


def refine_char_region(
    line_mask: "np.ndarray", x1: int, x2: int,
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
    main = blobs[0]
    char_span = max(1, x2 - x1)

    group = [main]
    for b in blobs[1:]:
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


def tight_crop(mask: "np.ndarray", padding: int = 3) -> "np.ndarray | None":
    rows = np.any(mask > 0, axis=1)
    cols = np.any(mask > 0, axis=0)
    if not rows.any() or not cols.any():
        return None
    r0, r1 = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
    c0, c1 = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
    h, w = mask.shape[:2]
    result = mask[max(0, r0 - padding):min(h, r1 + 1 + padding),
                  max(0, c0 - padding):min(w, c1 + 1 + padding)]
    if result.shape[0] < 1 or result.shape[1] < 1:
        return None
    return result


def to_rgba_smooth(mask: "np.ndarray") -> "Image.Image":
    """RGBA con bordes anti-aliased. RGB=blanco para que sea visible sobre fondos oscuros."""
    if mask.shape[0] < 1 or mask.shape[1] < 1:
        return Image.fromarray(np.zeros((1, 1, 4), dtype=np.uint8))
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (3, 3), 0.9)
    alpha = np.clip(alpha, 0, 255).astype(np.uint8)
    h, w = mask.shape[:2]
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = alpha
    return Image.fromarray(rgba)


def assess_quality(img: "Image.Image", align_score: float = 0.5) -> dict:
    """Calidad integral: cobertura + ancho de trazo + alineación + borde + ink absoluto.

    Fórmula asimétrica de cobertura: penaliza más el char vacío que el char
    estrecho con buen recorte (i, l, 1, f). Esencial para no descartar
    letras estrechas legítimas.
    """
    alpha = np.array(img.getchannel("A"))
    ink = int(np.sum(alpha > 50))
    h, w = alpha.shape[:2]
    if h == 0 or w == 0:
        return {"quality_score": 0.0, "coverage": 0.0, "ok": False, "score": 0.0}

    coverage = ink / max(1, w * h)
    bbox = Image.fromarray(alpha, mode="L").getbbox()
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

    if coverage < 0.22:
        cov_score = max(0.0, 1.0 - (0.22 - coverage) / 0.22)
    else:
        cov_score = max(0.0, 1.0 - (coverage - 0.22) / 0.60)
    ink_score = max(0.0, min(1.0, ink / 40.0))
    size_score = (1.0 if tw >= 4 and th >= 6
                  else 0.60 if tw >= 2 and th >= 3 else 0.10)
    border_score = 0.82 if touches else 1.0
    align_c = max(0.0, min(1.0, align_score))

    qs = max(0.0, min(1.0,
        0.10
        + cov_score    * 0.22
        + ink_score    * 0.22
        + size_score   * 0.18
        + sw_score     * 0.16
        + border_score * 0.07
        + align_c      * 0.05
    ))
    ok = (ink >= 10 and coverage >= 0.004 and tw >= 2
          and th >= 3 and qs >= QUALITY_MIN)
    return {
        "ink_pixels": ink, "coverage": float(coverage),
        "tight_w": tw, "tight_h": th,
        "touches_border": touches, "sw_score": float(sw_score),
        "quality_score": float(qs), "score": float(qs), "ok": bool(ok),
    }

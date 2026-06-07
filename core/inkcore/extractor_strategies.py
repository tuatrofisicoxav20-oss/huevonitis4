"""Benchmark de las 5 estrategias de alineación.

Útil desde la UI (botón "Comparar estrategias") y para tuning offline.
Cada estrategia produce sus fronteras y se puntúan los glifos resultantes
con la misma fórmula `assess_quality` que la pipeline de producción.
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
    from PIL import Image  # noqa: F401 (chequeo de disponibilidad)
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def benchmark_all(
    band_img,
    band_binary,
    x_min: int,
    x_max: int,
    n: int,
    chars: list[str],
    line_mask,
) -> dict:
    """Ejecuta las 5 estrategias + la combinación de producción y puntúa cada una."""
    if not _CV_OK or not _PIL_OK:
        return {}

    from core.inkcore.extractor_alignment import (
        align_cc_first,
        align_dp_energy,
        align_hybrid_v2,
        align_inkflow,
        align_uniform,
        align_vpp_only,
    )
    from core.inkcore.extractor_glyph_ops import (
        assess_quality,
        tight_crop,
        to_rgba_smooth,
    )
    from core.inkcore.extractor_ocr_hints import tesseract_boundaries

    h, w = band_binary.shape[:2]
    vpp = np.sum(band_binary > 0, axis=0).astype(np.float32)

    def _score_bounds(bounds: list[int]) -> dict:
        scores: list[float] = []
        for i in range(len(bounds) - 1):
            x1 = max(0, bounds[i])
            x2 = min(w, bounds[i + 1])
            if x2 <= x1:
                continue
            crop = band_binary[:, x1:x2]
            crop_tight = tight_crop(crop, 3)
            if crop_tight is None:
                continue
            pil_img = to_rgba_smooth(crop_tight)
            ink = float(np.sum(band_binary[:, x1:x2] > 0))
            area = max(1, h * (x2 - x1))
            cov = ink / area
            align_score = min(1.0, max(0.1, cov / 0.18))
            q = assess_quality(pil_img, align_score)
            scores.append(q["quality_score"])
        if not scores:
            return {"avg_quality": 0.0, "min_quality": 0.0,
                    "max_quality": 0.0, "glyph_count": 0}
        return {
            "avg_quality": float(np.mean(scores)),
            "min_quality": float(np.min(scores)),
            "max_quality": float(np.max(scores)),
            "glyph_count": len(scores),
        }

    def _safe(name: str, fn):
        try:
            bounds = fn()
            r = _score_bounds(bounds)
            r["boundaries"] = bounds
            return r
        except Exception as exc:
            return {"error": str(exc), "avg_quality": 0.0,
                    "min_quality": 0.0, "max_quality": 0.0,
                    "glyph_count": 0}

    results: dict = {}

    # Estrategia de producción: InkFlow + VPP snap + Tesseract anchor
    def _prod_strategy() -> list[int]:
        prod_bounds = align_inkflow(vpp, x_min, x_max, chars)
        char_w_avg = (x_max - x_min) / max(1, n)
        ks = max(3, int(w / max(1, n) * 0.12))
        ks = ks if ks % 2 == 1 else ks + 1
        vpp_s = cv2.GaussianBlur(vpp.reshape(1, -1), (1, ks), 0).flatten()
        vpp_max = float(np.max(vpp_s[x_min:x_max])) if x_max > x_min else 1.0
        gap_thr = vpp_max * 0.12
        sw = max(2, int(char_w_avg * 0.30))
        min_cw = max(1, int(char_w_avg * 0.20))
        refined: list[int] = [prod_bounds[0]]
        for i in range(1, n):
            eb = prod_bounds[i]
            prev = refined[-1]
            lo = max(prev + min_cw, eb - sw)
            hi = min(w, eb + sw + 1)
            if lo < hi:
                seg = vpp_s[lo:hi]
                min_i = int(np.argmin(seg))
                min_v = float(seg[min_i])
                best_x = max(prev + 1, lo + min_i) if min_v < gap_thr else max(prev + 1, eb)
            else:
                best_x = max(prev + 1, eb)
            refined.append(best_x)
        refined.append(prod_bounds[-1])
        for i in range(1, len(refined)):
            if refined[i] <= refined[i - 1]:
                refined[i] = refined[i - 1] + 1
        tess = tesseract_boundaries(line_mask)
        snap_r = max(3, int(char_w_avg * 0.22))
        if tess:
            final: list[int] = [refined[0]]
            prev_p = refined[0]
            for i in range(1, n):
                eb = refined[i]
                nearby = [tb for tb in tess
                          if abs(tb - eb) <= snap_r
                          and prev_p + min_cw < tb < w
                          and 0 <= tb < len(vpp_s)
                          and float(vpp_s[tb]) < vpp_max * 0.35]
                if nearby:
                    eb = max(prev_p + 1, min(nearby, key=lambda tb: abs(tb - eb)))
                final.append(eb)
                prev_p = eb
            final.append(refined[-1])
            return final
        return refined

    results["production (inkflow+vpp+tess)"] = _safe("prod", _prod_strategy)
    results["A: vpp_only"] = _safe("A", lambda: align_vpp_only(vpp, x_min, x_max, n))
    results["B: uniform"] = _safe("B", lambda: align_uniform(x_min, x_max, n))

    if n <= 20:
        results["C: dp_energy"] = _safe("C", lambda: align_dp_energy(vpp, x_min, x_max, n))
    else:
        results["C: dp_energy"] = {
            "avg_quality": 0.0, "min_quality": 0.0,
            "max_quality": 0.0, "glyph_count": 0,
            "note": f"skipped (n={n} > 20)",
        }

    results["D: cc_first"] = _safe("D", lambda: align_cc_first(band_binary, x_min, x_max, n))
    results["E: hybrid_v2"] = _safe("E", lambda: align_hybrid_v2(vpp, band_binary, x_min, x_max, n, chars))

    return results

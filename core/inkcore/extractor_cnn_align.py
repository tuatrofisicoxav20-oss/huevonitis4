"""Alineación de renglón guiada por el clasificador de caracteres (juez de cortes).

El alineador posicional reparte la línea por ancho esperado; con letra ligada los
cortes caen desplazados y la forma deja de coincidir con la letra que la posición
asignó (se pierde por validación). Aquí aplicamos la técnica recomendada en la
literatura para caracteres que se tocan: **over-segmentación + selección guiada
por reconocimiento**.

  1. Proponemos muchos cortes candidatos (valles del perfil vertical + bordes).
  2. Enumeramos los segmentos de ancho plausible entre cortes y los clasificamos
     en UN lote con el CNN (core.inkcore.ai.char_cnn).
  3. Por programación dinámica elegimos la partición en N segmentos (uno por letra
     del texto conocido) que MAXIMIZA Σ log P(letra_i | segmento_i) menos una
     penalización suave de ancho. El texto de referencia da la secuencia de
     letras; el CNN sólo juzga qué corte la hace más reconocible.

Devuelve n+1 fronteras X, o None si no hay clasificador / la línea es trivial /
no se encontró partición. El caller (AlignmentMixin) cae entonces a su pipeline
clásico. La ñ no existe en EMNIST: su costo usa cobertura de tinta como proxy.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _OK = True
except ImportError:  # pragma: no cover
    _OK = False

from core.inkcore.ai.char_cnn import char_to_label  # noqa: E402


def _candidate_cuts(vpp_s, x_min: int, x_max: int, n: int, char_w_avg: float) -> list[int]:
    """Posiciones X candidatas a frontera: bordes + valles + relleno uniforme."""
    vmax = max(1.0, float(vpp_s[x_min:x_max].max()))
    cuts = {x_min, x_max}
    thr = vmax * 0.60
    for x in range(x_min + 1, x_max - 1):
        if vpp_s[x] <= vpp_s[x - 1] and vpp_s[x] <= vpp_s[x + 1] and vpp_s[x] < thr:
            cuts.add(x)
    # densidad mínima: asegurar resolución aunque haya pocos valles (letra ligada)
    target = max(n * 2, 8)
    if len(cuts) < target:
        for t in range(target + 1):
            cuts.add(int(x_min + (x_max - x_min) * t / target))
    ordered = sorted(cuts)
    # techo de candidatos para acotar el costo (subsample preservando extremos)
    max_c = max(10, n * 4)
    if len(ordered) > max_c:
        idx = np.linspace(0, len(ordered) - 1, max_c).astype(int)
        ordered = sorted({ordered[i] for i in idx})
    return ordered


def align_by_classifier(
    line_mask: np.ndarray,
    chars: list[str],
    classifier,
    char_w_avg: float,
    wf_fn,
    *,
    w_width: float = 0.35,
    eps: float = 1e-3,
) -> list[int] | None:
    """n+1 fronteras por DP usando el CNN como juez, o None si no aplica."""
    if not _OK or classifier is None or not getattr(classifier, "available", False):
        return None
    n = len(chars)
    if n < 2 or line_mask is None or line_mask.size == 0:
        return None
    _h, _w = line_mask.shape[:2]
    vpp = (line_mask > 0).sum(0).astype(np.float32)
    ink = np.where(vpp > 0)[0]
    if len(ink) == 0:
        return None
    x_min, x_max = int(ink[0]), int(ink[-1]) + 1
    if x_max - x_min < n:
        return None

    ks = max(3, int(char_w_avg * 0.12))
    ks = ks if ks % 2 == 1 else ks + 1
    vpp_s = cv2.GaussianBlur(vpp.reshape(1, -1), (1, ks), 0).flatten()
    cuts = _candidate_cuts(vpp_s, x_min, x_max, n, char_w_avg)
    M = len(cuts)
    if n + 1 > M:
        return None

    # Enumerar segmentos de ancho plausible y clasificarlos en lote.
    min_w = max(2, int(0.22 * char_w_avg))
    max_w = max(min_w + 1, int(2.6 * char_w_avg))
    seg_pairs: list[tuple[int, int]] = []
    seg_masks: list[np.ndarray] = []
    for k in range(M):
        for j in range(k + 1, M):
            sw = cuts[j] - cuts[k]
            if sw < min_w or sw > max_w:
                continue
            seg_pairs.append((k, j))
            seg_masks.append(line_mask[:, cuts[k]:cuts[j]])
    if not seg_pairs:
        return None
    probs = classifier.classify_batch(seg_masks)
    if probs is None:
        return None
    seg_index = {kj: i for i, kj in enumerate(seg_pairs)}

    INF = float("inf")
    dp = [[INF] * M for _ in range(n + 1)]
    bk = [[-1] * M for _ in range(n + 1)]
    dp[0][0] = 0.0  # el primer carácter arranca en x_min (cuts[0])

    for i in range(1, n + 1):
        ch = chars[i - 1]
        label = char_to_label(ch)
        ew = max(1.0, wf_fn(ch) * char_w_avg)
        for j in range(1, M):
            best, best_k = INF, -1
            for k in range(j):
                if dp[i - 1][k] == INF:
                    continue
                si = seg_index.get((k, j))
                if si is None:
                    continue
                sw = cuts[j] - cuts[k]
                wp = abs(sw - ew) / ew
                if label is not None:
                    p = float(probs[si][label])
                    cost = -math.log(p + eps) + w_width * wp
                else:
                    seg = seg_masks[si]
                    cov = float((seg > 0).sum()) / max(1, seg.shape[0] * max(1, seg.shape[1]))
                    cost = (1.0 - min(1.0, cov / 0.18)) + w_width * wp + 0.5
                v = dp[i - 1][k] + cost
                if v < best:
                    best, best_k = v, k
            dp[i][j] = best
            bk[i][j] = best_k

    # El último carácter debería terminar en x_max (cuts[-1]); si no hay camino,
    # aceptar el mejor final disponible.
    j_end = M - 1
    if dp[n][j_end] == INF:
        cand = [j for j in range(1, M) if dp[n][j] < INF]
        if not cand:
            return None
        j_end = min(cand, key=lambda j: dp[n][j])

    bounds: list[int] = []
    j = j_end
    for i in range(n, 0, -1):
        bounds.append(cuts[j])
        k = bk[i][j]
        if k < 0:
            return None
        j = k
    bounds.append(cuts[j])
    bounds.reverse()
    if len(bounds) != n + 1:
        return None
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 1
    logger.info("cnn-align '%s': %d letras, %d cortes candidatos, %d segmentos",
                "".join(chars)[:30], n, M, len(seg_pairs))
    return bounds

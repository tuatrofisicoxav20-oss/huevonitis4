"""Estrategias de alineación básicas (familia simple).

Funciones puras: factor de ancho por carácter, masa de tinta acumulada,
VPP puro, división uniforme y pre-alineación por palabras.

Estrategias:
  - wf            : factor de ancho esperado por carácter
  - inkflow       : masa de tinta acumulada calibrada por `wf(char)`
  - vpp_only      : VPP puro con valles por prominencia
  - uniform       : división de ancho igual (línea base)
  - find_word_gaps : pre-alineación por palabras
"""
from __future__ import annotations

try:
    import cv2
    import numpy as np
    _CV_OK = True
except ImportError:
    _CV_OK = False


# Mínimo área de CC para considerar "no ruido"; mismo valor que extractor.py
MIN_COMP_AREA = 10


def wf(ch: str) -> float:
    """Factor de ancho esperado por carácter (escritura manual española)."""
    if ch in ".,;:!¡|`'\"":
        return 0.28
    if ch in "iltI1íì":
        return 0.40
    if ch in "jr":
        return 0.50
    if ch in "fFtT":
        return 0.60
    if ch in "scCeéèêëS":
        return 0.63
    if ch in "nuvbpkxyzñhúùü":
        return 0.72
    if ch in "adgqáàâ":
        return 0.80
    if ch in "oóòôöO":
        return 0.85
    if ch in "mwMW":
        return 1.30
    if ch.isupper():
        return 0.92
    if ch.isdigit():
        return 0.73
    return 0.78


def align_inkflow(vpp, x_min: int, x_max: int, chars: list[str]) -> list[int]:
    """Fronteras por masa de tinta acumulada (auto-calibradas por wf)."""
    n = len(chars)
    span = vpp[x_min:x_max].astype(np.float64)
    total_ink = max(1e-6, float(np.sum(span)))
    cumink = np.cumsum(span)

    total_wf = max(0.01, sum(wf(c) for c in chars))
    min_cw = max(1, int((x_max - x_min) / n * 0.15))

    bounds: list[int] = [x_min]
    cum_wf = 0.0
    for i, ch in enumerate(chars[:-1]):
        cum_wf += wf(ch)
        target = cum_wf / total_wf * total_ink
        prev = bounds[-1]

        lo_idx = max(0, prev + min_cw - x_min)
        if lo_idx >= len(cumink):
            remaining_chars = chars[i:]
            remaining_wf = max(0.01, sum(wf(c) for c in remaining_chars))
            space_left = max(0, x_max - prev)
            frac = wf(ch) / remaining_wf
            step = max(min_cw, int(space_left * frac))
            bounds.append(min(prev + step, x_max - (n - 1 - i)))
            continue
        idx = int(np.searchsorted(cumink[lo_idx:], target)) + lo_idx
        idx = min(idx, len(span) - max(1, n - 1 - i))
        x = x_min + idx
        x = max(prev + min_cw, min(x, x_max - (n - 1 - i)))
        bounds.append(x)

    bounds.append(x_max)
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 1
    return bounds


def align_vpp_only(vpp, x_min: int, x_max: int, n: int) -> list[int]:
    """VPP puro con selección por prominencia."""
    if n <= 1:
        return [x_min, x_max]

    span = vpp[x_min:x_max].astype(np.float64)
    if len(span) == 0:
        return list(np.linspace(x_min, x_max, n + 1, dtype=int))

    ks = max(3, int((x_max - x_min) / max(1, n) * 0.15))
    ks = ks if ks % 2 == 1 else ks + 1
    smoothed = cv2.GaussianBlur(
        span.astype(np.float32).reshape(1, -1), (1, ks), 0,
    ).flatten().astype(np.float64)

    vmax = float(np.max(smoothed)) if len(smoothed) > 0 else 1.0
    vmax = max(vmax, 1.0)

    valleys: list[tuple[float, int]] = []
    L = len(smoothed)
    for i in range(1, L - 1):
        if smoothed[i] <= smoothed[i - 1] and smoothed[i] <= smoothed[i + 1]:
            left_peak = float(np.max(smoothed[:i])) if i > 0 else smoothed[i]
            right_peak = float(np.max(smoothed[i + 1:])) if i < L - 1 else smoothed[i]
            depth = min(left_peak - smoothed[i], right_peak - smoothed[i])
            prominence = depth / vmax
            if prominence > 0.05:
                valleys.append((prominence, x_min + i))

    if not valleys:
        return list(np.linspace(x_min, x_max, n + 1, dtype=int))

    valleys.sort(key=lambda v: -v[0])
    chosen = sorted([v[1] for v in valleys[:n - 1]])

    bounds = [x_min, *chosen, x_max]
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 1
    return bounds


def align_uniform(x_min: int, x_max: int, n: int) -> list[int]:
    """División uniforme de ancho igual."""
    if n <= 0:
        return [x_min, x_max]
    return [int(x_min + (x_max - x_min) * i / n) for i in range(n + 1)]


def find_word_gaps(vpp, x_min: int, x_max: int, words: list[str]) -> list[int]:
    """Devuelve len(words)+1 posiciones [x_min, gap1, ..., x_max].

    Retorna [] si no hay suficientes gaps claros para separar las palabras
    (señal de "usar segmentación completa").
    """
    n_words = len(words)
    if n_words <= 1:
        return [x_min, x_max]

    span_len = x_max - x_min
    if span_len < 4:
        return []

    n_chars = max(1, sum(len(w) for w in words))
    char_w_est = span_len / n_chars

    ks = max(3, int(char_w_est * 0.12))
    ks = ks if ks % 2 == 1 else ks + 1
    vpp_s = cv2.GaussianBlur(
        vpp.astype(np.float32).reshape(1, -1), (1, ks), 0,
    ).flatten()

    vpp_max = float(np.max(vpp_s[x_min:x_max])) if x_max > x_min else 1.0
    gap_thr = vpp_max * 0.15
    min_gap_w = max(2, int(char_w_est * 0.35))

    in_gap = False
    gap_zones: list[tuple[int, int]] = []
    gs = x_min
    for x in range(x_min, x_max):
        below = float(vpp_s[x]) <= gap_thr
        if below and not in_gap:
            gs = x
            in_gap = True
        elif not below and in_gap:
            if x - gs >= min_gap_w:
                gap_zones.append((gs, x))
            in_gap = False
    if in_gap and x_max - gs >= min_gap_w:
        gap_zones.append((gs, x_max))

    if len(gap_zones) < n_words - 1:
        return []

    gap_centers = [int((g[0] + g[1]) / 2) for g in gap_zones]

    word_lens = [max(1, len(w)) for w in words]
    total_chars = sum(word_lens)
    expected: list[int] = []
    cum = 0
    for wl in word_lens[:-1]:
        cum += wl
        expected.append(int(x_min + span_len * cum / total_chars))

    chosen: list[int] = []
    used: set[int] = set()
    for ex in expected:
        candidates = [i for i in range(len(gap_centers)) if i not in used]
        if not candidates:
            return []
        best_i = min(candidates, key=lambda i: abs(gap_centers[i] - ex))
        used.add(best_i)
        chosen.append(gap_centers[best_i])

    bounds = [x_min, *sorted(chosen), x_max]
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 1
    return bounds

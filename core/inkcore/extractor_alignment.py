"""Estrategias de alineación carácter por carácter.

Cada función recibe el VPP (perfil vertical de tinta) o la máscara binaria
de la línea y devuelve `n+1` posiciones X (incluyen `x_min` y `x_max`).

Estrategias:
  - inkflow     : masa de tinta acumulada calibrada por `wf(char)`
  - vpp_only    : VPP puro con valles por prominencia
  - uniform     : división de ancho igual (línea base)
  - dp_energy   : programación dinámica O(L·k)
  - cc_first    : componentes conectados → grupos
  - hybrid_v2   : inkflow + columna mínima + verificación CC (primario)
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


def align_dp_energy(vpp, x_min: int, x_max: int, n: int) -> list[int]:
    """Minimización de energía por programación dinámica O(L·k)."""
    if n <= 1:
        return [x_min, x_max]

    span = vpp[x_min:x_max].astype(np.float64)
    L = len(span)
    if L == 0:
        return list(np.linspace(x_min, x_max, n + 1, dtype=int))

    ks = max(3, int(L / max(1, n) * 0.15))
    ks = ks if ks % 2 == 1 else ks + 1
    cost = cv2.GaussianBlur(
        span.astype(np.float32).reshape(1, -1), (1, ks), 0,
    ).flatten().astype(np.float64)

    min_gap = max(1, int(L / n * 0.15))
    num_cuts = n - 1
    INF = float("inf")

    dp = np.full(L, INF, dtype=np.float64)
    ptr = np.full((num_cuts, L), -1, dtype=np.int32)

    i_lo = min_gap
    i_hi = L - (num_cuts - 1) * min_gap
    for i in range(i_lo, i_hi):
        dp[i] = cost[i]

    for k in range(2, num_cuts + 1):
        new_dp = np.full(L, INF, dtype=np.float64)
        run_min_val = INF
        run_min_pos = -1
        j_cursor = (k - 1) * min_gap

        i_lo = k * min_gap
        i_hi = L - (num_cuts - k) * min_gap
        for i in range(i_lo, i_hi):
            j_max = i - min_gap
            while j_cursor <= j_max:
                if dp[j_cursor] < run_min_val:
                    run_min_val = dp[j_cursor]
                    run_min_pos = j_cursor
                j_cursor += 1
            if run_min_pos >= 0 and run_min_val < INF:
                new_val = run_min_val + cost[i]
                if new_val < new_dp[i]:
                    new_dp[i] = new_val
                    ptr[k - 1, i] = run_min_pos
        dp = new_dp

    best_last = -1
    best_cost = INF
    for i in range(num_cuts * min_gap, L):
        if dp[i] < best_cost:
            best_cost = dp[i]
            best_last = i

    if best_last < 0:
        return list(np.linspace(x_min, x_max, n + 1, dtype=int))

    cut_positions: list[int] = [best_last]
    pos = best_last
    for k in range(num_cuts - 1, 0, -1):
        prev = int(ptr[k, pos])
        if prev < 0:
            return list(np.linspace(x_min, x_max, n + 1, dtype=int))
        cut_positions.append(prev)
        pos = prev
    cut_positions = sorted(cut_positions)

    while len(cut_positions) < num_cuts:
        cut_positions.append(cut_positions[-1] + min_gap if cut_positions else min_gap)
    cut_positions = cut_positions[:num_cuts]

    bounds = [x_min] + [x_min + p for p in sorted(cut_positions)] + [x_max]
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 1
    return bounds


def align_cc_first(binary_band, x_min: int, x_max: int, n: int) -> list[int]:
    """Componentes conectados primero: agrupa y elige n grupos."""
    if n <= 1:
        return [x_min, x_max]

    num, _, stats, centroids = cv2.connectedComponentsWithStats(
        binary_band, connectivity=8,
    )

    blobs = []
    for i in range(1, num):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < MIN_COMP_AREA:
            continue
        bx = int(stats[i, cv2.CC_STAT_LEFT])
        bw_ = int(stats[i, cv2.CC_STAT_WIDTH])
        cx = float(centroids[i][0])
        blobs.append({"area": area, "x1": bx, "x2": bx + bw_, "cx": cx})

    if not blobs:
        return list(np.linspace(x_min, x_max, n + 1, dtype=int))

    blobs.sort(key=lambda b: b["x1"])

    merge_gap = 3
    groups: list[dict] = []
    for b in blobs:
        if groups and b["x1"] <= groups[-1]["x2"] + merge_gap:
            g = groups[-1]
            g["x2"] = max(g["x2"], b["x2"])
            g["area"] += b["area"]
            g["cx"] = (g["cx"] + b["cx"]) / 2
        else:
            groups.append({"x1": b["x1"], "x2": b["x2"],
                           "area": b["area"], "cx": b["cx"]})

    if not groups:
        return list(np.linspace(x_min, x_max, n + 1, dtype=int))

    # Fusionar grupos más próximos hasta exactamente n grupos.
    while len(groups) > n:
        min_gap_val = float("inf")
        min_gap_idx = 0
        for gi in range(len(groups) - 1):
            gap = groups[gi + 1]["x1"] - groups[gi]["x2"]
            if gap < min_gap_val:
                min_gap_val = gap
                min_gap_idx = gi
        g1, g2 = groups[min_gap_idx], groups[min_gap_idx + 1]
        merged = {
            "x1": g1["x1"], "x2": g2["x2"],
            "area": g1["area"] + g2["area"],
            "cx": (g1["cx"] * g1["area"] + g2["cx"] * g2["area"])
                   / max(1, g1["area"] + g2["area"]),
        }
        groups = [*groups[:min_gap_idx], merged, *groups[min_gap_idx + 2:]]

    top_n = groups

    bounds: list[int] = [x_min]
    for i in range(len(top_n) - 1):
        g1 = top_n[i]
        g2 = top_n[i + 1]
        gap_center = (g1["x2"] + g2["x1"]) // 2
        bounds.append(max(bounds[-1] + 1, gap_center))
    bounds.append(x_max)

    while len(bounds) < n + 1:
        bounds.append(bounds[-1] + 1)
    bounds = bounds[:n + 1]

    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 1
    return bounds


def align_hybrid_v2(vpp, binary_band, x_min: int, x_max: int, n: int, chars: list[str]) -> list[int]:
    """Híbrido: InkFlow → columna mínima → verificación CC."""
    if n <= 1:
        return [x_min, x_max]

    base_bounds = align_inkflow(vpp, x_min, x_max, chars)

    h, w_full = binary_band.shape[:2]
    char_w_avg = max(1, (x_max - x_min) / n)
    search_half = int(char_w_avg * 0.40)

    _, labels, _, _ = cv2.connectedComponentsWithStats(binary_band, connectivity=8)

    ks = max(3, int(char_w_avg * 0.12))
    ks = ks if ks % 2 == 1 else ks + 1
    vpp_s = cv2.GaussianBlur(
        vpp.astype(np.float32).reshape(1, -1), (1, ks), 0,
    ).flatten()

    min_cw = max(1, int(char_w_avg * 0.20))
    refined: list[int] = [base_bounds[0]]

    for i in range(1, n):
        eb = base_bounds[i]
        prev = refined[-1]
        lo = max(prev + min_cw, eb - search_half)
        hi = min(w_full, eb + search_half + 1)

        if lo < hi:
            seg = vpp_s[lo:hi]
            best_x = lo + int(np.argmin(seg))
            best_x = max(prev + 1, best_x)
        else:
            best_x = max(prev + 1, eb)

        # Verifica si el corte parte un CC; desplaza ±5 px buscando gap real
        shift_range = 5
        if 0 <= best_x < w_full:
            col_labels = set(int(labels[r, best_x]) for r in range(h)
                             if labels[r, best_x] > 0)
            if col_labels:
                found_gap = False
                for delta in range(1, shift_range + 1):
                    for candidate in [best_x - delta, best_x + delta]:
                        if candidate <= prev or candidate >= w_full:
                            continue
                        cand_labels = set(
                            int(labels[r, candidate]) for r in range(h)
                            if labels[r, candidate] > 0
                        )
                        if not cand_labels:
                            best_x = max(prev + 1, candidate)
                            found_gap = True
                            break
                    if found_gap:
                        break

        refined.append(max(prev + 1, best_x))

    refined.append(base_bounds[-1])
    for i in range(1, len(refined)):
        if refined[i] <= refined[i - 1]:
            refined[i] = refined[i - 1] + 1
    return refined


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

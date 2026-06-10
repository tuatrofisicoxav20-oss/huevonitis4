"""Métricas de realismo sobre una imagen de texto manuscrito (Fase R0).

Dado un PNG de texto (página real escaneada o render sintético) devuelve un
dict JSON-serializable con las métricas que distinguen escritura humana de
texto "de sello": variación de alturas, espaciado, perfil de línea base,
slant y repetición perceptual. Son las distribuciones de la Parte 1.3 de la
auditoría: si las del sintético se encajan dentro de las reales, vamos bien.

Sólo PIL + NumPy + stdlib (regla dura del proyecto): los componentes conexos
se etiquetan con un union-find por runs de fila en NumPy puro, sin cv2, para
que el harness corra en cualquier entorno donde corran los tests del render.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

# Distancia de Hamming reutilizada del banco (misma semántica que el dedup).
from core.inkcore.bank_hashing import _hamming

# Umbral default de "gemelos" perceptuales: a ≤6/64 bits dos letras son el
# mismo sello con micro-ruido. El warp de R5 debe empujar los pares por encima.
DUP_HAMMING_THRESHOLD = 6


# ── Binarización ─────────────────────────────────────────────────────────────

def _otsu_threshold(gray: np.ndarray) -> int:
    """Umbral de Otsu sobre el histograma de luminancia (sin cv2)."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 127
    p = hist / total
    omega = np.cumsum(p)                      # prob. acumulada de la clase baja
    mu = np.cumsum(p * np.arange(256))        # media acumulada
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom == 0] = np.nan
    sigma_b = (mu_t * omega - mu) ** 2 / denom
    return int(np.nanargmax(sigma_b))


def _ink_mask(img: Image.Image) -> np.ndarray:
    """Máscara booleana de tinta (True=tinta) desde cualquier modo de imagen.

    RGBA con alpha informativo (render_transparent): la forma ES el alpha.
    Lo demás se compone sobre blanco y se umbraliza por Otsu: la tinta es lo
    oscuro. Funciona igual para un escaneo real que para un render.
    """
    if img.mode == "RGBA":
        a = np.asarray(img.getchannel("A"))
        if int(a.max()) - int(a.min()) > 12:   # alpha informativo, no plano
            return a > 96
        img = img.convert("RGB")
    gray = np.asarray(img.convert("L"))
    thr = _otsu_threshold(gray)
    return gray < thr


# ── Componentes conexos (NumPy puro) ────────────────────────────────────────

def _row_runs(row: np.ndarray) -> list[tuple[int, int]]:
    """Runs [start, end) de True en una fila booleana."""
    if not row.any():
        return []
    d = np.diff(row.astype(np.int8))
    starts = np.flatnonzero(d == 1) + 1
    ends = np.flatnonzero(d == -1) + 1
    if row[0]:
        starts = np.r_[0, starts]
    if row[-1]:
        ends = np.r_[ends, len(row)]
    return list(zip(starts.tolist(), ends.tolist()))


def connected_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Cajas (x0, y0, x1, y1, área_px) de los componentes conexos de `mask`.

    Union-find sobre runs por fila (8-conectividad). Coordenadas exclusivas en
    x1/y1, como un slice. Suficientemente rápido para una página carta: el
    costo va por nº de runs (~nº de trazos), no por píxel.
    """
    parent: list[int] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    prev: list[tuple[int, int, int]] = []          # (start, end, label) fila anterior
    runs_all: list[tuple[int, int, int, int]] = []  # (y, start, end, label)
    for y in range(mask.shape[0]):
        cur: list[tuple[int, int, int]] = []
        for s, e in _row_runs(mask[y]):
            label = -1
            # 8-conectividad: el ±1 admite contacto diagonal entre runs.
            for ps, pe, pl in prev:
                if s < pe + 1 and ps < e + 1:
                    if label == -1:
                        label = pl
                    else:
                        union(label, pl)
            if label == -1:
                label = len(parent)
                parent.append(label)
            cur.append((s, e, label))
            runs_all.append((y, s, e, label))
        prev = cur

    boxes: dict[int, list[int]] = {}
    for y, s, e, label in runs_all:
        root = find(label)
        b = boxes.get(root)
        if b is None:
            boxes[root] = [s, y, e, y + 1, e - s]
        else:
            b[0] = min(b[0], s)
            b[1] = min(b[1], y)
            b[2] = max(b[2], e)
            b[3] = max(b[3], y + 1)
            b[4] += e - s
    return [tuple(b) for b in boxes.values()]


# ── Agrupación en líneas y fusión de diacríticos ────────────────────────────

def _filter_boxes(boxes: list, w: int, h: int) -> list:
    """Quita motas y rayas del papel (renglones impresos, bordes del escaneo)."""
    min_area = max(4.0, w * h * 2e-6)
    out = []
    for x0, y0, x1, y1, area in boxes:
        bw, bh = x1 - x0, y1 - y0
        if area < min_area:
            continue
        # Renglones/márgenes impresos: componentes que cruzan media página.
        if bw > 0.6 * w or bh > 0.6 * h:
            continue
        out.append((x0, y0, x1, y1, area))
    return out


def group_lines(boxes: list, mask: np.ndarray) -> list[list]:
    """Agrupa cajas en líneas de texto por el perfil de proyección horizontal.

    Los centros verticales de las letras de un mismo renglón varían demasiado
    (ascendentes vs x-height) para agrupar por cercanía. En su lugar: los
    CORES de los renglones son los máximos del perfil suavizado de tinta por
    fila (el cuerpo del renglón concentra la tinta), y la frontera entre dos
    renglones es el VALLE del perfil entre cores — robusto incluso cuando una
    cola toca un asta del renglón siguiente, como en letra real. Asume página
    razonablemente derecha (<~1°). Devuelve líneas top→bottom, ordenadas por x.
    """
    if not boxes:
        return []
    row_ink = mask.sum(axis=1).astype(np.float64)
    if row_ink.max() <= 0:
        return []
    smooth = np.convolve(row_ink, np.ones(7) / 7.0, mode="same")
    cores = _row_runs(smooth > 0.15 * smooth.max())
    if not cores:
        return []
    # Cores-fragmento (rebabas del umbral) se absorben en el vecino cercano.
    while len(cores) > 1:
        heights = sorted(e - s for s, e in cores)
        h_med = heights[len(heights) // 2]
        idx = next((i for i, (s, e) in enumerate(cores)
                    if (e - s) < 0.25 * h_med), None)
        if idx is None:
            break
        s, e = cores.pop(idx)
        gap_prev = s - cores[idx - 1][1] if idx > 0 else None
        gap_next = cores[idx][0] - e if idx < len(cores) else None
        if gap_next is None or (gap_prev is not None and gap_prev <= gap_next):
            cores[idx - 1] = (cores[idx - 1][0], max(cores[idx - 1][1], e))
        else:
            cores[idx] = (min(cores[idx][0], s), cores[idx][1])
    # Fronteras: el valle (mínimo del perfil) entre el fin de un core y el
    # inicio del siguiente; si se tocan, el punto medio.
    seps: list[float] = []
    for (s0, e0), (s1, e1) in zip(cores, cores[1:]):
        lo, hi = min(e0, s1), max(e0, s1)
        if hi - lo >= 2:
            seps.append(lo + int(np.argmin(smooth[lo:hi])))
        else:
            seps.append((e0 + s1) / 2.0)
    lines: list[list] = [[] for _ in cores]
    for b in boxes:
        cy = (b[1] + b[3]) / 2.0
        idx = sum(1 for s in seps if cy >= s)   # segmento entre fronteras
        lines[idx].append(b)
    return [sorted(ln, key=lambda b: b[0]) for ln in lines if ln]


def _merge_vertical_parts(line: list) -> list:
    """Fusiona en una sola caja las partes apiladas de una letra (punto de la
    i, tilde) con su base: si dos cajas vecinas solapan >50% en X son la misma
    letra y separarlas metería huecos negativos espurios en los gaps."""
    merged: list[list[int]] = []
    for x0, y0, x1, y1, area in line:
        if merged:
            mx0, my0, mx1, my1, marea = merged[-1]
            ov = min(x1, mx1) - max(x0, mx0)
            if ov > 0 and ov > 0.5 * min(x1 - x0, mx1 - mx0):
                merged[-1] = [min(mx0, x0), min(my0, y0),
                              max(mx1, x1), max(my1, y1), marea + area]
                continue
        merged.append([x0, y0, x1, y1, area])
    return [tuple(m) for m in merged]


# ── Métricas individuales ───────────────────────────────────────────────────

def _stats(values: list[float]) -> tuple[float, float, float]:
    """(media, σ, CV) de una lista; CV=0 si la media es ~0."""
    if not values:
        return 0.0, 0.0, 0.0
    arr = np.asarray(values, dtype=np.float64)
    mu = float(arr.mean())
    sigma = float(arr.std())
    cv = sigma / abs(mu) if abs(mu) > 1e-9 else 0.0
    return mu, sigma, cv


def _gap_metrics(lines: list[list]) -> dict:
    """Huecos horizontales entre cajas consecutivas de la misma línea.

    El split letra/palabra usa 2.5× la mediana de los huecos positivos: los
    huecos de palabra son varias veces el de letra en cualquier escritura.
    """
    gaps: list[float] = []
    for line in lines:
        for a, b in zip(line, line[1:]):
            gaps.append(float(b[0] - a[2]))
    positive = sorted(g for g in gaps if g > 0)
    if not positive:
        return {"letter_gap_mu": 0.0, "letter_gap_sigma": 0.0, "letter_gap_cv": 0.0,
                "word_gap_mu": 0.0, "word_gap_sigma": 0.0, "word_gap_cv": 0.0}
    median = positive[len(positive) // 2]
    word_thr = 2.5 * median
    letter = [g for g in gaps if g <= word_thr]
    word = [g for g in gaps if g > word_thr]
    lmu, lsig, lcv = _stats(letter)
    wmu, wsig, wcv = _stats(word)
    return {"letter_gap_mu": round(lmu, 3), "letter_gap_sigma": round(lsig, 3),
            "letter_gap_cv": round(lcv, 4),
            "word_gap_mu": round(wmu, 3), "word_gap_sigma": round(wsig, 3),
            "word_gap_cv": round(wcv, 4)}


def _baseline_metrics(lines: list[list]) -> dict:
    """σ del residuo y autocorrelación lag-1 del y-inferior vs la recta de línea.

    Ruido blanco (jitter por letra) da autocorr ≈ 0; el vaivén de una mano da
    un residuo correlacionado (>0.5). Una recta láser da σ ≈ 0.

    Ajuste ROBUSTO en dos pasos: las DESCENDENTES cuelgan su y-inferior muy
    por debajo del baseline real (un salto de forma, no de posición) y
    ahogarían la señal del vaivén; se ajusta, se descartan los outliers
    (>1.8σ) y se re-ajusta con las letras que asientan en la línea base.
    """
    residuals_all: list[np.ndarray] = []
    for line in lines:
        if len(line) < 4:
            continue
        xs = np.asarray([(b[0] + b[2]) / 2.0 for b in line])
        ys = np.asarray([float(b[3]) for b in line])
        coeff = np.polyfit(xs, ys, 1)
        res = ys - np.polyval(coeff, xs)
        sd = res.std()
        if sd > 1e-9:
            keep = np.abs(res) <= 1.8 * sd
            if keep.sum() >= 4:
                coeff = np.polyfit(xs[keep], ys[keep], 1)
                res = ys[keep] - np.polyval(coeff, xs[keep])
        residuals_all.append(res)
    if not residuals_all:
        return {"baseline_sigma": 0.0, "baseline_autocorr": 0.0}
    pooled = np.concatenate(residuals_all)
    sigma = float(pooled.std())
    num = 0.0
    den = 0.0
    for r in residuals_all:
        num += float((r[:-1] * r[1:]).sum())
        den += float((r * r).sum())
    autocorr = num / den if den > 1e-9 else 0.0
    return {"baseline_sigma": round(sigma, 3), "baseline_autocorr": round(autocorr, 4)}


def _slant_metrics(mask: np.ndarray, lines: list[list]) -> dict:
    """Ángulo de inclinación por caja vía momentos de imagen (deskew clásico).

    slant = atan(-mu11/mu02): positivo = recostado a la derecha (top corrido a
    la derecha, con y creciendo hacia abajo). Sólo cajas de letra (no motas).
    """
    flat = [b for line in lines for b in line]
    if not flat:
        return {"slant_mean": 0.0, "slant_std": 0.0}
    h_med = sorted(b[3] - b[1] for b in flat)[len(flat) // 2]
    angles: list[float] = []
    for x0, y0, x1, y1, _ in flat:
        if (y1 - y0) < 0.5 * h_med or (x1 - x0) < 3:
            continue
        ys, xs = np.nonzero(mask[y0:y1, x0:x1])
        if len(xs) < 12:
            continue
        xc = xs - xs.mean()
        yc = ys - ys.mean()
        mu02 = float((yc * yc).mean())
        if mu02 < 1e-6:
            continue
        mu11 = float((xc * yc).mean())
        angles.append(math.degrees(math.atan(-mu11 / mu02)))
    mu, sigma, _ = _stats(angles)
    return {"slant_mean": round(mu, 3), "slant_std": round(sigma, 3)}


def _dhash_mask(crop: np.ndarray) -> str:
    """dHash 64-bit de un crop binario (resize 9×8 + gradiente horizontal).

    No reutiliza bank_hashing._dhash porque aquélla espera el RGBA del banco
    (forma en alpha); acá la entrada es la máscara de tinta de la página. La
    distancia sí es la misma (_hamming del banco)."""
    img = Image.fromarray((crop * 255).astype(np.uint8)).resize(
        (9, 8), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.int16)
    bits = (arr[:, 1:] > arr[:, :-1]).ravel()
    return "".join("1" if b else "0" for b in bits)


def _dup_rate(mask: np.ndarray, lines: list[list],
              threshold: int = DUP_HAMMING_THRESHOLD) -> float:
    """Fracción de cajas con al menos un gemelo perceptual en la página.

    Detector de "sellos": con 1 variante por char y sin deformación, casi toda
    letra tiene otra instancia idéntica en la página → rate ≈ 1.0. El warp por
    instancia (R5) debe bajarlo a <0.05. Se mide por caja (no por par) para que
    el número sea interpretable como % de letras delatoras.
    """
    flat = [b for line in lines for b in line if b[4] >= 25]
    if len(flat) < 2:
        return 0.0
    hashes = [_dhash_mask(mask[y0:y1, x0:x1]) for x0, y0, x1, y1, _ in flat]
    dup = 0
    for i, hi in enumerate(hashes):
        for j, hj in enumerate(hashes):
            if i != j and _hamming(hi, hj) <= threshold:
                dup += 1
                break
    return round(dup / len(flat), 4)


# ── API pública ──────────────────────────────────────────────────────────────

def compute_metrics(img: Image.Image,
                    dup_threshold: int = DUP_HAMMING_THRESHOLD) -> dict:
    """Todas las métricas de realismo de una imagen de texto. JSON-serializable.

    Claves: n_boxes, n_lines, height_mu/height_cv, letter_gap_*, word_gap_*,
    baseline_sigma/baseline_autocorr, slant_mean/slant_std, phash_dup_rate.
    Referencias humanas: height_cv 0.35-0.60, word_gap_cv >0.10,
    baseline_autocorr >0.4, phash_dup_rate <0.05.
    """
    mask = _ink_mask(img)
    h, w = mask.shape
    boxes = _filter_boxes(connected_boxes(mask), w, h)
    lines = [_merge_vertical_parts(line) for line in group_lines(boxes, mask)]

    flat = [b for line in lines for b in line]
    out: dict = {"n_boxes": len(flat), "n_lines": len(lines)}
    heights = [float(b[3] - b[1]) for b in flat]
    big = sorted(heights)
    h_med = big[len(big) // 2] if big else 0.0
    # Sólo cajas de letra (≥30% de la mediana): las comas/motas no son "letras"
    # y meterían un CV inflado tanto en lo real como en lo sintético.
    letters = [hh for hh in heights if hh >= 0.3 * h_med]
    mu, _sigma, cv = _stats(letters)
    out["height_mu"] = round(mu, 3)
    out["height_cv"] = round(cv, 4)
    out.update(_gap_metrics(lines))
    out.update(_baseline_metrics(lines))
    out.update(_slant_metrics(mask, lines))
    out["phash_dup_rate"] = _dup_rate(mask, lines, dup_threshold)
    return out


def metrics_from_path(path: str, dup_threshold: int = DUP_HAMMING_THRESHOLD) -> dict:
    """compute_metrics sobre un archivo de imagen."""
    with Image.open(path) as img:
        return compute_metrics(img.copy(), dup_threshold)

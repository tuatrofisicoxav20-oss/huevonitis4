"""Segmentación de una línea por los espacios REALES entre letras.

El alineador posicional (hybrid_v2/InkFlow) reparte la línea en N franjas según
el ancho esperado de cada carácter. Cuando las letras están bien separadas —un
abecedario, letra de imprenta— eso junta vecinas ('c'+'d'→"cd") y corre las
etiquetas. Aquí detectamos los valles del perfil de proyección vertical (los
huecos entre letras) y, si el número de grupos de tinta se puede ajustar al
número de letras esperadas, los usamos como fronteras. Si no, devolvemos None y
el caller cae a la estrategia posicional.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _OK = True
except ImportError:
    _OK = False


def _ink_groups(vpp_s, x_min: int, x_max: int, thr: float, min_w: int):
    """Grupos contiguos de columnas con tinta > thr, de ancho >= min_w."""
    groups: list[list[int]] = []
    start = None
    for x in range(x_min, x_max):
        on = vpp_s[x] > thr
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start >= min_w:
                groups.append([start, x])
            start = None
    if start is not None and x_max - start >= min_w:
        groups.append([start, x_max])
    return groups


def _merge_to_n(groups, n: int):
    """Fusiona los grupos separados por los gaps más estrechos hasta quedar n.

    Sobran grupos cuando una letra se fragmenta (punto de i/j, trazos sueltos):
    los pedazos de una misma letra están muy juntos, así que fusionar por el gap
    más pequeño reúne la letra.
    """
    g = [list(x) for x in groups]
    while len(g) > n:
        # gap más estrecho entre grupos consecutivos
        i_min, gap_min = 0, None
        for i in range(len(g) - 1):
            gap = g[i + 1][0] - g[i][1]
            if gap_min is None or gap < gap_min:
                gap_min, i_min = gap, i
        g[i_min][1] = g[i_min + 1][1]
        del g[i_min + 1]
    return g


def _split_to_n(groups, vpp_s, n: int):
    """Parte los grupos más anchos por su valle interno hasta quedar n.

    Faltan grupos cuando dos letras se tocan ('i'+'j'): el grupo ancho esconde un
    valle interno (mínimo de tinta) que es la frontera real entre ellas.
    """
    g = [list(x) for x in groups]
    while len(g) < n:
        # grupo más ancho
        i_wide = max(range(len(g)), key=lambda i: g[i][1] - g[i][0])
        a, b = g[i_wide]
        if b - a < 4:
            break  # no hay nada que partir
        # valle interno: columna de mínima tinta, evitando los bordes
        margin = max(1, (b - a) // 5)
        lo, hi = a + margin, b - margin
        if hi <= lo:
            break
        seg = vpp_s[lo:hi]
        cut = lo + int(np.argmin(seg))
        g[i_wide] = [a, cut]
        g.insert(i_wide + 1, [cut, b])
    return g


def segment_by_gaps(vpp, x_min: int, x_max: int, n: int) -> list[int] | None:
    """Devuelve n+1 fronteras desde los espacios reales entre letras, o None.

    None significa "no pude segmentar con confianza por gaps" → usar posicional.
    """
    if not _OK or n <= 1 or x_max - x_min < n:
        return None
    span = x_max - x_min
    char_w = span / n
    ks = max(3, int(char_w * 0.15))
    ks = ks if ks % 2 == 1 else ks + 1
    vpp_s = cv2.GaussianBlur(
        np.asarray(vpp, dtype=np.float32).reshape(1, -1), (1, ks), 0,
    ).flatten()
    vmax = float(vpp_s[x_min:x_max].max())
    if vmax <= 0:
        return None
    thr = vmax * 0.12               # gap = tinta por debajo del 12% del máximo
    min_w = max(2, int(char_w * 0.12))
    groups = _ink_groups(vpp_s, x_min, x_max, thr, min_w)
    if not groups:
        return None
    # Sólo confiar si el desajuste es moderado (hasta ~70% de más/menos grupos);
    # un desajuste enorme indica que la línea no son letras separadas.
    if not (0.4 * n <= len(groups) <= 2.0 * n):
        return None
    if len(groups) > n:
        groups = _merge_to_n(groups, n)
    elif len(groups) < n:
        groups = _split_to_n(groups, vpp_s, n)
    if len(groups) != n:
        return None
    # Fronteras: bordes externos + punto medio de cada gap entre grupos.
    bounds = [int(groups[0][0])]
    for i in range(len(groups) - 1):
        bounds.append(int((groups[i][1] + groups[i + 1][0]) // 2))
    bounds.append(int(groups[-1][1]))
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 1
    return bounds

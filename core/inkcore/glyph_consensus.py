"""Salto 2 — Consenso entre instancias del mismo carácter.

Cada aparición de un carácter se evaluaba AISLADA. Pero un char aparece N veces,
y eso es evidencia estadística: si una instancia se desvía mucho del grupo, casi
siempre es una mala segmentación (se comió la letra vecina, se cortó a la mitad),
aunque haya pasado el filtro de calidad y hasta la verificación.

Dos usos:
  • OUTLIER REJECTION (en una sesión de extracción): agrupar instancias del mismo
    char, medir distancia visual al grupo, y BAJAR DE TIER las que se alejan mucho
    de la mediana. CPU-friendly: distancia de Hamming sobre hashes perceptuales.
  • MEDOIDE: elegir la instancia más central/representativa de un grupo (la que
    minimiza la distancia total al resto), en vez de una al azar.

Distancia: Hamming sobre el hash perceptual (cadena de '0'/'1'). Barato y sin
re-abrir PNGs cuando el hash ya está cacheado.
"""
from __future__ import annotations

MIN_GROUP = 4          # no marcamos outliers en grupos chicos (poca evidencia)
OUTLIER_K = 3.0        # umbral: dist > mediana + K·MAD para considerar outlier
_DEMOTE = {"Gold": "Silver", "Silver": "Bronze", "Bronze": "Bronze"}


def hamming(a: str, b: str) -> int:
    if not a or not b:
        return max(len(a), len(b)) or 1
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def medoid_index(hashes: list[str]) -> int:
    """Índice del hash más central (mínima suma de distancias al resto).

    Ignora hashes vacíos para el cálculo, pero devuelve siempre un índice válido
    de la lista original (0 si no hay ninguno usable)."""
    valid = [(i, h) for i, h in enumerate(hashes) if h]
    if not valid:
        return 0
    if len(valid) == 1:
        return valid[0][0]
    best_i, best_sum = valid[0][0], None
    for i, h in valid:
        s = sum(hamming(h, h2) for j, h2 in valid if j != i)
        if best_sum is None or s < best_sum:
            best_sum, best_i = s, i
    return best_i


def outlier_flags(hashes: list[str], k: float = OUTLIER_K,
                  min_group: int = MIN_GROUP) -> list[bool]:
    """Devuelve una lista de bools (True = instancia sospechosa de mala
    segmentación) usando distancia al medoide + criterio mediana/MAD robusto.

    No marca nada si el grupo es chico (< min_group): sin suficientes instancias
    no hay evidencia para llamar a algo "outlier"."""
    n = len(hashes)
    flags = [False] * n
    valid = [(i, h) for i, h in enumerate(hashes) if h]
    if len(valid) < min_group:
        return flags

    mi = medoid_index(hashes)
    medoid_h = hashes[mi]
    dists = {i: hamming(h, medoid_h) for i, h in valid}
    vals = sorted(dists.values())
    m = len(vals)
    median = vals[m // 2] if m % 2 else (vals[m // 2 - 1] + vals[m // 2]) / 2.0
    mad_vals = sorted(abs(v - median) for v in vals)
    mad = mad_vals[m // 2] if m % 2 else (mad_vals[m // 2 - 1] + mad_vals[m // 2]) / 2.0
    mad = mad or 1.0  # evita umbral 0 cuando casi todas son idénticas

    threshold = median + k * mad
    for i, d in dists.items():
        if d > threshold and d > median:
            flags[i] = True
    return flags


def demote_session_outliers(glyphs: list, hashes: list[str]) -> int:
    """Agrupa por carácter y BAJA DE TIER las instancias outlier de cada grupo.

    `glyphs[i]` y `hashes[i]` deben estar alineados 1:1. Devuelve cuántas
    instancias se degradaron. Marca `quality_score`/tier; no borra nada."""
    if not glyphs or len(glyphs) != len(hashes):
        return 0
    by_char: dict[str, list[int]] = {}
    for i, g in enumerate(glyphs):
        by_char.setdefault(g.char, []).append(i)

    demoted = 0
    for char, idxs in by_char.items():
        if len(idxs) < MIN_GROUP:
            continue
        group_hashes = [hashes[i] for i in idxs]
        flags = outlier_flags(group_hashes)
        for local, i in enumerate(idxs):
            if flags[local] and glyphs[i].tier != "Bronze":
                glyphs[i].tier = _DEMOTE[glyphs[i].tier]
                demoted += 1
    return demoted

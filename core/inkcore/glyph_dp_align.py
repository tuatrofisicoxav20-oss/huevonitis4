"""Salto 3 — Alineación GLOBAL caja↔carácter por programación dinámica (Needleman–Wunsch).

El mapeo POSICIONAL (la i-ésima caja en orden de lectura ↔ el i-ésimo carácter de
la referencia) es greedy: una sola caja extra o faltante al principio de la línea
desfasa TODO lo que sigue (la caja 3 mal asignada envenena las cajas 4..N). Eso
arruina la verificación cruzada (F4): se compara cada caja contra el carácter
equivocado y o bien se pierde el Gold o se promueve basura.

Aquí alineamos la SECUENCIA de cajas (en orden de lectura) con la SECUENCIA de
caracteres de la referencia con Needleman–Wunsch (min-coste), robusto a que
sobren o falten cajas:
  • match(caja, char): ancho de la caja vs `wf(char)` (calibrado por el Salto 4)
    + premio si el labeler predijo ese mismo carácter sobre ese crop.
  • gap en cajas  → carácter sin caja (caracteres pegados / no detectados).
  • gap en chars  → caja sobrante (ruido, diacrítico suelto).

Complejidad O(n·m) con n cajas y m caracteres por LÍNEA — barato; no se corre sobre
la página entera de una sino por renglón.
"""
from __future__ import annotations

from collections.abc import Callable

# Costes por defecto (escala comparable al término de ancho, ~0..2).
GAP_BOX = 0.65        # saltar una caja (caja sobrante)
GAP_CHAR = 0.65       # saltar un carácter (carácter sin caja)
CONF_BONUS = 0.6      # premio máx. si el labeler confirma el char
MISMATCH_PEN = 0.45   # castigo si el labeler predijo OTRO char alfanumérico


def _sub_cost(width_norm: float, pred_char: str, conf: float | None,
              target_char: str, wf_fn: Callable[[str], float]) -> float:
    """Coste de emparejar una caja con un carácter objetivo (menor = mejor)."""
    cost = abs(float(width_norm) - float(wf_fn(target_char)))
    p = (pred_char or "").strip()[:1].lower()
    t = (target_char or "").strip()[:1].lower()
    if p and p == t:
        cost -= CONF_BONUS * (conf if conf is not None else 0.5)
    elif p and p.isalnum() and p != t:
        cost += MISMATCH_PEN
    return cost


def nw_align(
    box_widths_norm: list[float],
    box_pred_chars: list[str],
    box_confs: list[float | None],
    ref_chars: list[str],
    wf_fn: Callable[[str], float],
    *,
    gap_box: float = GAP_BOX,
    gap_char: float = GAP_CHAR,
) -> dict[int, int]:
    """Alinea cajas (orden de lectura) con `ref_chars`. Devuelve {idx_caja: idx_char}
    solo para las cajas EMPAREJADAS (las cajas sobrantes no aparecen en el dict)."""
    n = len(box_widths_norm)
    m = len(ref_chars)
    if n == 0 or m == 0:
        return {}

    # Matriz de costes acumulados + punteros de traceback.
    INF = float("inf")
    D = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]  # 0=diag(match) 1=up(gap_box) 2=left(gap_char)
    for i in range(1, n + 1):
        D[i][0] = i * gap_box
        bt[i][0] = 1
    for j in range(1, m + 1):
        D[0][j] = j * gap_char
        bt[0][j] = 2

    for i in range(1, n + 1):
        wi = box_widths_norm[i - 1]
        pi = box_pred_chars[i - 1] if i - 1 < len(box_pred_chars) else ""
        ci = box_confs[i - 1] if i - 1 < len(box_confs) else None
        for j in range(1, m + 1):
            sub = D[i - 1][j - 1] + _sub_cost(wi, pi, ci, ref_chars[j - 1], wf_fn)
            up = D[i - 1][j] + gap_box      # caja i sobrante
            left = D[i][j - 1] + gap_char   # char j sin caja
            best = sub
            choice = 0
            if up < best:
                best, choice = up, 1
            if left < best:
                best, choice = left, 2
            D[i][j] = best if best != INF else INF
            bt[i][j] = choice

    # Traceback desde (n, m).
    i, j = n, m
    mapping: dict[int, int] = {}
    while i > 0 or j > 0:
        c = bt[i][j]
        if i > 0 and j > 0 and c == 0:
            mapping[i - 1] = j - 1
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or c == 1):
            i -= 1  # caja sobrante
        else:
            j -= 1  # char sin caja
    return mapping

"""Salto 5 — Multibinarización adaptativa.

Otsu (la binarización por defecto del detector clásico) FALLA en fotos de bajo
contraste: cuando la tinta es tenue (lápiz claro, papel amarillo), el umbral se
invierte y marca ~95% de la imagen como "tinta", colapsando todo el texto en un
solo componente conexo (se vio: muestra4 derecha y legible → 1 caja).

Aquí formalizamos un CONJUNTO de binarizaciones candidatas y elegimos, UNA VEZ por
imagen, la que produce la detección más sana: descartamos las degeneradas (fracción
de tinta absurda = umbral invertido o vacío) y entre las que quedan elegimos la que
da más componentes del tamaño de una letra. Barato (se corre una vez por imagen).

El detector clásico usa `best_binary()`; las funciones individuales quedan
disponibles para comparación/tests.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

try:
    from skimage.filters import threshold_sauvola as _sk_sauvola
    _SK_OK = True
except ImportError:
    _SK_OK = False

# Una binarización con fracción de tinta fuera de este rango es degenerada
# (umbral invertido si es altísima; vacía si es ~0).
INK_MIN = 0.001   # 0.1 %
INK_MAX = 0.35    # 35 %  (texto normal raramente supera esto)
_MIN_COMP_AREA = 10
_MIN_CHAR_W = 2
_MIN_CHAR_H = 3


def candidate_masks(gray: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Devuelve [(nombre, mask_binaria_inv)] — tinta = blanco (255)."""
    if not _CV2_OK:
        return []
    out: list[tuple[str, np.ndarray]] = []

    # 1) Otsu sobre CLAHE (el método histórico) — bueno en buen contraste.
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    _, m = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    out.append(("otsu_clahe", m))

    # 2) Adaptive gaussian — robusto a iluminación/contraste variable. Dos escalas.
    out.append(("adaptive_31_10", cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 10)))
    out.append(("adaptive_51_15", cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 51, 15)))

    # 3) Sauvola (si hay skimage) — clásico de documento con sombra.
    if _SK_OK:
        try:
            win = 25
            thr = _sk_sauvola(gray, window_size=win, k=0.2, r=128.0)
            sav = ((gray < thr) * 255).astype(np.uint8)
            out.append(("sauvola", sav))
        except Exception as exc:
            logger.debug("sauvola candidato falló: %s", exc)
    return out


def _letter_cc_count(mask: np.ndarray) -> int:
    """Cuenta componentes del tamaño de una letra (excluye ruido y el blob-página)."""
    h, w = mask.shape[:2]
    num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    n = 0
    for i in range(1, num):
        cw = int(stats[i, cv2.CC_STAT_WIDTH])
        ch = int(stats[i, cv2.CC_STAT_HEIGHT])
        ca = int(stats[i, cv2.CC_STAT_AREA])
        if ca < _MIN_COMP_AREA or cw < _MIN_CHAR_W or ch < _MIN_CHAR_H:
            continue
        if cw > w * 0.6 or ch > h * 0.6:
            continue  # blob que abarca casi toda la imagen = umbral colapsado
        n += 1
    return n


def best_binary(gray: np.ndarray) -> tuple[str, np.ndarray]:
    """Elige la mejor binarización por contenido.

    Descarta candidatas degeneradas (fracción de tinta fuera de [INK_MIN, INK_MAX])
    y entre las válidas elige la que produce más componentes tipo-letra. Si todas
    son degeneradas, cae a la menos mala (la de fracción de tinta más cercana al
    rango). Devuelve (nombre, mask).
    """
    cands = candidate_masks(gray)
    if not cands:
        return ("none", gray)

    scored = []
    for name, m in cands:
        ink = float(m.mean()) / 255.0
        degenerate = not (INK_MIN <= ink <= INK_MAX)
        cc = _letter_cc_count(m) if not degenerate else -1
        scored.append((name, m, ink, degenerate, cc))

    valid = [s for s in scored if not s[3]]
    if valid:
        best = max(valid, key=lambda s: s[4])  # más componentes tipo-letra
        logger.debug("best_binary: %s (cc=%d, ink=%.3f)", best[0], best[4], best[2])
        return (best[0], best[1])

    # Todas degeneradas: la de fracción de tinta más cercana al rango medio.
    target = (INK_MIN + INK_MAX) / 2
    best = min(scored, key=lambda s: abs(s[2] - target))
    logger.warning("best_binary: todas degeneradas, uso %s (ink=%.3f)", best[0], best[2])
    return (best[0], best[1])

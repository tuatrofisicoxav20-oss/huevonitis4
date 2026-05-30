"""Validación estructural de glifos: coherencia entre la forma extraída y la
letra que la alineación posicional le asignó.

Ataca el caso reportado "'a' etiquetada como 'd'" (y viceversa). El extractor
asigna a cada glifo el carácter del texto de referencia SEGÚN SU POSICIÓN; si la
segmentación se desplaza (una 'm' contada como dos trazos, dos letras ligadas
como una), las etiquetas siguientes se corren y un glifo recibe la letra de otra
posición. La FORMA es una restricción que la posición ignora: una 'd' sube como
ascendente sobre la x-height; una 'a' no. Comparar la extensión vertical del
glifo con la categoría esperada de su letra detecta esos desajustes.

Conservador a propósito: solo marca inconsistencia en contradicciones CLARAS,
para no descartar la letra (legítimamente irregular) de un manuscrito real.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Categorías por extensión vertical en escritura latina minúscula.
_ASCENDERS = set("bdfhklt")          # suben sobre la x-height
_DESCENDERS = set("gjpqy")           # bajan bajo la baseline
# El resto (a c e m n o r s u v w x z ñ) viven en la x-height.
# Ambiguos → no se validan: 'i'/'j' (punto), acentuadas (el acento sube),
# puntuación, dígitos y mayúsculas (todas suben).
_AMBIGUOUS = (
    set("ij")
    | set("áéíóúàèìòùâêîôûäëïöü")
    | set(".,;:!¡?¿|`'\"-_()[]{}/\\")
    | set("0123456789")
)


def expected_vclass(ch: str) -> str:
    """Categoría vertical esperada de un carácter: 'asc' | 'desc' | 'xheight' | 'any'."""
    if not ch:
        return "any"
    if ch.isupper():          # mayúsculas suben todas → ambiguas para esta validación
        return "any"
    c = ch.lower()
    if c in _AMBIGUOUS:
        return "any"
    if c in _ASCENDERS:
        return "asc"
    if c in _DESCENDERS:
        return "desc"
    if c.isalpha():
        return "xheight"
    return "any"


def line_metrics(line_mask) -> tuple[int, int, int, int] | None:
    """Estima (xh_top, xh_bot, line_top, line_bot) de una banda de línea (uint8).

    La x-height es la banda de mayor densidad de tinta por fila (donde viven
    TODAS las letras); ascendentes/descendentes la exceden por arriba/abajo.
    Devuelve None si la línea es demasiado pobre para estimar con confianza.
    """
    try:
        import numpy as np
    except ImportError:
        return None
    if line_mask is None or getattr(line_mask, "size", 0) == 0:
        return None
    rows = line_mask.sum(axis=1).astype("float64")
    rmax = float(rows.max())
    if rmax <= 0:
        return None
    ink = np.where(rows > rmax * 0.10)[0]
    if len(ink) < 3:
        return None
    line_top, line_bot = int(ink.min()), int(ink.max())
    dense = np.where(rows > rmax * 0.50)[0]
    if len(dense) < 2:
        return None
    xh_top, xh_bot = int(dense.min()), int(dense.max())
    # Guarda: si la banda densa cubre casi toda la línea no hay margen para
    # distinguir ascendentes/descendentes con fiabilidad → no validar.
    if (line_bot - line_top) < 6 or (xh_bot - xh_top) >= (line_bot - line_top) * 0.92:
        return None
    return xh_top, xh_bot, line_top, line_bot


def glyph_vclass(gy1: int, gy2: int, metrics, frac: float = 0.18) -> str:
    """Clasifica la extensión vertical de un glifo: 'asc'|'desc'|'both'|'xheight'.

    gy1/gy2 son top/bottom del glifo en las MISMAS coordenadas que line_mask.
    frac es la fracción de la altura de línea que debe exceder la x-height para
    contar como ascendente/descendente (0.18 ≈ holgado, tolera irregularidad).
    """
    xh_top, xh_bot, line_top, line_bot = metrics
    line_h = max(1, line_bot - line_top)
    sube = (xh_top - gy1) / line_h
    baja = (gy2 - xh_bot) / line_h
    asc = sube > frac
    desc = baja > frac
    if asc and desc:
        return "both"
    if asc:
        return "asc"
    if desc:
        return "desc"
    return "xheight"


def is_consistent(char: str, gy1: int, gy2: int, metrics) -> bool:
    """True si la forma del glifo es compatible con la letra que se le asignó.

    Conservador: ante categoría 'any', métricas no estimables, o formas
    ambiguas ('both'), devuelve True (no descarta). Solo niega contradicciones
    claras: x-height esperada con ascendente marcado (a↔d), o ascendente/
    descendente esperado que no aparece.
    """
    if metrics is None:
        return True
    exp = expected_vclass(char)
    if exp == "any":
        return True
    got = glyph_vclass(gy1, gy2, metrics)
    if got == "both":
        return True
    if exp == "xheight":
        return got == "xheight"
    if exp == "asc":
        return got in ("asc", "both")
    if exp == "desc":
        return got in ("desc", "both")
    return True

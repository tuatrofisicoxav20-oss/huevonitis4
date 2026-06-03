"""Cobertura del alfabeto: qué letras tenemos y cuáles faltan.

Lógica pura (sin cv2/PIL) para que la UI pueda decir con claridad "te faltan
g, m, n…". Sirve tanto para una extracción suelta (¿qué letras quedaron sin
recortar en esta foto?) como para el banco completo (¿qué letras todavía no
tengo, para subir otra foto?). Es la base del flujo multi-imagen: el banco
acumula al guardar, y este resumen guía al usuario a completar lo que falta.
"""
from __future__ import annotations

from collections.abc import Iterable

# Alfabeto español, ñ en la posición 14 (igual que el resto del proyecto).
SPANISH_ALPHABET = "abcdefghijklmnñopqrstuvwxyz"


def _present_set(chars: Iterable[str]) -> set[str]:
    """Conjunto de letras presentes, en minúscula, ignorando no-strings y vacíos."""
    out: set[str] = set()
    for c in chars:
        if isinstance(c, str) and c:
            out.add(c.lower())
    return out


def missing_letters(
    present: Iterable[str], alphabet: str = SPANISH_ALPHABET,
) -> list[str]:
    """Letras del alfabeto que NO aparecen en `present`, en orden alfabético."""
    have = _present_set(present)
    return [c for c in alphabet if c not in have]


def coverage(
    present: Iterable[str], alphabet: str = SPANISH_ALPHABET,
) -> tuple[int, int, list[str]]:
    """Devuelve (tenidas, total, faltantes) respecto al alfabeto dado."""
    miss = missing_letters(present, alphabet)
    return len(alphabet) - len(miss), len(alphabet), miss


def coverage_message(
    present: Iterable[str], alphabet: str = SPANISH_ALPHABET, *, scope: str = "",
) -> str:
    """Frase lista para la UI: 'Banco: 21/27 · faltan g m n o x z'.

    `scope` es un prefijo opcional ('Banco', 'Esta foto'…). Si no falta nada,
    devuelve un mensaje de completitud.
    """
    have, total, miss = coverage(present, alphabet)
    prefix = f"{scope}: " if scope else ""
    if not miss:
        return f"{prefix}{have}/{total} ✓ alfabeto completo"
    return f"{prefix}{have}/{total} · faltan {' '.join(miss)}"

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


def _case_sensitive(alphabet: str) -> bool:
    """¿El alfabeto distingue mayúsculas? (charset con MAYÚSCULAS lo requiere).

    Con el alfabeto base (27 minúsculas) devuelve False y se conserva el
    comportamiento histórico de ignorar mayúsculas. Cuando el charset de la
    plantilla incluye 'A'..'Z', 'a' y 'A' son glifos distintos y no deben
    colapsarse al medir cobertura.
    """
    return any(c.isupper() for c in alphabet)


def _present_set(chars: Iterable[str], *, case_sensitive: bool = False) -> set[str]:
    """Conjunto de caracteres presentes, ignorando no-strings y vacíos.

    Si `case_sensitive` es False (default) normaliza a minúscula, como antes.
    """
    out: set[str] = set()
    for c in chars:
        if isinstance(c, str) and c:
            out.add(c if case_sensitive else c.lower())
    return out


def missing_letters(
    present: Iterable[str], alphabet: str = SPANISH_ALPHABET,
    *, case_sensitive: bool | None = None,
) -> list[str]:
    """Caracteres del alfabeto que NO aparecen en `present`, en orden del alfabeto.

    `case_sensitive=None` autodetecta según el alfabeto (True si incluye
    mayúsculas), así un charset con MAYÚSCULAS/dígitos se mide bien sin tocar a
    los llamadores que usan el alfabeto base.
    """
    cs = _case_sensitive(alphabet) if case_sensitive is None else case_sensitive
    have = _present_set(present, case_sensitive=cs)
    return [c for c in alphabet if (c if cs else c.lower()) not in have]


def coverage(
    present: Iterable[str], alphabet: str = SPANISH_ALPHABET,
    *, case_sensitive: bool | None = None,
) -> tuple[int, int, list[str]]:
    """Devuelve (tenidas, total, faltantes) respecto al alfabeto dado."""
    miss = missing_letters(present, alphabet, case_sensitive=case_sensitive)
    return len(alphabet) - len(miss), len(alphabet), miss


def coverage_message(
    present: Iterable[str], alphabet: str = SPANISH_ALPHABET, *, scope: str = "",
    case_sensitive: bool | None = None,
) -> str:
    """Frase lista para la UI: 'Banco: 21/27 · faltan g m n o x z'.

    `scope` es un prefijo opcional ('Banco', 'Esta foto'…). `alphabet` es el
    charset real de la plantilla (puede incluir MAYÚSCULAS, dígitos o
    puntuación), así el conteo 'tenidas/total' refleja lo que se pidió y no las
    27 minúsculas. Si no falta nada, devuelve un mensaje de completitud.
    """
    have, total, miss = coverage(present, alphabet, case_sensitive=case_sensitive)
    prefix = f"{scope}: " if scope else ""
    if not miss:
        return f"{prefix}{have}/{total} ✓ completo"
    return f"{prefix}{have}/{total} · faltan {' '.join(miss)}"

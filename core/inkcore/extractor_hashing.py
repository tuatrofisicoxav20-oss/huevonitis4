"""Hashing perceptual para deduplicación de glifos.

Doble hash (8×8 + 16×16) ponderado: 0.6 al hash basto + 0.4 al fino.
Más sensible a variaciones reales que un solo hash 8×8 — clave para
distinguir variantes naturales de la misma letra del mismo usuario.
"""
from __future__ import annotations

try:
    import numpy as _np
    from PIL import Image
    _OK = True
except ImportError:
    _OK = False


def avg_hash(img: "Image.Image", size: int = 16) -> str:
    gray = img.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    px = _np.asarray(gray).flatten().tolist()
    avg = sum(px) / max(1, len(px))
    return "".join("1" if p >= avg else "0" for p in px)


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b, strict=False)) + abs(len(a) - len(b))


def dual_hash(img: "Image.Image") -> tuple[str, str]:
    return avg_hash(img, 8), avg_hash(img, 16)


def dual_dist(a: tuple[str, str], b: tuple[str, str]) -> float:
    h8 = hamming(a[0], b[0])           # 0-64
    h16 = hamming(a[1], b[1]) / 4.0    # 0-64 normalizado
    return h8 * 0.6 + h16 * 0.4

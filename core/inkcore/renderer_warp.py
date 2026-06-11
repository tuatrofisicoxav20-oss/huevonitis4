"""Warp elástico por instancia de glifo (Fase R5 — C4, el asesino del sello).

Dos apariciones del mismo carácter JAMÁS deben ser idénticas, ni con una sola
variante en el banco: una mano nunca repite exactamente el mismo trazo. Se
deforma cada instancia con una malla 3×3 cuyos nodos no-esquina se desplazan
con una gaussiana truncada (~1.5% del alto): suficiente para romper el hash
perceptual, invisible como deformación a tamaño de lectura.

PIL puro (Image.transform MESH): cada celda destino (rectángulo regular)
muestrea un cuadrilátero FUENTE perturbado. Las esquinas quedan fijas para no
cambiar el tamaño ni mover el baseline (el interior se mueve <1px efectivo).
"""
from __future__ import annotations

import random

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

from core.inkcore.renderer_noise import tnorm


def elastic_warp(img: "Image.Image", rng: random.Random,
                 strength: float = 0.04, grid: int = 4) -> "Image.Image":
    """Deforma `img` con una malla grid×grid de nodos perturbados.

    ``strength`` es la amplitud máxima del desplazamiento como fracción del
    ALTO del glifo. ``grid`` = nodos por lado (4 → 3×3 celdas): una malla más
    fina deforma con más frecuencia espacial, que es lo que separa dos
    instancias ante un hash perceptual; una 3×3 sólo "respira" globalmente.
    Las esquinas quedan ancladas (mismo tamaño, baseline casi intacto: el
    interior se mueve, el marco no). Glifos <8px o strength<=0 pasan tal cual.
    """
    if not PIL_OK or strength <= 0:
        return img
    w, h = img.size
    if w < 8 or h < 8:
        return img
    n = max(2, int(grid)) - 1          # celdas por lado
    amp = strength * h
    xs = [w * i / n for i in range(n + 1)]
    ys = [h * i / n for i in range(n + 1)]

    def _node(ix: int, iy: int) -> tuple[float, float]:
        x, y = xs[ix], ys[iy]
        if ix in (0, n) or iy in (0, n):
            # TODO el borde anclado (no sólo esquinas): mover el contorno
            # desplazaría el bbox de tinta y metería ruido blanco en el
            # baseline y las alturas — justo lo que R3 correlacionó. La
            # deformación interior basta para romper el hash perceptual.
            return x, y
        return (x + tnorm(rng, 0.0, amp * 0.6, -amp, amp),
                y + tnorm(rng, 0.0, amp * 0.6, -amp, amp))

    nodes = {(ix, iy): _node(ix, iy)
             for iy in range(n + 1) for ix in range(n + 1)}
    mesh = []
    for iy in range(n):
        for ix in range(n):
            box = (int(xs[ix]), int(ys[iy]), int(xs[ix + 1]), int(ys[iy + 1]))
            # Orden del quad fuente en PIL: NW, SW, SE, NE.
            quad = (*nodes[(ix, iy)], *nodes[(ix, iy + 1)],
                    *nodes[(ix + 1, iy + 1)], *nodes[(ix + 1, iy)])
            mesh.append((box, quad))
    return img.transform((w, h), Image.MESH, mesh, resample=Image.BICUBIC)

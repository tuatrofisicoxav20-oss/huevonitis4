"""Fase R12 — RECONSTRUCCIÓN DE BORDE del glifo (textura de tinta por FRONTERA).

Sobre un alpha binarizado (interior 255 sólido), lo que delata la "impresión" no
vive en el interior del trazo sino en su BORDE: la impresión tiene un perímetro
matemáticamente limpio; la tinta humana sangra fibra a fibra en el papel, con un
contorno orgánicamente irregular. Este paso reconstruye ese borde.

MÉTODO (campo de distancia con signo, robusto a trazos finos):
  1. EROSIÓN/DILATACIÓN IRREGULAR DEL PERÍMETRO: se calcula la distancia con
     signo al borde (distanceTransform dentro − fuera) y se DESPLAZA el borde
     sumándole un campo de ruido COHERENTE DE BAJA FRECUENCIA, con sesgo hacia
     AFUERA (la tinta sangra hacia el papel). Como el borde es el cruce por cero
     de un campo suave, el desplazamiento es continuo a lo largo del perímetro
     (sin saltos, sin auto-intersección) — equivale a mover el contorno por su
     normal, pero sin la fragilidad de desplazar vértices en trazos de ~2 px.
     El ruido NO toca la opacidad interior (el núcleo satura a 255): no hay
     moteado, solo se reescribe la FRONTERA.
  2. FEATHER VARIABLE: el alpha sale de rampar la distancia con signo con un
     ancho de AA que VARÍA a lo largo del borde (segundo campo de baja
     frecuencia): más difuso donde la tinta "corrió", más duro donde la pluma
     "levantó". No es un blur uniforme ni despinta el núcleo.

INVARIANTE: el lienzo del glifo NO cambia de tamaño y el baseline no se mueve
(se procesa con padding interno y se recorta de vuelta al tamaño original), así
proporciones/métricas/espaciado del layout quedan intactos. Solo se reescribe el
canal alpha; el RGB se rellena con el color de tinta del propio glifo (mediana de
sus píxeles opacos) para que las protuberancias salgan en color, no en negro.

Es un patch aislado: si se borra este módulo y su llamada en renderer_glyph, el
render vuelve exactamente a R11.
"""
from __future__ import annotations

import random

import numpy as np

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False


def _noise2d(h: int, w: int, cell: float, rng: random.Random,
             aspect: float = 1.0) -> np.ndarray:
    """Campo (h, w) float32 en [-1, 1] de BAJA frecuencia: grid aleatorio chico
    (una celda ≈ ``cell`` px) interpolado BICUBIC al tamaño pedido. Suave en el
    espacio → el borde que define no salta pixel a pixel.

    ``aspect`` > 1 estira la celda en X (R15: campo de FIBRA del papel — las
    fibras corren alargadas, no en manchas redondas). 1.0 = isotrópico, con
    exactamente los mismos draws de RNG que antes de R15."""
    gw = max(2, int(w / max(2.0, cell * max(1.0, aspect))) + 2)
    gh = max(2, int(h / max(2.0, cell)) + 2)
    grid = np.array([[rng.uniform(-1.0, 1.0) for _ in range(gw)] for _ in range(gh)],
                    dtype=np.float32)
    im = Image.fromarray(((grid + 1.0) * 127.5).astype(np.uint8)).resize(
        (w, h), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 127.5 - 1.0


def reconstruct_glyph_edge(img, rng: random.Random, *, strength_px: float,
                           cell_px: float, feather_px: float,
                           feather_amount: float = 0.6,
                           outward_bias: float = 0.12,
                           feather_fiber_aspect: float = 1.0):
    """Devuelve una copia RGBA del glifo con el borde reconstruido (mismo tamaño).

    ``strength_px``: amplitud del desplazamiento del perímetro (px, a escala de
    render). ``cell_px``: longitud de onda del ruido (px) — a mayor valor, ondas
    más largas/suaves (baja frecuencia). ``feather_px``: ancho extra de AA donde
    la tinta "corrió". ``feather_amount``: 0..1, cuánto se aplica ese feather.
    Todos en la resolución (supersampleada) en que llega el glifo.
    """
    if not (_CV2 and _PIL) or strength_px <= 0:
        return img
    rgba = np.asarray(img.convert("RGBA"))
    H, W = rgba.shape[:2]
    a0 = rgba[..., 3]
    if a0.max() == 0:
        return img

    # Color de tinta del propio glifo (respeta el jitter HSV por glifo): mediana
    # del RGB en los píxeles bien opacos. Las protuberancias nuevas saldrán así.
    opaque = a0 > 200
    if opaque.sum() >= 4:
        ink_rgb = np.median(rgba[opaque][:, :3], axis=0).astype(np.uint8)
    elif (a0 > 0).any():
        ink_rgb = np.median(rgba[a0 > 0][:, :3], axis=0).astype(np.uint8)
    else:
        ink_rgb = np.array([26, 26, 46], np.uint8)

    # Amplitud acotada: nunca desplazar más que una fracción de la dimensión
    # menor del glifo (no romper trazos finos ni puntuación diminuta).
    amp = float(min(strength_px, 0.28 * min(H, W)))
    if amp <= 0:
        return img

    # Padding interno para que el sangrado tenga aire; se recorta de vuelta al
    # tamaño original (dimensiones/baseline INTACTOS).
    P = int(np.ceil(amp + feather_px + 2))
    a0p = cv2.copyMakeBorder(a0, P, P, P, P, cv2.BORDER_CONSTANT, value=0)
    Hp, Wp = a0p.shape
    m = (a0p > 127).astype(np.uint8)
    if m.sum() == 0 or m.sum() == m.size:
        return img

    # Distancia con signo al borde (px): >0 dentro del trazo, <0 fuera.
    din = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    dout = cv2.distanceTransform(1 - m, cv2.DIST_L2, 3)
    sd = din - dout

    # Desplazamiento del borde: ruido de baja frecuencia con SESGO OUTWARD (la
    # tinta crece hacia el papel; mordidas hacia adentro pequeñas → no severa).
    nf = _noise2d(Hp, Wp, cell_px, rng)
    bias = max(0.0, min(1.0, outward_bias))
    disp = (bias + (1.0 - bias) * nf) * amp
    new_sd = sd + disp

    # Feather VARIABLE: ancho de la rampa de AA modulado por un 2º campo suave.
    # alpha = clip(0.5 + sd/ancho): ancho chico → borde duro; ancho grande →
    # borde corrido. Base ~0.7 px (AA mínimo) + extra donde "corrió".
    if feather_amount > 0 and feather_px > 0:
        # R15: feather_fiber_aspect>1 = el campo que modula el ancho del
        # feather es de FIBRA (celdas alargadas en X): el sangrado corre
        # direccional por la fibra del papel, no como blur redondo. 1.0 =
        # comportamiento R12 exacto (mismos draws de RNG).
        fw = (_noise2d(Hp, Wp, cell_px * 0.8, rng,
                       aspect=feather_fiber_aspect) + 1.0) * 0.5  # 0..1
        width = 0.7 + float(feather_amount) * float(feather_px) * fw
    else:
        width = np.float32(0.7)
    alpha = np.clip(0.5 + new_sd / np.maximum(0.4, width), 0.0, 1.0)

    out_alpha = (alpha * 255.0).astype(np.uint8)[P:P + H, P:P + W]
    out = np.empty((H, W, 4), np.uint8)
    out[..., 0] = ink_rgb[0]
    out[..., 1] = ink_rgb[1]
    out[..., 2] = ink_rgb[2]
    out[..., 3] = out_alpha
    return Image.fromarray(out)

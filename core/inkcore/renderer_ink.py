"""Pase de tinta y papel del render (Fase R6 — D1/D2/D8/D10, I2 light).

La composición deja de ser un paste plano de color sólido:

  • value_noise_field: campo de ruido suave (grid aleatorio chico + resize
    BICUBIC — sin dependencia de Perlin) que modula el alpha DENTRO del
    trazo (D2): la tinta respira, no por letra (eso era el tell #5) sino por
    zona, como la carga real de un bolígrafo.
  • jitter_ink_color: micro-variación HSV del color por glifo (D1) — V±3%,
    S±4%: ninguna pluma deposita exactamente el mismo color dos veces.
  • apply_paper: compone la CAPA de tinta sobre el papel con MULTIPLY (D10):
    la tinta oscurece el papel y su textura se ve a través del trazo, en vez
    de taparlo con un color opaco. Sangrado opcional (D8): blur sub-píxel del
    alpha antes de componer.

separar tinta de papel (I2) es lo que permite que R7 cambie el papel sin
tocar la tinta y viceversa.
"""
from __future__ import annotations

import colorsys
import random

import numpy as np

try:
    from PIL import Image, ImageFilter
    PIL_OK = True
except ImportError:
    PIL_OK = False

from core.inkcore.renderer_noise import tnorm


def value_noise_field(w: int, h: int, rng: random.Random,
                      cell_px: int = 48, lo: float = 0.88,
                      hi: float = 1.0) -> np.ndarray:
    """Campo (h, w) float32 en [lo, hi]: ruido de baja frecuencia.

    Grid aleatorio de ~cell_px por celda interpolado con BICUBIC al tamaño de
    página — la frecuencia queda a escala de trazos/palabras, no de píxel.
    """
    gw = max(2, w // max(8, cell_px))
    gh = max(2, h // max(8, cell_px))
    grid = np.array([[rng.random() for _ in range(gw)] for _ in range(gh)],
                    dtype=np.float32)
    img = Image.fromarray(grid).resize((w, h), Image.BICUBIC)
    field = np.asarray(img, dtype=np.float32)
    field = np.clip(field, 0.0, 1.0)
    return lo + field * (hi - lo)


def jitter_ink_color(base_hex: str, rng: random.Random,
                     s_jitter: float = 0.04, v_jitter: float = 0.03) -> str:
    """Color de tinta con micro-variación HSV por glifo (D1). Devuelve hex."""
    from PIL import ImageColor
    try:
        r, g, b = ImageColor.getrgb(base_hex)[:3]
    except (ValueError, TypeError):
        r, g, b = (26, 26, 46)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if s_jitter > 0:
        s = min(1.0, max(0.0, s + tnorm(rng, 0.0, s_jitter * 0.6,
                                        -s_jitter, s_jitter)))
    if v_jitter > 0:
        v = min(1.0, max(0.0, v + tnorm(rng, 0.0, v_jitter * 0.6,
                                        -v_jitter, v_jitter)))
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r2 * 255):02x}{int(g2 * 255):02x}{int(b2 * 255):02x}"


def apply_paper(ink: Image.Image, paper: Image.Image, options,
                rng: random.Random) -> Image.Image:
    """Compone la capa de tinta (RGBA) sobre el papel (RGB) → página RGB.

    Pipeline: densidad intra-trazo (value noise sobre el alpha, D2) →
    sangrado (blur sub-píxel del alpha, D8) → composición MULTIPLY (D10).
    La identidad ``paper·(1-a) + paper·(tinta/255)·a = paper·(1-a·(1-t))``
    deja UN solo producto de página completa, y todo se opera únicamente
    sobre el bbox con tinta (los márgenes de una hoja son ~40% del área).
    """
    if not PIL_OK:
        return paper
    out = paper.convert("RGB")
    bbox = ink.getbbox()
    if bbox is None:
        return out
    # margen para que el bleed no se corte en el borde del bbox
    pad = int(4 + 2 * max(0.0, getattr(options, "ink_bleed", 0.0)))
    x0 = max(0, bbox[0] - pad)
    y0 = max(0, bbox[1] - pad)
    x1 = min(ink.width, bbox[2] + pad)
    y1 = min(ink.height, bbox[3] + pad)
    region = ink.crop((x0, y0, x1, y1))
    a = np.asarray(region.getchannel("A"), dtype=np.float32) / 255.0

    strength = max(0.0, getattr(options, "ink_texture_strength", 0.0))
    if strength > 0:
        # cell ∝ font_size: la "respiración" va a escala de trazo, y escala
        # sola con el supersampling (font_size ya viene multiplicado).
        cell = max(16, int(options.font_size * 1.2))
        field = value_noise_field(x1 - x0, y1 - y0, rng, cell_px=cell,
                                  lo=1.0 - strength, hi=1.0)
        a *= field

    bleed = max(0.0, getattr(options, "ink_bleed", 0.0))
    if bleed > 0:
        # Halo ADITIVO, no blur destructivo: el GaussianBlur directo resta
        # densidad al núcleo de los trazos finos (1-2 px) y, sumado al value
        # noise y al LANCZOS del supersampling, dejaba la tinta gris pálida.
        # El sangrado real EXPANDE el borde sin despintar el centro:
        # a = max(a, blur(a)·0.85).
        a_img = Image.fromarray((np.clip(a, 0.0, 1.0) * 255).astype(np.uint8))
        a_img = a_img.filter(ImageFilter.GaussianBlur(bleed))
        a_blur = np.asarray(a_img, dtype=np.float32) / 255.0
        np.maximum(a, a_blur * 0.85, out=a)

    p = np.asarray(out.crop((x0, y0, x1, y1)), dtype=np.float32)
    t = np.asarray(region.convert("RGB"), dtype=np.float32) / 255.0
    np.subtract(1.0, t, out=t)
    t *= a[..., None]
    np.subtract(1.0, t, out=t)
    p *= t
    out.paste(Image.fromarray(np.clip(p, 0.0, 255.0).astype(np.uint8)),
              (x0, y0))
    return out

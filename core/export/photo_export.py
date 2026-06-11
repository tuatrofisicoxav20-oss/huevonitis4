"""Export "📷 Foto de tarea" (Fase R7 — F4/F2/I4).

Una página renderizada perfecta delata su origen digital. Este export la hace
pasar por una FOTO de celular de la hoja: iluminación direccional (nadie
fotografía con luz perfectamente pareja), viñeta suave de lente, grano
gaussiano leve del sensor, y JPEG q=85 a resolución típica de cámara de
teléfono (~3000 px el lado largo) — los artefactos de compresión son parte
del disfraz.

Determinista: todo el ruido sale del rng inyectado (regla del proyecto).
El skew de la hoja NO se aplica aquí: es parte del render (scan_skew en
RenderOptions); el caller renderiza con esa opción y luego exporta.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

import numpy as np

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

logger = logging.getLogger(__name__)

PHOTO_LONG_SIDE = 3000
PHOTO_JPEG_QUALITY = 85


def _illumination_field(w: int, h: int, rng: random.Random) -> np.ndarray:
    """Gradiente de luz direccional + viñeta de lente, en [≈0.86, ≈1.06].

    La dirección de la luz es aleatoria (ventana/lámpara en cualquier lado);
    la viñeta oscurece esquinas como una lente real de celular.
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xx /= max(1, w - 1)
    yy /= max(1, h - 1)

    ang = rng.uniform(0.0, 2.0 * np.pi)
    # Proyección sobre la dirección de la luz, centrada: [-0.5, 0.5]
    proj = (xx - 0.5) * np.cos(ang) + (yy - 0.5) * np.sin(ang)
    strength = rng.uniform(0.05, 0.09)
    light = 1.0 + proj * 2.0 * strength  # ±strength extremo a extremo

    # Viñeta: caída radial suave hacia las esquinas (hasta -8%).
    r2 = (xx - 0.5) ** 2 + (yy - 0.5) ** 2   # 0 centro, 0.5 esquina
    vignette = 1.0 - (r2 / 0.5) * rng.uniform(0.05, 0.08)

    return light * vignette


def export_photo(page: Image.Image, path: str | Path,
                 rng: random.Random | None = None,
                 long_side: int = PHOTO_LONG_SIDE,
                 quality: int = PHOTO_JPEG_QUALITY) -> Path:
    """Guarda una página como JPEG estilo "foto de celular". Devuelve el path."""
    if not PIL_OK:
        raise RuntimeError("Pillow no disponible para exportar foto")
    rng = rng or random.Random()
    path = Path(path)

    img = page.convert("RGB")
    # Resolución de cámara de teléfono: lado largo ~3000 px.
    scale = long_side / max(img.size)
    if abs(scale - 1.0) > 0.01:
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)

    arr = np.asarray(img, dtype=np.float32)
    field = _illumination_field(img.width, img.height, rng)
    arr *= field[..., None]

    # Grano del sensor: gaussiano leve por píxel. Generador numpy seedeado
    # desde el rng inyectado (determinismo sin pagar el loop Python).
    np_rng = np.random.default_rng(rng.getrandbits(32))
    arr += np_rng.normal(0.0, 2.2, size=arr.shape).astype(np.float32)

    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, "JPEG", quality=quality, optimize=True)
    return path


def export_photo_pages(pages: list, base_path: str | Path,
                       rng: random.Random | None = None) -> list[Path]:
    """Exporta N páginas como fotos: base.jpg o base_p1.jpg, base_p2.jpg…"""
    rng = rng or random.Random()
    base = Path(base_path)
    stem = base.with_suffix("")
    paths: list[Path] = []
    for i, page in enumerate(pages, start=1):
        out = base if len(pages) == 1 else Path(f"{stem}_p{i}.jpg")
        paths.append(export_photo(page, out.with_suffix(".jpg"), rng))
    return paths

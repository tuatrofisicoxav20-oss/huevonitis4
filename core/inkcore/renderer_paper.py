"""Pase de papel del render (Fase R7 — F1/F3): textura y skew de escaneo.

El papel deja de ser un color hex plano:

  • make_paper: construye la hoja RGB del tamaño pedido — color base del
    estilo + textura opcional. La textura se busca primero en los papeles del
    usuario (``tipografia/{profile}/papers/``) y luego en ``assets/papers/``
    (procedurales, generadas por ``tools/gen_paper_textures.py``). Se tilea
    con espejo en los bordes para no mostrar costuras y se mezcla MUY sutil
    (la textura modula la luminancia, no pinta encima).
  • generate_paper_texture: value noise multi-octava + fibras finas — el
    generador procedural compartido con el script de assets (sin descargar
    imágenes, regla del proyecto).
  • apply_scan_skew: rotación global sub-grado de la página final (F3) con
    las esquinas rellenas del color del papel (sin bordes negros).

Separado de renderer_backgrounds para mantener cada módulo bajo ~420 líneas:
backgrounds dibuja DECORACIONES (renglones/margen); este módulo fabrica el
SUSTRATO (color+textura) y el artefacto de escaneo.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

import numpy as np

try:
    from PIL import Image, ImageOps
    PIL_OK = True
except ImportError:
    PIL_OK = False

from core.inkcore.renderer_noise import tnorm

logger = logging.getLogger(__name__)

# Caché de texturas abiertas (path → PIL "L"). Las páginas de un documento
# reutilizan la misma textura; reabrir el PNG por página sería puro I/O.
_TEXTURE_CACHE: dict[str, Image.Image] = {}
_TEXTURE_CACHE_MAX = 6


def generate_paper_texture(w: int, h: int, rng: random.Random,
                           fibers: int = 140, octaves: int = 3) -> Image.Image:
    """Textura de papel procedural en escala de grises (~128 = neutro).

    Value noise multi-octava (grid chico + BICUBIC, igual que la tinta de R6)
    para el grano, más "fibras": segmentos finos de celulosa con opacidad
    bajísima. El resultado modula luminancia alrededor de 128, así el mismo
    PNG sirve para papel blanco, crema o cuadriculado.
    """
    acc = np.zeros((h, w), dtype=np.float32)
    amp_total = 0.0
    for octave in range(octaves):
        cell = max(8, 96 >> octave)          # 96, 48, 24 px por celda
        amp = 1.0 / (2 ** octave)            # cada octava aporta la mitad
        gw, gh = max(2, w // cell), max(2, h // cell)
        grid = np.array([[rng.random() for _ in range(gw)] for _ in range(gh)],
                        dtype=np.float32)
        layer = Image.fromarray(grid).resize((w, h), Image.BICUBIC)
        acc += np.asarray(layer, dtype=np.float32) * amp
        amp_total += amp
    acc /= amp_total                          # [0,1] aprox

    # Centrar en 128 con un rango de luminancia MUY sutil (±6 niveles).
    tex = 128.0 + (acc - 0.5) * 12.0

    img = Image.fromarray(np.clip(tex, 0, 255).astype(np.uint8))

    # Fibras de celulosa: segmentos cortos casi invisibles en ángulos al azar.
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    for _ in range(fibers):
        x0 = rng.uniform(0, w)
        y0 = rng.uniform(0, h)
        length = rng.uniform(6, 22)
        ang = rng.uniform(0, 3.14159)
        x1 = x0 + length * np.cos(ang)
        y1 = y0 + length * np.sin(ang)
        shade = 128 + rng.choice((-9, -7, 7, 9))
        draw.line([(x0, y0), (x1, y1)], fill=int(shade), width=1)
    return img


def _load_texture(name: str, profile_dir: Path | None) -> Image.Image | None:
    """Resuelve una textura por nombre: papers del usuario > assets/papers."""
    candidates = []
    if profile_dir is not None:
        candidates.append(Path(profile_dir) / "papers" / name)
    candidates.append(Path(__file__).resolve().parents[2] / "assets" / "papers" / name)
    for path in candidates:
        key = str(path)
        if key in _TEXTURE_CACHE:
            return _TEXTURE_CACHE[key]
        if path.exists():
            try:
                with Image.open(path) as f:
                    tex = f.convert("L")
                if len(_TEXTURE_CACHE) >= _TEXTURE_CACHE_MAX:
                    _TEXTURE_CACHE.pop(next(iter(_TEXTURE_CACHE)))
                _TEXTURE_CACHE[key] = tex
                return tex
            except Exception as exc:
                logger.warning("Textura de papel ilegible %s: %s", path, exc)
    return None


def _tile_to(tex: Image.Image, w: int, h: int) -> np.ndarray:
    """Tilea la textura a (h, w) con espejo alternado (sin costuras visibles)."""
    tw, th = tex.size
    arr = np.asarray(tex, dtype=np.float32)
    cols = -(-w // tw)   # ceil
    rows = -(-h // th)
    strips = []
    for r in range(rows):
        row = []
        a = arr[::-1, :] if (r % 2) else arr
        for c in range(cols):
            row.append(a[:, ::-1] if (c % 2) else a)
        strips.append(np.concatenate(row, axis=1))
    return np.concatenate(strips, axis=0)[:h, :w]


def make_paper(size: tuple[int, int], options, rng: random.Random,
               profile_dir: Path | None = None) -> Image.Image:
    """Hoja RGB: color base del estilo + textura sutil si está configurada.

    La textura (L, ~128 neutro) modula la luminancia del color base:
    ``papel = base · (tex/128)`` acotado — el grano respeta el tinte del
    papel (crema sigue crema). Sin textura: color sólido (cero costo).
    """
    if not PIL_OK:
        return None
    base = Image.new("RGB", size, options.background_color)
    name = getattr(options, "paper_texture", None)
    if not name:
        return base
    tex = _load_texture(name, profile_dir)
    if tex is None:
        logger.info("make_paper: textura %r no encontrada; papel liso", name)
        return base
    w, h = size
    field = _tile_to(tex, w, h) / 128.0
    # ATENUAR la modulación: el grano de papel real a 150 dpi es CASI
    # invisible. Con la textura cruda (±7%) la hoja salía con "nubes de
    # humedad" y el tile espejado se percibía repetido (visto en golden R7);
    # al 35% de la señal y acotado a ±2.5% queda subliminal — se siente la
    # materia sin verse el patrón.
    field = 1.0 + (field - 1.0) * 0.35
    field = np.clip(field, 0.975, 1.025)
    arr = np.asarray(base, dtype=np.float32) * field[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def apply_scan_skew(page: Image.Image, options, rng: random.Random) -> Image.Image:
    """Rotación global sub-grado de la página final (F3 — skew de escaneo).

    Nadie alinea la hoja perfecto contra el escáner/cámara. Esquinas rellenas
    del color del papel (fillcolor), no negras ni transparentes. BICUBIC: a
    <1.2° el muestreo es casi 1:1 y no ensucia la tinta ya compuesta.
    """
    if not PIL_OK or not getattr(options, "scan_skew", False):
        return page
    angle = tnorm(rng, 0.0, 0.5, -1.2, 1.2)
    if abs(angle) < 0.02:
        return page
    return page.rotate(angle, resample=Image.BICUBIC, expand=False,
                       fillcolor=options.background_color)

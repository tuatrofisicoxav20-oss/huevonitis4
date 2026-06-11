"""Genera las texturas de papel procedurales de assets/papers/ (Fase R7, F1).

Uso: python tools/gen_paper_textures.py

Produce 3 PNG en escala de grises (~128 = neutro) que make_paper modula sobre
el color base del estilo. Seeds fijas: regenerarlas da bytes idénticos (regla
de determinismo del proyecto). NO se descargan imágenes: value noise + fibras
(generate_paper_texture, el mismo generador que usa el renderer).

  papel_fibra.png     — grano fino con fibras visibles (hoja blanca común)
  papel_crema.png     — grano suave, pocas fibras (libreta crema)
  papel_reciclado.png — grano grueso multi-octava y muchas fibras (kraft)
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.inkcore.renderer_paper import generate_paper_texture  # noqa: E402

# Tamaño del tile: se repite con espejo en make_paper, así que no necesita
# cubrir una página completa; 512 px mantiene los PNG en ~100-200 KB.
TILE = 512

SPECS = [
    ("papel_fibra.png",     1001, {"fibers": 170, "octaves": 3}),
    ("papel_crema.png",     2002, {"fibers":  60, "octaves": 2}),
    ("papel_reciclado.png", 3003, {"fibers": 320, "octaves": 4}),
]


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "assets" / "papers"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, seed, kw in SPECS:
        rng = random.Random(seed)
        tex = generate_paper_texture(TILE, TILE, rng, **kw)
        path = out_dir / name
        tex.save(path, "PNG", optimize=True)
        print(f"{path}  ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

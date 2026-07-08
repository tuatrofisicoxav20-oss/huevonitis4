"""R15 — evaluación de tinta en espacio de trazo (criterios de aceptación).

1. Zoom 400%: renderiza 'a' y 'g' del banco real a 4× el font_size normal,
   baseline (R12/R14: master off + ink_boost 0.7) vs R15 (defaults), lado a
   lado → r15_zoom_a.png / r15_zoom_g.png. A ese zoom el trazo R15 debe
   verse con densidad y ancho variables + textura direccional, no un slab
   plano con borde ruidoso.
2. Regresión de legibilidad tesseract (mismo protocolo que r14_eval): el
   acierto con R15 ON no puede caer más de ~3 pts vs el baseline pre-R14.

Uso:  python -m tools.eval_render.r15_eval [--profile default] [--seed 1234]
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from tools.eval_render.r14_eval import KNOBS_OFF, TEXTO, _ocr_accuracy

# Rollback R15: master off + los dos defaults que R15 movió.
R15_OFF = dict(ink_stroke_space=False, ink_boost=0.7, pen_skip_prob=0.0)


def _zoom_glyph(renderer, ch: str, opts) -> object:
    """Glifo suelto a 4× vía _load_glyph (la misma ruta del render real)."""
    entry = renderer._select_entry(ch)
    if entry is None:
        raise SystemExit(f"el banco no tiene glifo para {ch!r}")
    out = renderer._load_glyph(entry.image_path, opts, ch,
                               geo=renderer._geo(entry), rotation=0.0,
                               rng=random.Random(11))
    if out is None:
        raise SystemExit(f"no se pudo cargar el glifo {ch!r}")
    return out[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args()

    from PIL import Image

    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions

    out_dir = Path(__file__).parent
    bank = GlyphBank(profile=args.profile) if args.profile else GlyphBank()
    r = HandwritingRenderer(bank)

    base_fs = RenderOptions().font_size
    for ch in ("a", "g"):
        panes = []
        for label, kw in (("baseline", R15_OFF), ("r15", {})):
            opts = RenderOptions(seed=args.seed, font_size=base_fs * 4,
                                 supersample=1, warp_strength=0.0,
                                 size_variation=0.0, rotation_range=0.0,
                                 glyph_slant_drift_deg=0.0, **kw)
            r._begin_render(opts)
            panes.append(_zoom_glyph(r, ch, opts))
        w = sum(p.width for p in panes) + 60
        h = max(p.height for p in panes) + 40
        sheet = Image.new("RGB", (w, h), (245, 243, 238))
        x = 20
        for p in panes:
            sheet.paste(p, (x, 20), p)
            x += p.width + 20
        path = out_dir / f"r15_zoom_{ch}.png"
        sheet.save(path)
        print(f"zoom 400% {ch!r}: {path.name} (izq baseline / der R15)")

    print("\nregresión de legibilidad (tesseract spa)…")
    base = r.render_pages(TEXTO, RenderOptions(seed=args.seed, **KNOBS_OFF,
                                               **{k: v for k, v in R15_OFF.items()
                                                  if k not in KNOBS_OFF}))[0]
    r15 = r.render_pages(TEXTO, RenderOptions(seed=args.seed))[0]
    base.save(out_dir / "r15_ocr_base.png")
    r15.save(out_dir / "r15_ocr_on.png")
    acc_base = _ocr_accuracy(out_dir / "r15_ocr_base.png", TEXTO)
    acc_r15 = _ocr_accuracy(out_dir / "r15_ocr_on.png", TEXTO)
    (out_dir / "r15_ocr_base.png").unlink()
    (out_dir / "r15_ocr_on.png").unlink()
    delta = (acc_base - acc_r15) * 100
    print(f"  baseline pre-R14 : {acc_base * 100:5.1f}%")
    print(f"  R14+R15 defaults : {acc_r15 * 100:5.1f}%  (Δ {delta:+.1f} pts)")
    if delta > 3.0:
        print("FALLA: la legibilidad cayó más de 3 puntos — ajustar clamps.")
        return 1
    print("OK: la legibilidad se mantiene dentro del margen (≤3 pts).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

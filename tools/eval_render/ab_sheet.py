"""Hoja A/B para el mini test de Turing casero (Fase R9 — H1/H6).

Recibe una página manuscrita REAL y un texto; renderiza el sintético con el
banco del perfil y arma un PNG con tiras de ambas BARAJADAS, etiquetadas con
números neutros. El mapa tira→origen va a un JSON APARTE: se lo muestras a
5-10 personas sin el mapa y anotas aciertos. Meta del proyecto: ≤60% de
acierto (50% = indistinguible de tu letra).

CLI:
    python -m tools.eval_render.ab_sheet real.png "texto a renderizar" \
        --out hoja_ab.png [--profile default] [--seed 7] [--strips 5]
"""
from __future__ import annotations

import argparse
import json
import random
import sys

try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except ImportError:
    PIL_OK = False

# Geometría de la hoja A/B: tiras apiladas con una franja de etiqueta.
_LABEL_W = 56
_GAP = 14
_BG = "#E8E8E8"


def _strips_from(img: Image.Image, n: int, strip_h: int,
                 width: int) -> list:
    """`n` tiras horizontales del centro de la imagen, normalizadas a width."""
    img = img.convert("RGB")
    if img.width != width:
        scale = width / img.width
        img = img.resize((width, max(1, round(img.height * scale))),
                         Image.LANCZOS)
    usable = img.height - strip_h
    if usable <= 0:
        return [img.crop((0, 0, width, img.height))] * n
    out = []
    for i in range(n):
        # Tiras repartidas a lo alto (evita repetir siempre el mismo renglón).
        y = round(usable * (i + 0.5) / n)
        out.append(img.crop((0, y, width, y + strip_h)))
    return out


def build_ab_sheet(real_img: Image.Image, synth_img: Image.Image,
                   rng: random.Random, n_strips: int = 5,
                   strip_h: int = 110, width: int = 1000):
    """Construye (hoja, mapa): tiras reales y sintéticas barajadas.

    El mapa es {"1": "real" | "synth", ...} en el orden vertical de la hoja.
    """
    pairs = ([("real", s) for s in _strips_from(real_img, n_strips, strip_h, width)]
             + [("synth", s) for s in _strips_from(synth_img, n_strips, strip_h, width)])
    rng.shuffle(pairs)
    total_h = len(pairs) * (strip_h + _GAP) + _GAP
    sheet = Image.new("RGB", (width + _LABEL_W, total_h), _BG)
    draw = ImageDraw.Draw(sheet)
    mapping: dict[str, str] = {}
    y = _GAP
    for i, (origin, strip) in enumerate(pairs, start=1):
        draw.text((14, y + strip_h // 2 - 8), f"{i:02d}", fill="#333333")
        sheet.paste(strip, (_LABEL_W, y))
        draw.rectangle((_LABEL_W, y, width + _LABEL_W - 1, y + strip_h - 1),
                       outline="#BBBBBB")
        mapping[str(i)] = origin
        y += strip_h + _GAP
    return sheet, mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hoja A/B real-vs-sintético para el mini test de Turing.")
    parser.add_argument("real", help="página manuscrita real (PNG/JPG)")
    parser.add_argument("texto", help="texto a renderizar con tu letra")
    parser.add_argument("--out", default="hoja_ab.png")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--strips", type=int, default=5)
    args = parser.parse_args(argv)
    if not PIL_OK:
        print("PIL no disponible")
        return 1

    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions

    bank = GlyphBank(args.profile)
    renderer = HandwritingRenderer(bank)
    opts = RenderOptions.from_calibration(
        bank.bank_dir, style="", background_style="hoja_blanca", seed=args.seed)
    pages = renderer.render_pages(args.texto, opts)
    if not pages:
        print("el render no produjo páginas (¿banco vacío?)")
        return 1
    missing = renderer.last_missing_chars()
    if missing:
        print(f"⚠ sin glifo (omitidos): {' '.join(sorted(missing))}")

    with Image.open(args.real) as f:
        real = f.copy()
    rng = random.Random(args.seed)
    sheet, mapping = build_ab_sheet(real, pages[0], rng, n_strips=args.strips)
    sheet.save(args.out)
    map_path = str(args.out).rsplit(".", 1)[0] + "_mapa.json"
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"hoja A/B → {args.out}")
    print(f"mapa (NO lo muestres) → {map_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

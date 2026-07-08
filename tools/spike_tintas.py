"""Spike H5-C3 (F3b) — recoloreo de tintas conservando textura. NO integra nada.

Toma 5 glifos REALES del banco activo y los recolorea a azul/rojo/verde
mapeando la DENSIDAD de tinta a la rampa de valor del color destino, con el
canal alpha INTACTO. Genera una hoja comparativa (original / azul / rojo /
verde a 200% y 400%) para el veredicto GO/NO-GO de SPIKE_TINTAS.md.

Los glifos del banco son RGBA con RGB blanco plano: toda la textura de
densidad vive en el ALPHA (el extractor guarda la forma ahí). La densidad se
deriva entonces del alpha; si un banco futuro trajera RGB con información
(escaneo a color), se usaría la luminancia invertida. El recoloreo actual del
pipeline (_recolor_ink) pinta un RGB PLANO — la comparación de esta hoja es
exactamente "plano vs rampa de densidad".

Uso:  python -m tools.spike_tintas [--perfil default] [--out "muestras /tintas_spike"]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw

# Chars objetivo: cuerpos con trazo variado (curvas, astas, colas). Si el
# banco no tiene alguno, se completa con lo que haya.
_CHARS_PREFERIDOS = ["a", "e", "m", "q", "t"]

# Tintas destino: (nombre, tono claro = tinta poco cargada, tono oscuro =
# tinta apozada). La rampa va de claro→oscuro según densidad local.
_TINTAS = [
    ("azul", "#4A63B8", "#0B1A52"),
    ("rojo", "#C4525C", "#7A0E18"),
    ("verde", "#4E9668", "#0E4D28"),
]
_ORIGINAL_INK = "#1A1A2E"  # ink_color default del render actual (plano)


def _densidad(img: Image.Image) -> np.ndarray:
    """Densidad de tinta por píxel en [0,1]. Banco actual: RGB blanco plano →
    la densidad ES el alpha. RGB con señal (std>2 dentro de tinta): luminancia
    invertida ponderada por alpha."""
    a = np.asarray(img.getchannel("A"), dtype=np.float64) / 255.0
    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    lum = rgb @ (0.299, 0.587, 0.114)
    ink = a > 0.15
    if ink.any() and lum[ink].std() > 2.0:
        return (1.0 - lum / 255.0) * a
    return a


def recolor_rampa(img: Image.Image, claro: str, oscuro: str) -> Image.Image:
    """Recolorea mapeando densidad→rampa claro→oscuro. Alpha INTACTO."""
    d = _densidad(img)[..., None]                     # (h, w, 1) en [0,1]
    c0 = np.asarray(ImageColor.getrgb(claro)[:3], dtype=np.float64)
    c1 = np.asarray(ImageColor.getrgb(oscuro)[:3], dtype=np.float64)
    rgb = (c0 * (1.0 - d) + c1 * d).round().astype(np.uint8)
    out = np.dstack([rgb, np.asarray(img.getchannel("A"))])
    return Image.fromarray(out)  # uint8 ×4 canales → RGBA


def recolor_plano(img: Image.Image, color: str) -> Image.Image:
    """Recoloreo PLANO como el pipeline actual (referencia 'original')."""
    r, g, b = ImageColor.getrgb(color)[:3]
    flat = Image.new("RGBA", img.size, (r, g, b, 0))
    flat.putalpha(img.getchannel("A"))
    return flat


def _sobre_blanco(img: Image.Image, zoom: int) -> Image.Image:
    """Composición sobre papel blanco al zoom pedido (NEAREST: píxel honesto)."""
    base = Image.new("RGBA", img.size, (255, 255, 255, 255))
    base.alpha_composite(img)
    w, h = base.size
    return base.convert("RGB").resize((w * zoom, h * zoom), Image.NEAREST)


def _elegir_glifos(bank) -> list:
    entries = []
    for ch in _CHARS_PREFERIDOS:
        cands = bank.get_all(ch)
        if cands:
            entries.append(cands[0])
    if len(entries) < 5:
        vistos = {e.char for e in entries}
        for e in bank.get_all():
            if e.char not in vistos and len(e.char) == 1 and e.char.isalpha():
                entries.append(e)
                vistos.add(e.char)
            if len(entries) == 5:
                break
    return entries[:5]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--perfil", default=None)
    parser.add_argument("--out", default="muestras /tintas_spike")
    args = parser.parse_args(argv)

    from core.inkcore.bank import GlyphBank
    bank = GlyphBank(args.perfil)
    entries = _elegir_glifos(bank)
    if len(entries) < 5:
        print(f"banco insuficiente: solo {len(entries)} glifos utilizables")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cols = ["original (plano)"] + [f"{n} (rampa)" for n, _, _ in _TINTAS]
    pad, label_h = 14, 26
    for zoom in (2, 4):
        celdas: list[list[Image.Image]] = []
        for e in entries:
            with Image.open(e.image_path) as im:
                g = im.convert("RGBA")
            fila = [_sobre_blanco(recolor_plano(g, _ORIGINAL_INK), zoom)]
            fila += [_sobre_blanco(recolor_rampa(g, c0, c1), zoom)
                     for _n, c0, c1 in _TINTAS]
            celdas.append(fila)
        col_w = [max(f[j].width for f in celdas) for j in range(4)]
        row_h = [max(c.height for c in f) for f in celdas]
        W = sum(col_w) + pad * 5
        H = sum(row_h) + pad * 6 + label_h
        hoja = Image.new("RGB", (W, H), "#FFFFFF")
        d = ImageDraw.Draw(hoja)
        x = pad
        for j, name in enumerate(cols):
            d.text((x, pad), name, fill="#333333")
            x += col_w[j] + pad
        y = pad + label_h
        for i, fila in enumerate(celdas):
            x = pad
            for j, c in enumerate(fila):
                hoja.paste(c, (x, y))
                x += col_w[j] + pad
            d.text((pad, y + row_h[i] - 14), f"'{entries[i].char}'",
                   fill="#888888")
            y += row_h[i] + pad
        dest = out_dir / f"hoja_comparativa_{zoom * 100}pct.png"
        hoja.save(dest)
        print(f"hoja {zoom * 100}% → {dest}")

    # Sanidad numérica del contrato "alpha intacto" + textura viva en el color.
    with Image.open(entries[0].image_path) as im:
        g = im.convert("RGBA")
    rec = recolor_rampa(g, *_TINTAS[0][1:])
    a0 = np.asarray(g.getchannel("A"))
    a1 = np.asarray(rec.getchannel("A"))
    ink = a0 > 40
    v = np.asarray(rec.convert("RGB"), dtype=np.float64)[ink] @ (0.299, 0.587, 0.114)
    aa = float(((a0 > 0) & (a0 < 255)).sum()) / max(1, int((a0 > 0).sum()))
    print(f"alpha intacto: {bool((a0 == a1).all())}; "
          f"std de valor dentro de tinta: {v.std():.1f} (plano seria 0.0); "
          f"fraccion de alpha intermedio (antialiasing): {aa:.2%}")

    # HOJA 2 — pipeline REAL: el alpha del banco es casi binario (la textura
    # de tinta se sintetiza en render: ink_boost + R11 + R12, todos agnósticos
    # al tono), así que la prueba de verdad es renderizar una palabra completa
    # con ink_color en cada tinta por el pipeline existente — ink_color YA es
    # perilla; aquí no se integra nada nuevo.
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions
    hw = HandwritingRenderer(bank)
    colores = [("original", _ORIGINAL_INK)] + [(n, osc) for n, _c, osc in _TINTAS]
    tiles = []
    for nombre, hexcolor in colores:
        opts = RenderOptions(style="", background_style="blanco_liso",
                             seed=42, ink_color=hexcolor)
        page = hw.render_pages("la tinta viva", opts)[0]
        gray = np.asarray(page.convert("L"))
        ys, xs = np.nonzero(gray < 200)
        if len(xs):
            m = 8
            page = page.crop((max(0, xs.min() - m), max(0, ys.min() - m),
                              min(page.width, xs.max() + m),
                              min(page.height, ys.max() + m)))
        tiles.append((nombre, page))
    for zoom in (2, 4):
        tw = max(t.width for _n, t in tiles) * zoom
        th = max(t.height for _n, t in tiles) * zoom
        hoja = Image.new("RGB", (tw + 2 * pad, (th + label_h + pad) * 4 + pad),
                         "#FFFFFF")
        d = ImageDraw.Draw(hoja)
        y = pad
        for nombre, t in tiles:
            d.text((pad, y), f"{nombre} - pipeline real (R11+R12 activos)",
                   fill="#333333")
            y += label_h
            hoja.paste(t.resize((t.width * zoom, t.height * zoom),
                                Image.NEAREST), (pad, y))
            y += th + pad
        dest = out_dir / f"pipeline_real_{zoom * 100}pct.png"
        hoja.save(dest)
        print(f"hoja pipeline real {zoom * 100}% → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

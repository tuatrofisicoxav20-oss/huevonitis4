"""R16 — export_svg: texto con la letra del usuario -> SVG de TRAZOS para plotter.

Emite un SVG en milímetros 1:1 (papel carta) donde cada polilínea del esqueleto
del glifo es un ``<path>`` (pluma-abajo); el hueco entre paths = pluma-arriba.
Pensado para AxiDraw / GRBL: se rasteriza/plotea a tamaño físico real.

Reusa la GEOMETRÍA FÍSICA de RenderOptions (papel, márgenes en mm, line_spacing_mm
= alto del em, line_height, word/letter spacing) para que la escala coincida con
el render raster. La variación humana (elección de variante, slant, baseline
drift) sale toda del ``seed`` inyectado → mismo seed ⇒ SVG idéntico (regla dura).

Ruta NUEVA y AISLADA: solo LEE el banco vía StrokeBank; no toca nada más.
"""
from __future__ import annotations

import math
import random
import xml.sax.saxutils as _xml

from core.inkcore.plotter.vectorize import StrokeBank, load_stroke_glyph

PAPER_MM = {"letter": (215.9, 279.4), "a4": (210.0, 297.0)}
MM_PER_IN = 25.4


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


class _Cursor:
    __slots__ = ("baseline", "line", "x")

    def __init__(self, x, baseline):
        self.x = x
        self.baseline = baseline
        self.line = 0


def build_stroke_paths(text: str, options, bank: StrokeBank,
                       paper: str = "letter") -> dict:
    """Devuelve {'paper_mm':(w,h), 'polylines_mm':[[(x,y),...],...],
    'missing':[chars]} — polilíneas ya colocadas en mm de página."""
    seed = getattr(options, "seed", None)
    rng = random.Random(seed if seed is not None else 0)

    em_mm = float(options.line_spacing_mm)              # el em en mm
    line_adv = em_mm * float(options.line_height)
    left_mm = options.margin_left_px / options.render_dpi * MM_PER_IN
    right_mm = options.margin_right_px / options.render_dpi * MM_PER_IN
    top_mm = float(options.margin_top_mm)
    w_mm, h_mm = PAPER_MM.get(paper, PAPER_MM["letter"])
    usable = w_mm - left_mm - right_mm

    slant0 = math.radians(float(getattr(options, "slant_deg", 0.0)))
    line_slant_amp = math.radians(float(getattr(options, "line_slant_deg", 0.0)))
    drift_amp_mm = float(getattr(options, "baseline_drift", 0.0)) / options.render_dpi * MM_PER_IN
    word_gap = em_mm * float(options.word_space_frac)
    letter_gap = em_mm * float(options.letter_gap_frac)

    polylines: list[list[tuple[float, float]]] = []
    missing: list[str] = []
    cur = _Cursor(left_mm, top_mm + em_mm)
    # deriva lenta de baseline y slant por línea (OU acotado, determinista)
    line_slant = 0.0
    drift = 0.0

    def newline():
        nonlocal line_slant, drift
        cur.line += 1
        cur.x = left_mm
        cur.baseline = top_mm + em_mm + cur.line * line_adv
        line_slant = max(-line_slant_amp, min(line_slant_amp,
                         line_slant + rng.uniform(-0.4, 0.4) * line_slant_amp))
        drift = 0.0

    for raw_line in text.split("\n"):
        for word in raw_line.split(" "):
            # medir ancho aproximado de la palabra para wrap
            entries_w = []
            wsum = 0.0
            for ch in word:
                g = _pick(bank, ch, rng)
                entries_w.append((ch, g))
                wsum += (g["adv_em"] * em_mm + letter_gap) if g else word_gap * 0.6
            if cur.x + wsum > left_mm + usable and cur.x > left_mm:
                newline()
            for ch, g in entries_w:
                if g is None:
                    if ch not in missing and not ch.isspace():
                        missing.append(ch)
                    cur.x += word_gap * 0.6
                    continue
                # micro-drift de baseline por glifo (deriva acotada)
                drift = max(-drift_amp_mm, min(drift_amp_mm,
                        drift + rng.uniform(-0.5, 0.5) * drift_amp_mm))
                slant = slant0 + line_slant
                bx, by = cur.x, cur.baseline + drift
                for stroke in g["strokes"]:
                    poly = []
                    for xe, ye in stroke:
                        xs = xe - ye * math.tan(slant)     # shear (italic)
                        poly.append((bx + xs * em_mm, by + ye * em_mm))
                    if len(poly) >= 1:
                        polylines.append(poly)
                cur.x += g["adv_em"] * em_mm + letter_gap
            cur.x += word_gap
        newline()

    return {"paper_mm": (w_mm, h_mm), "polylines_mm": polylines, "missing": missing}


_TIER_RANK = {"Gold": 0, "Silver": 1, "Bronze": 2}


def _pick(bank: StrokeBank, ch: str, rng: random.Random) -> dict | None:
    """Elige una variante del banco para ch (o su minúscula) y la vectoriza.

    Prefiere el mejor tier disponible (Gold>Silver>Bronze), igual que el raster,
    para no caer en variantes mal extraídas; dentro del tier elige al azar
    (variación humana) con el rng inyectado. Descarta esqueletos degenerados
    (glifos que colapsan a <2 puntos, p.ej. una 'o' rellena mal extraída).
    """
    if ch.isspace():
        return None
    for c in (ch, ch.lower()):
        ents = bank.by_char.get(c)
        if not ents:
            continue
        best = min(_TIER_RANK.get(e.get("tier", "Bronze"), 3) for e in ents)
        pool = [i for i, e in enumerate(ents)
                if _TIER_RANK.get(e.get("tier", "Bronze"), 3) == best]
        rng.shuffle(pool)
        for idx in pool:
            try:
                g = load_stroke_glyph(c, bank, idx)
            except Exception:
                continue
            n_pts = sum(len(s) for s in g.get("strokes", []))
            if g.get("strokes") and n_pts >= 2:
                return g
        return None
    return None


def export_svg(text: str, options, bank: StrokeBank, out_path: str,
               paper: str = "letter", dry_run: bool = False) -> dict:
    """Escribe el SVG de trazos. dry_run=True emite SOLO los saltos pluma-arriba
    (líneas punteadas) para previsualizar el recorrido. Devuelve el dict de
    build_stroke_paths + 'out_path' y 'n_paths'."""
    data = build_stroke_paths(text, options, bank, paper)
    w, h = data["paper_mm"]
    polys = data["polylines_mm"]

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(w)}mm" height="{_fmt(h)}mm" '
        f'viewBox="0 0 {_fmt(w)} {_fmt(h)}">',
        f'<!-- Huevonitis R16 plotter export — {len(polys)} trazos, '
        f'seed={getattr(options, "seed", None)} -->',
    ]
    if dry_run:
        # recorrido pluma-arriba: del fin de un trazo al inicio del siguiente
        parts.append('<g fill="none" stroke="#c00" stroke-width="0.15" '
                     'stroke-dasharray="0.8 0.8">')
        prev = None
        for poly in polys:
            if prev is not None and poly:
                parts.append(f'<path d="M {_fmt(prev[0])} {_fmt(prev[1])} '
                             f'L {_fmt(poly[0][0])} {_fmt(poly[0][1])}"/>')
            if poly:
                prev = poly[-1]
        parts.append("</g>")
    else:
        parts.append('<g fill="none" stroke="#0B1A52" stroke-width="0.35" '
                     'stroke-linecap="round" stroke-linejoin="round">')
        for poly in polys:
            if not poly:
                continue
            if len(poly) == 1:
                x, y = poly[0]
                parts.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="0.2"/>')
                continue
            d = "M " + " L ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in poly)
            parts.append(f'<path d="{_xml.escape(d)}"/>')
        parts.append("</g>")
    parts.append("</svg>\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    data["out_path"] = out_path
    data["n_paths"] = len(polys)
    return data

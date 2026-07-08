#!/usr/bin/env python3
"""R16 — Genera un SVG de TRAZOS (para plotter AxiDraw/GRBL) con tu letra.

Uso:
    python tools/plotter_svg.py "texto a escribir"        # desde texto
    python tools/plotter_svg.py --pdf ~/Descargas/x.pdf   # desde un PDF
    python tools/plotter_svg.py "..." --dry-run           # solo recorrido pluma-arriba
    python tools/plotter_svg.py "..." --seed 42           # reproducible

Salida: ~/Documentos/huevonitis_exports/plotter_YYYYMMDD_HHMMSS.svg (mm 1:1).
Post-proceso recomendado (CLIs externas, NO deps del app):
    vpype read out.svg linemerge linesort reloop write opt.svg   # optimizar
    axicli opt.svg                                               # AxiDraw
    svg2gcode out.svg -o out.gcode                              # GRBL
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _export_dir() -> Path:
    docs = Path.home() / "Documentos"
    base = docs if docs.is_dir() else Path.home()
    out = base / "huevonitis_exports"
    out.mkdir(parents=True, exist_ok=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="", help="texto a escribir")
    ap.add_argument("--pdf", help="extraer el texto de este PDF")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true", help="solo recorrido pluma-arriba")
    ap.add_argument("--paper", default="letter", choices=["letter", "a4"])
    args = ap.parse_args()

    import config
    config.ensure_dirs()
    config.load_settings()

    text = args.text
    if args.pdf:
        from core.export.pdf_to_handwriting import extract_pdf_text
        text = extract_pdf_text(args.pdf)
    if not text.strip():
        sys.exit("✗ Dame texto o --pdf con un PDF con texto.")

    active = "default"
    try:
        if config.SETTINGS_FILE.exists():
            with open(config.SETTINGS_FILE, encoding="utf-8") as f:
                active = json.load(f).get("active_profile_id", "default") or "default"
    except Exception:
        pass

    from core.inkcore.plotter.svg_export import export_svg
    from core.inkcore.plotter.vectorize import StrokeBank
    from core.inkcore.renderer_options import RenderOptions

    bank_dir = Path.home() / ".local/share/huevonitis4/tipografia" / active
    bank = StrokeBank(bank_dir)
    opts = RenderOptions(render_dpi=150, seed=args.seed, style="Bolígrafo")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _export_dir() / f"plotter_{stamp}.svg"
    res = export_svg(text, opts, bank, str(out), paper=args.paper, dry_run=args.dry_run)

    print(f"✓ SVG de trazos: {res['out_path']}")
    print(f"  {res['n_paths']} trazos (pluma-abajo), papel {args.paper} en mm 1:1.")
    if res["missing"]:
        print(f"  ⚠ sin glifo (se omiten): {' '.join(res['missing'])}")
    print("  Abrir en Inkscape para verlo; plotear con vpype+axicli o svg2gcode.")


if __name__ == "__main__":
    main()

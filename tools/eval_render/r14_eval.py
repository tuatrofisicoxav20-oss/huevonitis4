"""R14 — renders de evaluación y regresión de legibilidad (entregables 3/4).

Renderiza el MISMO párrafo largo con el banco real del perfil en tres
variantes para comparar a ojo:

  r14_baseline.png  — knobs R14 en OFF (comportamiento pre-R14).
  r14_trackAB.png   — Track A (latente de mano) + Track B (skips/uniones).
  r14_trackC.jpg    — la página A+B exportada con photo_export v2 completo.

Y corre la REGRESIÓN DE LEGIBILIDAD: tesseract (spa) sobre baseline vs
efectos ON; el acierto (ratio de difflib contra el texto fuente) no puede
caer más de ~3 puntos (criterio de aceptación R14 — si cae, se ajustan
clamps, no se sube el gate).

Uso:  python -m tools.eval_render.r14_eval [--profile default] [--seed 1234]
"""
from __future__ import annotations

import argparse
import difflib
import random
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

TEXTO = (
    "La luz de la tarde entraba por la ventana del laboratorio y caia sobre "
    "los cuadernos abiertos. Habiamos repetido el experimento tres veces y "
    "los resultados seguian sin coincidir con el modelo teorico, asi que "
    "decidimos revisar cada supuesto desde el principio.\n"
    "\n"
    "Primero medimos la temperatura del agua con dos termometros distintos "
    "para descartar un error de instrumento. Despues comparamos las lecturas "
    "de presion con la tabla de referencia del manual y encontramos una "
    "diferencia pequena pero constante en la tercera cifra decimal.\n"
    "\n"
    "Al final resulto que la calibracion inicial estaba mal anotada en la "
    "bitacora. Corregimos el valor, repetimos la serie completa de mediciones "
    "y esta vez la curva experimental quedo dentro del margen de error "
    "esperado. La conclusion es que ningun dato vale mas que su registro."
)

# Knobs de R14/R15 apagados = render pre-R14 (rollback byte-idéntico probado
# en los commits de cada track; aquí sirve de línea base visual y de OCR).
# R15 movió defaults (ink_stroke_space=True, ink_boost 0.7→0.92): el baseline
# los regresa para seguir midiendo contra el render pre-R14 real.
KNOBS_OFF = dict(hand_energy_sigma=0.0, session_shift_prob=0.0,
                 pressure_darkness_coupling=0.0, line_end_cramp=0.0,
                 pen_skip_prob=0.0, connector_prob=0.0,
                 ink_stroke_space=False, ink_boost=0.7)

# Track A en defaults + Track B prendido con valores de evaluación (los
# defaults de B son 0; esto es lo que se está evaluando).
KNOBS_AB = dict(pen_skip_prob=0.03, connector_prob=0.35)

FOTO_FX = dict(keystone_strength=0.012, desk_background="procedural",
               wb_warmth=0.05, shadow_blob=0.12, focus_gradient=1.6,
               motion_blur=1.5, iso_noise=1.6, chromatic_aberration=0.001,
               quality_range=(82, 88))


def _ocr_accuracy(png_path: Path, source_text: str) -> float:
    """Acierto de tesseract (spa) contra el texto fuente, 0..1.

    Normaliza a minúsculas sin acentos y colapsa espacios: mide LEGIBILIDAD
    del trazo, no la ortografía del OCR."""
    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s.lower())
        s = "".join(c for c in s if not unicodedata.combining(c))
        return " ".join(s.split())

    out = subprocess.run(
        ["tesseract", str(png_path), "-", "-l", "spa", "--psm", "6"],
        capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"tesseract falló: {out.stderr[:200]}")
    # autojunk=False: con textos >200 chars el modo por default marca los
    # caracteres frecuentes (espacios, vocales) como junk y el ratio colapsa.
    return difflib.SequenceMatcher(
        None, _norm(source_text), _norm(out.stdout), autojunk=False).ratio()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default=None,
                    help="perfil del banco (default: el activo)")
    ap.add_argument("--seed", type=int, default=1234)
    args = ap.parse_args()

    from core.export.photo_export import export_photo
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions

    out_dir = Path(__file__).parent
    bank = GlyphBank(profile=args.profile) if args.profile else GlyphBank()
    r = HandwritingRenderer(bank)

    print("render baseline (knobs R14 off)…")
    base = r.render_pages(TEXTO, RenderOptions(seed=args.seed, **KNOBS_OFF))[0]
    base.save(out_dir / "r14_baseline.png")

    print("render Track A+B on…")
    ab = r.render_pages(TEXTO, RenderOptions(seed=args.seed, **KNOBS_AB))[0]
    ab.save(out_dir / "r14_trackAB.png")

    print("export Track C (foto v2 sobre la página A+B)…")
    export_photo(ab, out_dir / "r14_trackC.jpg",
                 rng=random.Random(args.seed), **FOTO_FX)

    print("\nregresión de legibilidad (tesseract spa)…")
    with tempfile.TemporaryDirectory() as td:
        # La foto C se evalúa aparte (es la salida final del disfraz).
        foto_png = Path(td) / "c.png"
        from PIL import Image
        Image.open(out_dir / "r14_trackC.jpg").save(foto_png)
        acc_base = _ocr_accuracy(out_dir / "r14_baseline.png", TEXTO)
        acc_ab = _ocr_accuracy(out_dir / "r14_trackAB.png", TEXTO)
        acc_c = _ocr_accuracy(foto_png, TEXTO)

    delta = (acc_base - acc_ab) * 100
    print(f"  baseline : {acc_base * 100:5.1f}%")
    print(f"  A+B on   : {acc_ab * 100:5.1f}%  (Δ {delta:+.1f} pts)")
    print(f"  foto C   : {acc_c * 100:5.1f}%  (informativa)")
    if delta > 3.0:
        print("FALLA: la legibilidad cayó más de 3 puntos — ajustar clamps.")
        return 1
    print("OK: la legibilidad se mantiene dentro del margen (≤3 pts).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

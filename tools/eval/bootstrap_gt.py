#!/usr/bin/env python3
"""
Fase 0 — Anotación semi-automática de ground-truth.

Objetivo: bajar el costo de anotar una imagen de "una hora a mano" a "cinco
minutos corrigiendo". Dada una imagen real y (opcionalmente) su texto de
referencia, esta herramienta:

  1. Reproduce el preprocesado del pipeline y guarda ``<stem>.preprocessed.png``
     (el espacio sobre el que SE DEBE anotar el ground-truth).
  2. Corre el extractor actual y vuelca sus cajas + chars predichos a un
     borrador ``<stem>.gt.json`` (o ``<stem>.gt.json.draft`` si ya existe un GT,
     para no pisar trabajo anotado a mano).
  3. Imprime instrucciones claras de cómo corregir el borrador a mano.

NO es un editor gráfico: el borrador es un JSON editable. La idea es que el
humano abra ``<stem>.preprocessed.png`` en cualquier visor, compare con el
borrador y arregle (a) las cajas mal puestas y (b) los chars mal asignados.

Uso:
    python -m tools.eval.bootstrap_gt IMG [IMG ...] [--ref "texto escrito"]
    python -m tools.eval.bootstrap_gt tools/eval/eval_dataset/mi_foto.png \
        --ref "el veloz murcielago"

Tras corregir el borrador, renombralo a ``<stem>.gt.json`` (si quedó como
``.draft``) y medí con:
    python -m tools.eval.run_eval tools/eval/eval_dataset/*.png --label baseline
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import sys
from pathlib import Path

# Permitir ejecutar como script suelto (python tools/eval/bootstrap_gt.py …)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Reusar el preprocesado y la corrida del extractor del evaluador: una sola
# fuente de verdad para "cómo se preprocesa" y "cómo se corre el pipeline".
from tools.eval.run_eval import _preprocess_image, _run_extractor  # noqa: E402


def _draft_path(image_path: Path) -> Path:
    """Devuelve dónde escribir el borrador sin pisar un GT existente."""
    gt = image_path.parent / (image_path.stem + ".gt.json")
    if gt.exists():
        return image_path.parent / (image_path.stem + ".gt.json.draft")
    return gt


def bootstrap_image(image_path: Path, reference_text: str = "") -> bool:
    print(f"\n── {image_path.name} ──")
    if not image_path.exists():
        print(f"  ✕ no existe: {image_path}")
        return False

    # 1. Emitir la imagen preprocesada (espacio de anotación).
    pre = _preprocess_image(str(image_path))
    if pre is not None:
        try:
            import cv2
            out_pre = image_path.parent / (image_path.stem + ".preprocessed.png")
            cv2.imwrite(str(out_pre), pre)
            print(f"  imagen preprocesada → {out_pre.name}  (anota el GT sobre ESTA)")
        except Exception as exc:  # noqa: BLE001 — degradar con gracia
            print(f"  ⚠ no se pudo guardar la preprocesada: {exc}")
    else:
        print("  ⚠ no se pudo preprocesar (¿faltan deps de visión?). Sigo sin ella.")

    # 2. Correr el extractor para sembrar el borrador.
    try:
        pred_boxes, glyphs, _stats = _run_extractor(str(image_path), reference_text)
    except Exception as exc:  # noqa: BLE001
        print(f"  ✕ el extractor falló: {exc}")
        return False

    chars = [
        {"char": g.char, "box": list(b), "tier": g.tier}
        for g, b in zip(glyphs, pred_boxes)
    ]
    draft = {
        "_nota": "BORRADOR semi-automático. Corregí cada 'char' y 'box' contra "
                 f"{image_path.stem}.preprocessed.png. Las coords son [x,y,w,h] en "
                 "píxeles sobre ESA imagen. Borrá 'tier' y '_nota' cuando termines.",
        "image": image_path.name,
        "reference_text": reference_text,
        "chars": chars,
    }

    out = _draft_path(image_path)
    out.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  borrador → {out.name}  ({len(chars)} cajas predichas)")
    if out.suffix == ".draft":
        print(f"  ⓘ ya existía un {image_path.stem}.gt.json: no lo pisé. "
              f"Revisá el .draft y mergeá a mano si querés.")
    return True


def _print_instructions(n_ok: int) -> None:
    print("\n" + "=" * 72)
    print("CÓMO CORREGIR EL BORRADOR (5 minutos por imagen):")
    print("-" * 72)
    print("1. Abrí  <stem>.preprocessed.png  en cualquier visor de imágenes.")
    print("2. Abrí  <stem>.gt.json  en un editor de texto.")
    print("3. Para cada entrada de 'chars':")
    print("     • Si el 'char' está mal → corregilo (el carácter REAL de esa caja).")
    print("     • Si la 'box' [x,y,w,h] no encierra bien la letra → ajustá los números.")
    print("     • Si es una caja BASURA (ruido, media letra) → borrá la entrada.")
    print("     • Si falta una letra que el extractor NO detectó → agregá una entrada.")
    print("4. Borrá los campos 'tier' y '_nota' (el evaluador no los necesita).")
    print("5. Si el archivo quedó como '.gt.json.draft', renombralo a '.gt.json'.")
    print("6. Medí:  python -m tools.eval.run_eval tools/eval/eval_dataset/*.png "
          "--label baseline")
    print("=" * 72)
    print(f"Borradores generados: {n_ok}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Anotación semi-automática de ground-truth (Fase 0)")
    ap.add_argument("images", nargs="+", help="imágenes a sembrar (acepta globs)")
    ap.add_argument("--ref", default="",
                    help="texto de referencia escrito (mejora el sembrado de chars)")
    args = ap.parse_args(argv)

    paths: list[Path] = []
    for pat in args.images:
        expanded = _glob.glob(pat)
        paths.extend(Path(p) for p in (expanded or [pat]))
    paths = [p for p in paths if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    if not paths:
        print("No se encontraron imágenes (.png/.jpg).")
        return 1

    n_ok = sum(1 for p in paths if bootstrap_image(p, args.ref))
    _print_instructions(n_ok)
    return 0 if n_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

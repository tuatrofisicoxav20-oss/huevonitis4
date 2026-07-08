#!/usr/bin/env python3
"""Limpia glifos de mayúscula con un componente de tinta SUELTO arriba (artefacto
de extracción: una marca/tilde del renglón de arriba quedó pegada a la letra).

Detectado en E e I (cada una con 1 sola muestra): renderizaban con un puntito
flotando arriba a la izquierda en cada palabra capitalizada (Estado,
Introducción, El…). Ñ también tiene componente arriba PERO es su tilde real:
por eso este tool recibe la lista de chars a limpiar EXPLÍCITA (default 'E','I')
y nunca toca acentos/diacríticos.

Qué hace por glifo: borra el componente conectado pequeño superior separado por
un gap del cuerpo principal, recorta, y recalcula nat_h/nat_w/baseline_off en el
manifest (em_px se conserva: el cuerpo limpio ya renderiza a la proporción
correcta porque el render escala por alto_de_tinta/em_px).

Uso: python tools/clean_stray_caps.py [--apply] [--chars EI]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

BANK = Path.home() / ".local/share/huevonitis4/tipografia/default"
MANIFEST = BANK / "_manifest.json"


def clean_glyph(path: Path) -> tuple | None:
    """Quita el componente suelto superior. Devuelve (nat_w, nat_h, baseline_off)
    nuevos relativos a la imagen completa, o None si no había stray claro."""
    im = Image.open(path).convert("RGBA")
    alpha = np.asarray(im.split()[-1])
    mask = alpha > 40
    lbl, n = ndimage.label(mask)
    if n < 2:
        return None
    comps = []
    for i in range(1, n + 1):
        ys, xs = np.where(lbl == i)
        comps.append({"id": i, "top": ys.min(), "bot": ys.max(),
                      "area": (lbl == i).sum()})
    main = max(comps, key=lambda c: c["area"])
    top = min(comps, key=lambda c: c["top"])
    gap = main["top"] - top["bot"]
    # stray = componente chico, por encima del cuerpo, con gap claro
    if top["id"] == main["id"] or top["area"] >= main["area"] * 0.5 or gap <= 5:
        return None
    # borrar TODOS los componentes por encima del cuerpo principal con gap
    new_alpha = alpha.copy()
    for c in comps:
        if c["bot"] < main["top"] - 3 and c["area"] < main["area"] * 0.5:
            new_alpha[lbl == c["id"]] = 0
    im.putalpha(Image.fromarray(new_alpha))
    im.save(path)
    # geometría nueva sobre la tinta restante
    m2 = new_alpha > 40
    ys, xs = np.where(m2)
    nat_h = int(ys.max() - ys.min() + 1)
    nat_w = int(xs.max() - xs.min() + 1)
    baseline_off = int(ys.max())  # bottom de la tinta en coords de la imagen
    return nat_w, nat_h, baseline_off


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--chars", default="EI", help="caracteres a limpiar (default EI)")
    args = ap.parse_args()
    chars = set(args.chars)

    man = json.loads(MANIFEST.read_text())
    changed = []
    for it in man:
        if it.get("char") not in chars:
            continue
        path = Path(it["image_path"])
        if not path.exists():
            continue
        if not args.apply:
            # dry: solo reportar si hay stray
            im = Image.open(path).convert("RGBA")
            lbl, n = ndimage.label(np.asarray(im.split()[-1]) > 40)
            changed.append((it["char"], path.name, f"{n} componentes"))
            continue
        res = clean_glyph(path)
        if res:
            nat_w, nat_h, baseline_off = res
            old = (it.get("nat_w_px"), it.get("nat_h_px"), it.get("baseline_off"))
            it["nat_w_px"], it["nat_h_px"], it["baseline_off"] = nat_w, nat_h, baseline_off
            changed.append((it["char"], path.name, f"{old} -> {(nat_w, nat_h, baseline_off)}"))

    for c in changed:
        print(" ", *c)
    if not args.apply:
        print("[DRY-RUN] usá --apply para limpiar.")
        return
    shutil.copy2(MANIFEST, MANIFEST.with_suffix(".json.bak2"))
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(man, ensure_ascii=False, indent=2))
    os.replace(tmp, MANIFEST)
    print(f"\n✓ Limpiados {len(changed)} glifos. Backup manifest: {MANIFEST.with_suffix('.json.bak2')}")


if __name__ == "__main__":
    sys.exit(main())

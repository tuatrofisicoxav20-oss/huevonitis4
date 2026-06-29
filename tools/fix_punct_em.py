#!/usr/bin/env python3
"""Arregla la puntuación del banco: los signos renderizaban enormes porque su
em_px estaba mal referenciado (51-131 vs ~350 de las letras) y había glifos
basura (puntos de 78px de alto, mal extraídos).

Qué hace:
  1) Mueve los glifos basura a default/_purged_punct/ y los saca del manifest.
  2) Re-referencia em_px de la puntuación sobreviviente a una FRACCIÓN
     tipográfica objetivo por carácter: em_px = nat_h_px / target_frac.
     (altura_render = font_size * nat_h/em_px = font_size * target_frac).
     Así el punto sale chico, los signos altos (! ? ( )) quedan altos, y
     todas las muestras de un signo renderizan a tamaño consistente.

Uso:  python tools/fix_punct_em.py [--apply]   (sin --apply = dry-run)
El garbage list lo toma de un JSON (--garbage ruta) o de criterios objetivos.
Hace backup .bak del manifest. El banco grande ya debe tener backup tar.gz.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

BANK = Path.home() / ".local/share/huevonitis4/tipografia/default"
MANIFEST = BANK / "_manifest.json"

# Fracción del font_size a la que debe renderizar cada signo (proporción
# tipográfica real). Punto/coma chicos; ! ? ( ) altos.
TARGET_FRAC = {
    ".": 0.10, ",": 0.16, ";": 0.46, ":": 0.42,
    "!": 0.68, "?": 0.68, "¡": 0.62, "¿": 0.62,
    '"': 0.26, "(": 0.80, ")": 0.80, "-": 0.12,
    "'": 0.26, "–": 0.12, "—": 0.12,
}


def is_garbage_objetivo(it: dict) -> bool:
    """Criterio objetivo de respaldo: signo tipo-punto/coma con altura nativa
    absurda (mal extraído) o ink casi nula."""
    ch = it.get("char")
    if ch not in TARGET_FRAC:
        return False
    nat_h = it.get("nat_h_px") or 0
    ink = it.get("ink_coverage") or 0
    # un punto/coma de >40px de alto es claramente otra cosa
    if ch in ".,-" and nat_h > 40:
        return True
    return ink < 0.06  # casi sin tinta = ruido


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="aplicar (default dry-run)")
    ap.add_argument("--garbage", help="JSON con lista de image_path a purgar")
    args = ap.parse_args()

    if not MANIFEST.exists():
        sys.exit(f"No existe {MANIFEST}")
    man = json.loads(MANIFEST.read_text())

    purge_set: set[str] = set()
    if args.garbage and Path(args.garbage).exists():
        purge_set = set(json.loads(Path(args.garbage).read_text()))
        print(f"Garbage list externa: {len(purge_set)} rutas")
    # complementar con criterio objetivo
    for it in man:
        if is_garbage_objetivo(it):
            purge_set.add(it["image_path"])

    purge_dir = BANK / "_purged_punct"
    kept, purged = [], []
    em_changes = []
    for it in man:
        if it["image_path"] in purge_set:
            purged.append(it)
            continue
        ch = it.get("char")
        if ch in TARGET_FRAC:
            nat_h = it.get("nat_h_px") or 0
            if nat_h > 0:
                new_em = round(nat_h / TARGET_FRAC[ch])
                new_em = max(40, min(400, new_em))
                if new_em != it.get("em_px"):
                    em_changes.append((it["image_path"], ch, it.get("em_px"), new_em))
                    it["em_px"] = new_em
        kept.append(it)

    print(f"\nPURGA: {len(purged)} glifos | em_px corregidos: {len(em_changes)}")
    from collections import Counter
    print("  purga por char:", dict(Counter(p.get("char") for p in purged)))
    print("  ejemplos em_px:", [(c, a, n) for _, c, a, n in em_changes[:8]])

    if not args.apply:
        print("\n[DRY-RUN] nada escrito. Corré con --apply para aplicar.")
        return

    # Backup del manifest
    shutil.copy2(MANIFEST, MANIFEST.with_suffix(".json.bak"))
    purge_dir.mkdir(exist_ok=True)
    moved = 0
    for it in purged:
        src = Path(it["image_path"])
        if src.exists():
            try:
                shutil.move(str(src), str(purge_dir / src.name))
                moved += 1
            except Exception as e:
                print("  ! no se pudo mover", src.name, e)
    # Escritura atómica del manifest
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(kept, ensure_ascii=False, indent=2))
    os.replace(tmp, MANIFEST)
    print(f"\n✓ Aplicado. Manifest: {len(man)} -> {len(kept)} glifos. PNG movidos: {moved}.")
    print(f"  Backup manifest: {MANIFEST.with_suffix('.json.bak')}")
    print(f"  Glifos purgados en: {purge_dir}")


if __name__ == "__main__":
    main()

"""Curación del banco: elimina los glifos feos, conserva los mejores.

Uso: python tools/curate_bank.py           (dry-run, muestra el plan)
     python tools/curate_bank.py --apply   (hace backup tar.gz y ejecuta)

Criterios (conservador; NUNCA vacía un carácter):
  1. CNN-mismatch fuerte (solo a-z): P(char) < 0.05 y top-1 es OTRA letra
     → mal corte / otra letra / basura.
  2. Calidad ínfima: quality_score < 0.50 (si el char conserva ≥2 muestras).
  3. Cap de variantes: máx 12 por char (se quedan las mejores por score
     compuesto = quality_score + P_cnn).
Protecciones: mínimo 2 muestras por char (o todas si solo hay 1-2);
ñ/dígitos/signos se juzgan solo por calidad (el CNN EMNIST no aplica).
"""
import sys, tarfile, time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, ".")
DRY = "--apply" not in sys.argv
import config
config.ensure_dirs(); config.load_settings()
import logging
logging.basicConfig(level=logging.ERROR)

from core.inkcore.bank import GlyphBank, _CURATE_MISCLASS_FLOOR
from core.inkcore.ai.char_cnn import EMNISTCharClassifier, char_to_label

bank = GlyphBank(); bank.load()
entries = bank.get_all()
print(f"banco: {len(entries)} glifos, dir={bank.bank_dir}", flush=True)

# ── backup (solo en --apply) ──
if not DRY:
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = bank.bank_dir.parent / f"backup_pre_curado_{ts}.tar.gz"
    with tarfile.open(backup, "w:gz") as tf:
        tf.add(bank.bank_dir, arcname=bank.bank_dir.name)
    print(f"backup: {backup} ({backup.stat().st_size//1024} KB)", flush=True)

clf = EMNISTCharClassifier()
print("CNN disponible:", clf.available, flush=True)

MAX_PER_CHAR = 12
MIN_KEEP = 2
QUALITY_FLOOR = 0.50

by_char = defaultdict(list)
for e in entries:
    by_char[e.char].append(e)

plan = []   # (entry, razón)
kept_stats = {}
for char, glyphs in sorted(by_char.items()):
    use_cnn = clf.available and char_to_label(char) is not None
    scored = []
    for e in glyphs:
        p_cnn, top1 = None, None
        if use_cnn:
            mask = GlyphBank._ink_mask_for_cnn(e.image_path)
            if mask is not None:
                p_cnn = clf.score(mask, char)
                tk = clf.predict_topk(mask, 1)
                top1 = tk[0][0] if tk else None
        comp = e.quality_score + (p_cnn if p_cnn is not None else 0.0)
        scored.append((e, p_cnn, top1, comp))
    scored.sort(key=lambda t: -t[3])  # mejor primero

    keep, drop = [], []
    for e, p_cnn, top1, comp in scored:
        reason = None
        if (p_cnn is not None and 0 <= p_cnn < _CURATE_MISCLASS_FLOOR
                and top1 and top1 != char):
            reason = f"CNN dice '{top1}' (P({char})={p_cnn:.3f})"
        elif e.quality_score < QUALITY_FLOOR:
            reason = f"calidad {e.quality_score:.2f} < {QUALITY_FLOOR}"
        elif len(keep) >= MAX_PER_CHAR:
            reason = f"cap {MAX_PER_CHAR} variantes (score {comp:.2f})"
        if reason:
            drop.append((e, reason))
        else:
            keep.append(e)
    # Garantía: mínimo MIN_KEEP por char (rescatar los mejor rankeados del drop)
    while len(keep) < min(MIN_KEEP, len(glyphs)) and drop:
        # rescatar el de mayor score compuesto entre los dropeados
        drop.sort(key=lambda t: -(t[0].quality_score))
        e, _ = drop.pop(0)
        keep.append(e)
    plan.extend(drop)
    kept_stats[char] = (len(glyphs), len(keep))

print(f"\n{'char':>5} | antes → quedan | se van")
total_drop = 0
for char, (antes, quedan) in sorted(kept_stats.items()):
    n_drop = antes - quedan
    total_drop += n_drop
    if n_drop:
        print(f"{char!r:>5} | {antes:5d} → {quedan:6d} | {n_drop}")
print(f"\nTOTAL: {len(entries)} → {len(entries)-total_drop} (se eliminan {total_drop})")

razones = defaultdict(int)
for _, r in plan:
    razones[r.split(" (")[0].split(" dice")[0]] += 1
print("por razón:", dict(razones))

if DRY:
    print("\nDRY-RUN (usa --apply para ejecutar)")
else:
    bank.begin_batch()
    for e, _ in plan:
        bank.remove_glyph(e)
    bank.end_batch()
    bank.load()
    print(f"\nHECHO. Banco ahora: {len(bank.get_all())} glifos")

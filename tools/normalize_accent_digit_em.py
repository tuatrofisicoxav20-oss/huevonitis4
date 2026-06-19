"""Normaliza el em_px de las hojas de acentos y dígitos.

Las hojas auto-identificadas de acentos (á é í ó ú) y dígitos (0-9) se midieron
con una referencia de em inconsistente: em_px ~61-169 frente a ~350 de la hoja
de letras base. Como el render escala por nat_h/em_px, esos glifos salían
~1.65-1.7x más grandes de lo debido (acentos a frac ~0.80, dígitos ~0.83, contra
~0.49 de las ascendentes).

Fix: re-referenciar em_px POR GLIFO a la fracción objetivo (altura de ascendente
≈ cap-height), medida del propio banco. Como baseline_in/target_h =
(baseline_off - ink_top)/nat_h es INDEPENDIENTE de em_px, mover sólo em_px deja
la línea base intacta dentro del glifo: el glifo encoge/crece como bloque.

NO toca ñ ni ü (están en la hoja normal, em_px ~342, ya correctos) ni
baseline_off ni nat_h_px. No correrlo con la app abierta (manifest compartido).

Uso:
    python -m tools.normalize_accent_digit_em            # perfil default, aplica
    python -m tools.normalize_accent_digit_em --dry-run  # sólo reporta
    python -m tools.normalize_accent_digit_em --profile juan
"""
from __future__ import annotations

import argparse
import statistics as st
import sys

# Vocales con tilde aguda + sus mayúsculas. ñ y ü quedan FUERA a propósito.
ACCENT_CHARS = set("áéíóúÁÉÍÓÚ")
DIGIT_CHARS = set("0123456789")
ASCENDER_CHARS = set("bdfhklt")  # referencia de cap-height


def _frac(em_px: int, nat_h: int) -> float:
    return min(1.6, max(0.04, nat_h / em_px)) if em_px > 0 else 0.0


def normalize_profile(profile_id: str, *, dry_run: bool = False) -> dict:
    from core.inkcore.bank import GlyphBank

    bank = GlyphBank(profile_id)
    entries = bank.get_all()

    asc = [e for e in entries if e.char in ASCENDER_CHARS and e.em_px > 0]
    if not asc:
        raise SystemExit("No hay ascendentes en el banco para fijar el target.")
    target = st.median([_frac(e.em_px, e.nat_h_px) for e in asc])

    targets = ACCENT_CHARS | DIGIT_CHARS
    changed = 0
    before_acc, before_dig = [], []
    after_acc, after_dig = [], []
    for e in entries:
        if e.char not in targets or e.nat_h_px <= 0:
            continue
        new_em = max(1, round(e.nat_h_px / target))
        (before_acc if e.char in ACCENT_CHARS else before_dig).append(e.em_px)
        if new_em != e.em_px:
            if not dry_run:
                e.em_px = new_em
            changed += 1
        (after_acc if e.char in ACCENT_CHARS else after_dig).append(new_em)

    if changed and not dry_run:
        bank.save()

    def med(xs):
        return st.median(xs) if xs else 0

    return {
        "profile": profile_id,
        "target_frac": round(target, 3),
        "changed": changed,
        "acc_n": len(before_acc),
        "acc_em_before": med(before_acc),
        "acc_em_after": med(after_acc),
        "dig_n": len(before_dig),
        "dig_em_before": med(before_dig),
        "dig_em_after": med(after_dig),
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    import config
    pid = args.profile or config.DEFAULT_PROFILE_ID
    s = normalize_profile(pid, dry_run=args.dry_run)
    tag = "[DRY-RUN] " if s["dry_run"] else ""
    print(f"{tag}[{s['profile']}] target_frac={s['target_frac']} "
          f"(altura de ascendente)")
    print(f"  acentos: n={s['acc_n']}  em_px {s['acc_em_before']:.0f} -> "
          f"{s['acc_em_after']:.0f}")
    print(f"  dígitos: n={s['dig_n']}  em_px {s['dig_em_before']:.0f} -> "
          f"{s['dig_em_after']:.0f}")
    print(f"  entries modificados: {s['changed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

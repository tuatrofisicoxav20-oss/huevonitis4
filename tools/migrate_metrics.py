"""Migrador R1: añade métricas geométricas estimadas a bancos existentes.

Los bancos creados antes del manifest v2 no tienen geometría por glifo
(nat_h_px, baseline_off, em_px…); sin ella el renderer cae al modo estimado
en vivo. Este migrador corre el estimador heurístico UNA vez y persiste el
resultado al manifest.

Uso:
    python -m tools.migrate_metrics                  # perfil default
    python -m tools.migrate_metrics --profile juan   # un perfil específico
    python -m tools.migrate_metrics --all            # todos los perfiles
    python -m tools.migrate_metrics --force          # re-estimar las estimadas

Idempotente: sin --force sólo toca entries con metrics_source == "" y un
segundo run no cambia nada. NUNCA pisa métricas medidas de template. No
correrlo con la app abierta sobre el mismo banco (mismo aviso que cualquier
script suelto: el manifest es compartido).
"""
from __future__ import annotations

import argparse
import sys


def migrate_profile(profile_id: str, *, force: bool = False) -> dict:
    """Estima y persiste la geometría faltante de un perfil. Stats del run."""
    from core.inkcore.bank import GlyphBank
    from core.inkcore.glyph_metrics import (
        apply_geometry_to_entries,
        estimate_bank_geometry,
    )

    bank = GlyphBank(profile_id)
    entries = bank.get_all()
    updates = estimate_bank_geometry(entries, force=force)
    # get_all devuelve COPIA de la lista pero con los MISMOS objetos entry:
    # mutarlos muta el estado del banco; save() los persiste.
    applied = apply_geometry_to_entries(entries, updates)
    if applied:
        bank.save()
    stats = {
        "profile": profile_id,
        "total": len(entries),
        "estimated": applied,
        "already_ok": len(entries) - applied,
    }
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Estima métricas geométricas (R1) para bancos sin ellas.")
    parser.add_argument("--profile", default=None,
                        help="perfil a migrar (default: el perfil default)")
    parser.add_argument("--all", action="store_true",
                        help="migrar todos los perfiles existentes")
    parser.add_argument("--force", action="store_true",
                        help="re-estimar también las métricas ya estimadas "
                             "(nunca las medidas de template)")
    args = parser.parse_args(argv)

    import config
    profiles: list[str]
    if args.all:
        profiles = sorted(
            p.name for p in config.TIPOGRAFIA_DIR.iterdir()
            if p.is_dir() and (p / "_manifest.json").exists()
        ) if config.TIPOGRAFIA_DIR.exists() else []
    else:
        profiles = [args.profile or config.DEFAULT_PROFILE_ID]

    if not profiles:
        print("No hay perfiles con manifest que migrar.")
        return 0
    for pid in profiles:
        stats = migrate_profile(pid, force=args.force)
        print(f"[{stats['profile']}] {stats['estimated']} estimado(s), "
              f"{stats['already_ok']} ya con métricas, {stats['total']} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())

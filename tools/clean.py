#!/usr/bin/env python3
"""
Huevonitis 4 — Limpieza y checkpoint.

Elimina archivos temporales generados por la app sin tocar datos de usuario.
Ejecutar desde la raíz del proyecto:

    python tools/clean.py [--dry-run]
"""
from __future__ import annotations

import sys
import shutil
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(description="Limpieza de temporales de Huevonitis 4")
    parser.add_argument("--dry-run", action="store_true", help="No borrar, solo mostrar qué se borraría")
    args = parser.parse_args()
    dry = args.dry_run

    if dry:
        print("Modo simulación (--dry-run) — no se elimina nada.\n")

    total_bytes = 0
    total_files = 0

    def remove(path: Path, reason: str) -> None:
        nonlocal total_bytes, total_files
        try:
            size = path.stat().st_size if path.is_file() else sum(
                f.stat().st_size for f in path.rglob("*") if f.is_file()
            )
        except OSError:
            size = 0
        total_bytes += size
        total_files += 1
        action = "  [dry]" if dry else "  ✘"
        print(f"{action} {path}  ({_fmt_bytes(size)})  — {reason}")
        if not dry:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except OSError as e:
                print(f"      Error: {e}")

    # ── Temp bulk capture pages ───────────────────────────────────────────────
    bulk_temp = config.DATA_DIR / "temp_bulk_capture"
    if bulk_temp.exists():
        for f in bulk_temp.iterdir():
            remove(f, "página temporal de captura masiva")

    # ── Debug extraction overlays ─────────────────────────────────────────────
    debug_dir = config.DEBUG_DIR
    if debug_dir.exists():
        for f in debug_dir.iterdir():
            remove(f, "overlay de depuración de extracción")

    # ── OCR cache (configurable) ──────────────────────────────────────────────
    ask = input("\n¿Limpiar caché de OCR también? (puede ralentizar el primer uso) [s/N] ").strip().lower()
    if ask in ("s", "y"):
        cache_dir = config.OCR_CACHE_DIR
        if cache_dir.exists():
            for f in cache_dir.glob("*.pkl"):
                remove(f, "caché de OCR")

    # ── Autosave de proyectos eliminados ──────────────────────────────────────
    autosave_dir = config.AUTOSAVE_DIR
    if autosave_dir.exists():
        try:
            from core.project_manager import ProjectManager
            pm = ProjectManager()
            active_ids = {p.id for p in pm.list_projects()}
            for f in autosave_dir.glob("*.json"):
                pid = f.stem
                if pid not in active_ids:
                    remove(f, "autosave de proyecto eliminado")
        except Exception as exc:
            print(f"  No se pudo verificar proyectos activos: {exc}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    verb = "Se liberarían" if dry else "Liberados"
    print(f"  {verb}: {_fmt_bytes(total_bytes)} en {total_files} elemento(s)")

    if not dry and total_files > 0:
        print("  Limpieza completada.")
    elif total_files == 0:
        print("  No hay archivos temporales para limpiar.")


if __name__ == "__main__":
    main()

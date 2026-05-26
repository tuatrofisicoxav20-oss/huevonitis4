"""Migra un banco pre-v4.2 (plano) a la estructura de perfiles tipografia/default/.

Uso (modo seguro, hace backup): python tools/migrate_to_profiles.py
Uso (sin backup, no recomendado):  python tools/migrate_to_profiles.py --no-backup

La app ejecuta esta migración automáticamente al arrancar v4.2. Este script
sirve para correr manualmente, ej. desde la línea de comandos para probar.

Exit code 0 = OK o no se requería migración.
Exit code 1 = migración falló (el backup queda intacto si --no-backup no se pasó).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("migrate_to_profiles")

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def main() -> int:
    backup = "--no-backup" not in sys.argv

    import config
    config.ensure_dirs()

    from core.inkcore.profile_manager import (
        migrate_legacy_to_default,
        needs_legacy_migration,
    )

    if not needs_legacy_migration():
        log.info("No se requiere migración — el banco ya está en formato v4.2 o vacío.")
        return 0

    log.info("Banco legacy detectado en %s", config.TIPOGRAFIA_DIR)
    log.info("Backup: %s", "habilitado" if backup else "DESHABILITADO (--no-backup)")
    try:
        result = migrate_legacy_to_default(backup=backup)
    except Exception as exc:
        log.error("Migración FALLÓ: %s", exc, exc_info=True)
        log.error("Si pasaste --no-backup, restaura manualmente desde tu propia copia.")
        return 1

    log.info("=== Resumen de migración ===")
    for k, v in result.items():
        log.info("  %s: %s", k, v)
    log.info("OK — abrir Huevonitis 4 normalmente para ver el perfil 'default'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

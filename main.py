#!/usr/bin/env python3
"""
Huevonitis 4
App de escritorio para producir apuntes con tu letra real y gestionar
trabajos escolares freelance.

La versión real se lee de config.VERSION (sincronizada con VERSION, pyproject.toml e install.sh).
"""
import logging
import sys

import config


def _bootstrap() -> logging.Logger:
    """Setup de directorios, settings y logging. Llamar solo dentro de main()."""
    config.ensure_dirs()
    config.load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    log = logging.getLogger("huevonitis4")
    log.info(f"Starting Huevonitis {config.VERSION}")
    from core.diagnostics import diagnostics
    diagnostics.log_event("app", "start", config.VERSION)
    return log


def main():
    logger = _bootstrap()

    from app_state import STATE
    from core.businesscore.ledger import BusinessLedger
    from core.inkcore.pipeline import InkCorePipeline
    from core.project_manager import ProjectManager
    from ui.app import HuevonitisApp

    # v4.2: migración automática del banco legacy a estructura de perfiles.
    # Si detectamos un manifest en la raíz de tipografia/ y no hay _profiles.json,
    # movemos todo a tipografia/default/. Backup en _backup_pre_profiles/.
    try:
        from core.inkcore.profile_manager import (
            migrate_legacy_to_default,
            needs_legacy_migration,
        )
        if needs_legacy_migration():
            logger.info("Banco legacy detectado — migrando a perfiles…")
            res = migrate_legacy_to_default(backup=True)
            logger.info("Migración OK: %s", res)
    except Exception as e:
        logger.critical("Migración legacy falló: %s", e, exc_info=True)
        _show_fatal(
            f"La migración a perfiles falló.\n"
            f"Tu banco anterior está intacto en backup.\n\n{e}",
        )
        return

    # v4.2: diagnóstico de sesión — detectar inconsistencias antes de arrancar UI.
    # Skip con H4_SKIP_DIAGNOSTIC=1.
    try:
        from core.session_diagnostic import run_diagnostic, should_skip_diagnostic
        if not should_skip_diagnostic():
            results = run_diagnostic()
            issues = [r for r in results if r.severity in ("warning", "error")]
            if issues:
                logger.info("Diagnóstico: %d issues — mostrando modal", len(issues))
                from ui.views.diagnostic_modal import show_diagnostic_modal
                ok = show_diagnostic_modal(results)
                if not ok:
                    logger.info("Usuario eligió salir desde el modal de diagnóstico")
                    return
            else:
                logger.info("Diagnóstico: todo OK")
    except Exception as e:
        logger.error("Diagnóstico falló (no crítico): %s", e, exc_info=True)

    try:
        pm = ProjectManager()
    except Exception as e:
        logger.critical(f"No se pudo inicializar ProjectManager: {e}", exc_info=True)
        _show_fatal(f"Error al cargar proyectos:\n{e}")
        return

    # Cargar el perfil activo desde settings (default "default")
    active_profile = "default"
    try:
        import json
        if config.SETTINGS_FILE.exists():
            with open(config.SETTINGS_FILE, encoding="utf-8") as f:
                _s = json.load(f)
            active_profile = _s.get("active_profile_id", "default") or "default"
    except Exception:
        pass

    try:
        inkcore = InkCorePipeline(profile_id=active_profile)
    except Exception as e:
        logger.critical(f"No se pudo inicializar InkCorePipeline: {e}", exc_info=True)
        _show_fatal(f"Error al cargar el módulo de escritura (InkCore):\n{e}")
        return

    try:
        ledger = BusinessLedger()
    except Exception as e:
        logger.critical(f"No se pudo inicializar BusinessLedger: {e}", exc_info=True)
        _show_fatal(f"Error al cargar el módulo de negocio:\n{e}")
        return

    try:
        app = HuevonitisApp(
            state=STATE,
            project_manager=pm,
            inkcore=inkcore,
            ledger=ledger,
        )
        app.mainloop()
    except Exception as e:
        logger.critical(f"Error fatal en la aplicación: {e}", exc_info=True)
        _show_fatal(f"Error inesperado:\n{e}")


def _show_fatal(message: str):
    """Show a minimal Tk error dialog when the app cannot start normally."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Huevonitis — Error fatal", message)
        root.destroy()
    except Exception:
        print(f"FATAL: {message}", file=sys.stderr)


if __name__ == "__main__":
    main()

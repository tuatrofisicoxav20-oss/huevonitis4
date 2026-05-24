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

    try:
        pm = ProjectManager()
    except Exception as e:
        logger.critical(f"No se pudo inicializar ProjectManager: {e}", exc_info=True)
        _show_fatal(f"Error al cargar proyectos:\n{e}")
        return

    try:
        inkcore = InkCorePipeline()
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

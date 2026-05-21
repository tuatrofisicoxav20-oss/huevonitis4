#!/usr/bin/env python3
"""
Huevonitis 4.0.0
App de escritorio para producir apuntes con tu letra real y gestionar
trabajos escolares freelance.
"""
import logging
import sys

import config

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
logger = logging.getLogger("huevonitis4")
logger.info(f"Starting Huevonitis {config.VERSION}")

from core.diagnostics import diagnostics  # noqa: E402

diagnostics.log_event("app", "start", config.VERSION)

from app_state import STATE  # noqa: E402
from core.businesscore.ledger import BusinessLedger  # noqa: E402
from core.inkcore.pipeline import InkCorePipeline  # noqa: E402
from core.project_manager import ProjectManager  # noqa: E402
from ui.app import HuevonitisApp  # noqa: E402


def main():
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
        # Last resort: print to stderr if Tk itself is broken
        import sys
        print(f"FATAL: {message}", file=sys.stderr)


if __name__ == "__main__":
    main()

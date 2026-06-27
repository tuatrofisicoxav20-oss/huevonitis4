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


def _patch_customtkinter_py314(logger: logging.Logger) -> None:
    """Workaround: customtkinter 5.2.2 (la última en PyPI) + Python 3.14.

    En 3.14, Tk puede entregar `event.widget` como el pathname (str) en vez del
    objeto widget. `CTkScrollableFrame.check_if_master_is_canvas` hace
    `widget.master` asumiendo un widget, así que un str revienta con
    AttributeError en CADA evento de rueda sobre un scrollable frame (banco,
    revisión, grilla de plantilla…). No es fatal pero ensucia el log y rompe el
    scroll con rueda. No hay versión upstream que lo arregle todavía, así que
    envolvemos el método para resolver el str a widget (o tratarlo como
    no-canvas si no se puede)."""
    try:
        from customtkinter.windows.widgets.ctk_scrollable_frame import (
            CTkScrollableFrame,
        )
    except Exception as exc:
        logger.debug("patch ctk py314 omitido (import falló): %s", exc)
        return
    if getattr(CTkScrollableFrame, "_h4_py314_patched", False):
        return
    _orig = CTkScrollableFrame.check_if_master_is_canvas

    def _safe_check(self, widget):
        if isinstance(widget, str):
            try:
                widget = self.nametowidget(widget)
            except Exception:
                return False
        return _orig(self, widget)

    CTkScrollableFrame.check_if_master_is_canvas = _safe_check
    CTkScrollableFrame._h4_py314_patched = True
    logger.info("Aplicado workaround de scroll de customtkinter para Python 3.14")

    # Workaround 2: CTkScrollbar.set → _draw → update_idletasks → set → … entra
    # en recursión cuando un update_idletasks externo (p. ej. el toast al
    # terminar la Captura masiva) procesa la geometría de un scrollable frame
    # con cientos de items: la app se congela ("se queda plasmada"). Guard de
    # reentrada: la llamada anidada solo registra los valores y NO redibuja —
    # el redraw llega igual con el set de nivel superior.
    try:
        from customtkinter.windows.widgets.ctk_scrollbar import CTkScrollbar
    except Exception as exc:
        logger.debug("patch ctk scrollbar omitido (import falló): %s", exc)
        return
    if getattr(CTkScrollbar, "_h4_set_guard", False):
        return
    _orig_sb_set = CTkScrollbar.set

    def _safe_sb_set(self, *args, **kwargs):
        # Debounce: registrar los valores y agendar UN redraw con after(8).
        # Los N sets encolados (uno por <Configure> de cada widget empacado)
        # colapsan en un solo _draw; after() de timer además escapa del
        # update_idletasks en curso (after_idle NO lo haría).
        self._h4_pending_set = (args, kwargs)
        if getattr(self, "_h4_set_after", None) is not None:
            return

        def _flush():
            self._h4_set_after = None
            pend = getattr(self, "_h4_pending_set", None)
            if pend is None:
                return
            a, kw = pend
            try:
                if self.winfo_exists():
                    _orig_sb_set(self, *a, **kw)
            except Exception:  # widget destruido a mitad del after
                pass

        try:
            self._h4_set_after = self.after(8, _flush)
        except Exception:
            # fallback si after no está disponible (teardown): comportamiento orig
            _orig_sb_set(self, *args, **kwargs)

    CTkScrollbar.set = _safe_sb_set

    # Workaround 2b: CTkScrollbar._draw llama update_idletasks (vía su canvas
    # interno) para medirse — eso re-procesa la cola de geometría COMPLETA de
    # la app DENTRO del redraw, y los <Configure> resultantes redibujan otros
    # scrollbars que vuelven a procesar la cola (cascada que congela la app
    # con grids grandes). Durante _draw neutralizamos update_idletasks a nivel
    # tkinter.Misc (todos los widgets) y lo restauramos al salir (LIFO-safe):
    # como mucho el slider usa la medida del frame anterior y se corrige en el
    # siguiente redraw.
    import tkinter as _tk

    _orig_sb_draw = CTkScrollbar._draw

    def _safe_sb_draw(self, *args, **kwargs):
        prev_upd = _tk.Misc.update_idletasks
        _tk.Misc.update_idletasks = lambda s: None
        try:
            return _orig_sb_draw(self, *args, **kwargs)
        finally:
            _tk.Misc.update_idletasks = prev_upd

    CTkScrollbar._draw = _safe_sb_draw
    CTkScrollbar._h4_set_guard = True
    logger.info("Aplicado guard anti-recursión de CTkScrollbar (set + _draw)")

    # Workaround 3 (U1): CTkOptionMenu._draw llama self._canvas.update_idletasks()
    # — flushea la cola de geometría de TODA la app en cada redraw. Durante la
    # construcción de una vista con backlog grande eso cuesta ~1 s POR
    # OptionMenu (medido: Settings con 8 menús tardaba ~25 s en crearse).
    # Mismo tratamiento que el scrollbar: update_idletasks neutralizado solo
    # durante el _draw; el canvas se mide igual en el siguiente ciclo idle.
    try:
        from customtkinter.windows.widgets.ctk_optionmenu import CTkOptionMenu
    except Exception as exc:
        logger.debug("patch ctk optionmenu omitido (import falló): %s", exc)
        return
    if getattr(CTkOptionMenu, "_h4_draw_guard", False):
        return
    _orig_om_draw = CTkOptionMenu._draw

    def _safe_om_draw(self, *args, **kwargs):
        prev_upd = _tk.Misc.update_idletasks
        _tk.Misc.update_idletasks = lambda s: None
        try:
            return _orig_om_draw(self, *args, **kwargs)
        finally:
            _tk.Misc.update_idletasks = prev_upd

    CTkOptionMenu._draw = _safe_om_draw
    CTkOptionMenu._h4_draw_guard = True
    logger.info("Aplicado guard de update_idletasks en CTkOptionMenu._draw")


def main():
    logger = _bootstrap()
    from ui import perf
    perf.mark("startup")  # U0: el primer navigate("dashboard") cierra el timer
    _patch_customtkinter_py314(logger)

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
            # Solo los errores deben frenar el arranque con el modal bloqueante.
            # Los warnings (p. ej. orphan_pngs, cuyo auto_fix es no-op y por tanto
            # nunca se limpia) se registran pero NO gatean la app: si lo hicieran,
            # el modal reaparecería en cada arranque y —bajo Hyprland/XWayland el
            # CTkToplevel con root oculto no se mapea— dejaría el proceso colgado
            # para siempre en mainloop().
            errors = [r for r in results if r.severity == "error"]
            warnings = [r for r in results if r.severity == "warning"]
            if warnings:
                logger.info(
                    "Diagnóstico: %d warning(s) (no bloqueante): %s",
                    len(warnings), ", ".join(w.name for w in warnings),
                )
            if errors:
                logger.info("Diagnóstico: %d error(es) — mostrando modal", len(errors))
                from ui.views.diagnostic_modal import show_diagnostic_modal
                ok = show_diagnostic_modal(results)
                if not ok:
                    logger.info("Usuario eligió salir desde el modal de diagnóstico")
                    return
            elif not warnings:
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

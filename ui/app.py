"""HuevonitisApp — ventana raíz, navegación entre vistas y ciclo de vida.

La lógica de la ventana está repartida en mixins:
  • AppLayoutMixin — armado de grilla, topbar y statusbar
  • AppChromeMixin — status bar, spinner, título dinámico y atajos de teclado

Aquí quedan el __init__, la navegación entre vistas, la animación de entrada y
el ciclo de vida (cierre + autosave).
"""
import contextlib
import logging
from tkinter import messagebox

import customtkinter as ctk

import config
from ui import theme
from ui.app_chrome import AppChromeMixin
from ui.app_layout import AppLayoutMixin
from ui.components.toast import ToastManager
from ui.views.business_view import BusinessView
from ui.views.dashboard_view import DashboardView
from ui.views.inkcore_view import InkCoreView
from ui.views.projects_view import ProjectsView
from ui.views.settings_view import SettingsView
from ui.views.study_view import StudyView

logger = logging.getLogger(__name__)


def _load_saved_theme() -> str:
    """Return 'dark', 'light', or 'system' from saved settings (default 'dark')."""
    import json
    _map = {"Oscuro": "dark", "Claro": "light", "Sistema": "system"}
    try:
        if config.SETTINGS_FILE.exists():
            with open(config.SETTINGS_FILE, encoding="utf-8") as _f:
                return _map.get(json.load(_f).get("theme", "Oscuro"), "dark")
    except Exception:
        pass
    return "dark"


VIEW_NAMES = {
    "dashboard": "Dashboard",
    "projects":  "Proyectos",
    "study":     "Estudio",
    "inkcore":   "Mi Letra",
    "business":  "Negocio",
    "settings":  "Configuración",
}

VIEW_CLASSES = {
    "dashboard": DashboardView,
    "projects":  ProjectsView,
    "study":     StudyView,
    "inkcore":   InkCoreView,
    "business":  BusinessView,
    "settings":  SettingsView,
}


class HuevonitisApp(AppLayoutMixin, AppChromeMixin, ctk.CTk):
    def __init__(self, state, project_manager, inkcore, ledger):
        super().__init__()
        self.app_state = state
        self.project_manager = project_manager
        self.inkcore = inkcore
        self.ledger = ledger

        _saved_theme = _load_saved_theme()
        _ctk_mode = {"dark": "dark", "light": "light", "system": "system"}.get(_saved_theme, "dark")
        ctk.set_appearance_mode(_ctk_mode)
        ctk.set_default_color_theme("blue")
        theme.apply_theme(_saved_theme)
        theme.init_fonts()

        self.title(f"Huevonitis {config.VERSION}")
        self.geometry(f"{config.WINDOW_DEFAULT_WIDTH}x{config.WINDOW_DEFAULT_HEIGHT}")
        self.minsize(config.WINDOW_MIN_WIDTH, config.WINDOW_MIN_HEIGHT)

        self._current_view = None
        self._views: dict = {}
        self._title_update_job = None
        self._autosave_job = None
        self._status_clear_job = None
        self._spinner_index = 0
        self._spinner_job = None
        self._bg_work_count = 0

        self._build()
        self.toast_manager = ToastManager(self)
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.navigate("dashboard")
        self._schedule_autosave()
        self._schedule_title_update()

        # Window entrance animation
        self.after(50, self._entrance_animation)

    # ── Navigation ──────────────────────────────────────────────────────────

    def navigate(self, view_id: str):
        # Issue #4: guard against unknown view IDs — log a warning and do nothing.
        if view_id not in VIEW_CLASSES:
            logger.warning("navigate(): unknown view_id %r — ignoring", view_id)
            return

        name = VIEW_NAMES.get(view_id, view_id.title())
        self._view_title.configure(text=name)

        # Update topbar icon from nav items
        for item_id, icon, _label in theme.NAV_ITEMS:
            if item_id == view_id:
                self._topbar_icon.configure(text=icon)
                # Colour the topbar accent line per section
                accent = theme.NAV_ACCENT.get(view_id, theme.ACCENT_BLUE)
                # Find the accent line widget (first child packed at bottom)
                for child in self._topbar.winfo_children():
                    try:
                        if child.cget("height") == 2:
                            child.configure(fg_color=accent)
                    except Exception:
                        pass
                break

        self._sidebar.set_active(view_id)
        self.app_state.active_view = view_id

        if self._current_view:
            with contextlib.suppress(Exception):
                self._current_view.on_hide()
            self._current_view.pack_forget()

        # Issue #6: reuse cached view instances; only create each view once.
        if view_id not in self._views:
            cls = VIEW_CLASSES[view_id]
            self._views[view_id] = cls(self._content, app=self)

        view = self._views[view_id]
        # Issue #5: pack (map) the widget before calling on_show() so that any
        # geometry queries inside on_show() (winfo_width, winfo_height, etc.)
        # return valid values rather than 1x1 defaults.
        view.pack(fill="both", expand=True)
        self._current_view = view
        view.on_show()
        self.set_status(f"{name}")

    # ── Entrance animation ───────────────────────────────────────────────────

    def _entrance_animation(self):
        w = config.WINDOW_DEFAULT_WIDTH
        h = config.WINDOW_DEFAULT_HEIGHT
        steps = 18
        step_ms = 11
        start_scale = 0.92

        sx = (self.winfo_screenwidth() - w) // 2
        sy = (self.winfo_screenheight() - h) // 2

        def step(i):
            from ui.animations import ease_out
            t = ease_out(i / steps)
            scale = start_scale + (1.0 - start_scale) * t
            cur_w = int(w * scale)
            cur_h = int(h * scale)
            cx = sx + (w - cur_w) // 2
            cy = sy + (h - cur_h) // 2
            try:
                self.geometry(f"{cur_w}x{cur_h}+{cx}+{cy}")
            except Exception:
                return
            if i < steps:
                self.after(step_ms, lambda: step(i + 1))
            else:
                self.geometry(f"{w}x{h}+{sx}+{sy}")

        step(1)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _on_close(self):
        if self.app_state.current_project and self.app_state.unsaved_changes:
            answer = messagebox.askyesnocancel(
                "Salir",
                f"El proyecto '{self.app_state.current_project.name}' tiene cambios sin guardar.\n\n"
                "¿Guardar antes de salir?",
            )
            if answer is None:
                return
            if answer:
                self.project_manager.save(self.app_state.current_project)
        # Cancel pending after-jobs to avoid callbacks on destroyed widgets
        for job_attr in ("_title_update_job", "_autosave_job", "_spinner_job", "_status_clear_job"):
            job = getattr(self, job_attr, None)
            if job is not None:
                with contextlib.suppress(Exception):
                    self.after_cancel(job)
        self.destroy()

    def _schedule_autosave(self):
        def autosave():
            if self.app_state.current_project and self.app_state.unsaved_changes:
                with contextlib.suppress(Exception):
                    self.project_manager.autosave(self.app_state.current_project)
            self._autosave_job = self.after(config.AUTOSAVE_INTERVAL_MS, autosave)

        self._autosave_job = self.after(config.AUTOSAVE_INTERVAL_MS, autosave)

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
from ui import motion, perf, theme
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

        # U1: fade-in del contenido (la geometry de la ventana no se anima)
        self.after(50, self._content_fade_in)

    # ── Navigation ──────────────────────────────────────────────────────────

    def navigate(self, view_id: str):
        # Issue #4: guard against unknown view IDs — log a warning and do nothing.
        if view_id not in VIEW_CLASSES:
            logger.warning("navigate(): unknown view_id %r — ignoring", view_id)
            return

        if perf.ENABLED:
            perf.logger.info("navigate(%s): inicio", view_id)
        name = VIEW_NAMES.get(view_id, view_id.title())
        with perf.measure("navigate:chrome"):
            self._view_title.configure(text=name)

            # Update topbar icon from nav items (U3: icono dibujado, no emoji)
            for item_id, icon, _label in theme.NAV_ITEMS:
                if item_id == view_id:
                    from ui import icons
                    self._topbar_icon.configure(
                        image=icons.get_icon(icon, 20, theme.ACCENT_PRIMARY))
                    # U1/UI-22: lerp de color de la línea de acento (referencia
                    # directa creada en app_layout, sin escanear hijos)
                    accent = theme.NAV_ACCENT.get(view_id, theme.ACCENT_BLUE)
                    self._animate_topbar_accent(accent)
                    break

            self._sidebar.set_active(view_id)
        self.app_state.active_view = view_id

        first_view = self._current_view is None
        if self._current_view:
            with perf.measure("navigate:on_hide"), contextlib.suppress(Exception):
                self._current_view.on_hide()
            self._current_view.place_forget()

        # Issue #6: reuse cached view instances; only create each view once.
        if view_id not in self._views:
            cls = VIEW_CLASSES[view_id]
            with perf.measure(f"create_view({view_id})"):
                self._views[view_id] = cls(self._content, app=self)

        view = self._views[view_id]
        # Issue #5: map the widget before calling on_show() so that geometry
        # queries inside on_show() return valid values rather than 1x1.
        # U1: place (no pack) — la transición slide solo mueve la subventana
        # del view con tamaño constante: cero relayouts del root.
        start_x = 0 if first_view else 12
        view.place(x=start_x, y=0, relwidth=1.0, relheight=1.0)
        self._current_view = view
        with perf.measure(f"navigate:on_show({view_id})"):
            view.on_show()
        self.set_status(f"{name}")
        perf.note_navigate(self, view_id)
        if start_x:
            motion.animate(
                view,
                lambda t: view.place_configure(x=round(start_x * (1.0 - t))),
                steps=11, step_ms=16, kind="motion", easing="ease_out",
                key="view_slide",
            )

    def _animate_topbar_accent(self, accent: str):
        line = getattr(self, "_topbar_accent", None)
        if line is None:
            return
        try:
            current = line.cget("fg_color")
            if isinstance(current, (list, tuple)):
                current = current[0]
        except Exception:
            return
        motion.animate(
            line,
            lambda t: line.configure(fg_color=motion.lerp_color(current, accent, t)),
            steps=8, step_ms=16, kind="color", key="accent",
        )

    # ── Entrance ─────────────────────────────────────────────────────────────

    def _content_fade_in(self):
        """U1/UI-04: la ventana raíz YA NO anima geometry (en un WM de tiling
        eso pelea con el compositor). El "entrance" es un fade barato del
        fondo de la vista inicial vía ui/motion."""
        view = self._current_view or self._content
        start, end = theme.BG_SECONDARY, theme.BG_PRIMARY
        motion.animate(
            view,
            lambda t: view.configure(fg_color=motion.lerp_color(start, end, t)),
            steps=9, step_ms=16, kind="color", key="fg_color",
        )

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

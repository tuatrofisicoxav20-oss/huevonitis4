import contextlib
import logging
from tkinter import messagebox

import customtkinter as ctk

import config
from ui import theme
from ui.components.sidebar import CollapsibleSidebar
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

# Spinner frames for background work indicator
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class HuevonitisApp(ctk.CTk):
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

    # ── Layout ──────────────────────────────────────────────────────────────

    def _build(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=0)

        self._sidebar = CollapsibleSidebar(self, on_navigate=self.navigate)
        self._sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")

        self._topbar = self._make_topbar()
        self._topbar.grid(row=0, column=1, sticky="ew")

        self._content = ctk.CTkFrame(self, fg_color=theme.BG_PRIMARY, corner_radius=0)
        self._content.grid(row=1, column=1, sticky="nsew")

        self._statusbar = self._make_statusbar()
        self._statusbar.grid(row=2, column=1, sticky="ew")

    def _make_topbar(self) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(
            self,
            fg_color=theme.BG_SECONDARY,
            height=52,
            corner_radius=0,
        )
        bar.pack_propagate(False)

        # Accent line at the very bottom of the topbar
        accent_line = ctk.CTkFrame(bar, fg_color=theme.ACCENT_ORANGE, height=2, corner_radius=0)
        accent_line.pack(side="bottom", fill="x")

        # View icon + title
        self._topbar_icon = ctk.CTkLabel(
            bar,
            text="🏠",
            font=("Segoe UI", 18),
        )
        self._topbar_icon.pack(side="left", padx=(18, 4))

        self._view_title = ctk.CTkLabel(
            bar, text="Dashboard",
            font=theme.FONT_HEADING, text_color=theme.TEXT_PRIMARY,
        )
        self._view_title.pack(side="left", padx=(0, 16))

        # Separator
        ctk.CTkFrame(bar, width=1, fg_color=theme.BORDER, corner_radius=0).pack(
            side="left", fill="y", pady=12,
        )

        self._search_bar = ctk.CTkEntry(
            bar, placeholder_text="🔍  Buscar...",
            width=240, height=32,
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.BORDER,
        )
        self._search_bar.pack(side="left", padx=14)

        self._unsaved_label = ctk.CTkLabel(
            bar, text="",
            font=theme.FONT_SMALL, text_color=theme.ACCENT_ORANGE,
        )
        self._unsaved_label.pack(side="left")

        ctk.CTkLabel(
            bar, text=f"v{config.VERSION}",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(side="right", padx=20)

        return bar

    def _make_statusbar(self) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(
            self,
            fg_color=theme.BG_PRIMARY,
            height=26,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER,
        )
        bar.pack_propagate(False)

        self._spinner_label = ctk.CTkLabel(
            bar, text="",
            font=theme.FONT_MONO, text_color=theme.ACCENT_ORANGE, width=20,
        )
        self._spinner_label.pack(side="left", padx=(10, 0))

        self._status_label = ctk.CTkLabel(
            bar, text="Listo",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._status_label.pack(side="left", padx=(4, 14))

        self._status_project = ctk.CTkLabel(
            bar, text="",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._status_project.pack(side="right", padx=14)

        return bar

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

    # ── Status / title helpers ───────────────────────────────────────────────

    def set_status(self, message: str, clear_after: int = 5000):
        self._status_label.configure(text=message, text_color=theme.TEXT_SECONDARY)
        if clear_after > 0:
            if self._status_clear_job is not None:
                with contextlib.suppress(Exception):
                    self.after_cancel(self._status_clear_job)
            self._status_clear_job = self.after(clear_after, lambda: self._status_label.configure(
                text="Listo", text_color=theme.TEXT_MUTED))

    def begin_background_work(self):
        self._bg_work_count += 1
        if self._bg_work_count == 1:
            self._start_spinner()

    def end_background_work(self):
        self._bg_work_count = max(0, self._bg_work_count - 1)
        if self._bg_work_count == 0:
            self._stop_spinner()

    def _start_spinner(self):
        if self._spinner_job is not None:
            return

        def spin():
            self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
            try:
                self._spinner_label.configure(text=_SPINNER_FRAMES[self._spinner_index])
            except Exception:
                return
            self._spinner_job = self.after(80, spin)

        self._spinner_job = self.after(80, spin)

    def _stop_spinner(self):
        if self._spinner_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._spinner_job)
            self._spinner_job = None
        with contextlib.suppress(Exception):
            self._spinner_label.configure(text="")

    def _schedule_title_update(self):
        def update():
            proj = self.app_state.current_project
            if proj:
                indicator = " ●" if self.app_state.unsaved_changes else ""
                self._status_project.configure(text=f"📁 {proj.name}{indicator}")
                self._unsaved_label.configure(
                    text="  ● Sin guardar" if self.app_state.unsaved_changes else ""
                )
                win_title = f"Huevonitis {config.VERSION} — {proj.name}{indicator}"
            else:
                self._status_project.configure(text="")
                self._unsaved_label.configure(text="")
                win_title = f"Huevonitis {config.VERSION}"
            try:
                self.title(win_title)
            except Exception:
                return
            self._title_update_job = self.after(1000, update)

        self._title_update_job = self.after(1000, update)

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

    # ── Keyboard shortcuts ───────────────────────────────────────────────────

    def _bind_shortcuts(self):
        self.bind("<Control-s>", lambda e: self._save_current())
        self.bind("<Control-n>", lambda e: self.navigate("projects"))
        self.bind("<Control-d>", lambda e: self.navigate("dashboard"))
        self.bind("<Control-e>", lambda e: self.navigate("study"))
        self.bind("<Control-l>", lambda e: self.navigate("inkcore"))
        self.bind("<Control-b>", lambda e: self.navigate("business"))
        self.bind("<Control-comma>", lambda e: self.navigate("settings"))
        self.bind("<F1>", lambda e: self._show_shortcuts())

    def _save_current(self):
        if self.app_state.current_project and self.app_state.unsaved_changes:
            self.project_manager.save(self.app_state.current_project)
            self.app_state.mark_saved()
            self.set_status("Proyecto guardado ✓")
            self.toast_manager.show("Proyecto guardado", "success")

    def _show_shortcuts(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Atajos de teclado")
        dlg.geometry("400x340")
        dlg.configure(fg_color=theme.BG_PRIMARY)
        dlg.grab_set()

        header = ctk.CTkFrame(dlg, fg_color=theme.BG_SECONDARY, height=52, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="⌨️  Atajos de Teclado",
            font=theme.FONT_HEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(side="left", padx=20, pady=12)

        shortcuts = [
            ("Ctrl + S", "Guardar proyecto"),
            ("Ctrl + N", "Ir a Proyectos"),
            ("Ctrl + D", "Dashboard"),
            ("Ctrl + E", "Estudio"),
            ("Ctrl + L", "Mi Letra (InkCore)"),
            ("Ctrl + B", "Negocio"),
            ("Ctrl + ,", "Configuración"),
            ("F1",       "Mostrar atajos"),
            ("Ctrl + Z", "Deshacer (en canvas)"),
            ("Ctrl + Y", "Rehacer (en canvas)"),
        ]

        scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=12)

        for key, desc in shortcuts:
            row = ctk.CTkFrame(
                scroll,
                fg_color=theme.CARD_BG,
                corner_radius=8,
                border_width=1,
                border_color=theme.CARD_BORDER,
            )
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(
                row, text=key,
                font=theme.FONT_MONO, text_color=theme.ACCENT_ORANGE,
                width=130, anchor="w",
            ).pack(side="left", padx=12, pady=6)
            ctk.CTkLabel(
                row, text=desc,
                font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY,
            ).pack(side="left", padx=(0, 12))

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

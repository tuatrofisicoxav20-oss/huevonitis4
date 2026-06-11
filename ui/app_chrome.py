"""AppChromeMixin — "cromo" de la ventana: status bar, spinner de trabajo en
segundo plano, actualización de título y atajos de teclado.

Separado de app.py. Depende de:
  • self.app_state, self.project_manager, self.toast_manager
  • self.navigate — para los atajos de navegación
  • widgets creados en AppLayoutMixin: self._status_label, self._spinner_label,
    self._status_project, self._unsaved_label
  • jobs guardados como atributos: self._status_clear_job, self._spinner_job,
    self._title_update_job y el contador self._bg_work_count / self._spinner_index
"""
import contextlib

import customtkinter as ctk

import config
from ui import theme
from ui.modal_utils import safe_grab

# Spinner frames for background work indicator
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class AppChromeMixin:
    """Status, spinner, título dinámico y atajos de teclado."""

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
        safe_grab(dlg, self)

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

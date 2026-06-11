"""InkCoreViewProfileMixin — barra de perfiles (v4.2) de InkCoreView.

Separado de main_view.py para mantener cada archivo manejable. Agrupa toda la
barra superior de perfil activo: dropdown, contador de glifos, y las acciones
crear/renombrar/eliminar/seleccionar + persistencia en settings.json.

Depende de atributos definidos en InkCoreView.__init__ / _build:
  self._pipeline, self._profile_dropdown, self._profile_count_label
y de métodos de otros mixins:
  self._reload_and_refresh_all, self.toast
"""
import json
import logging
from tkinter import messagebox

import customtkinter as ctk

import config
from ui import theme
from ui.modal_utils import safe_grab

logger = logging.getLogger(__name__)


class InkCoreViewProfileMixin:
    """Barra de perfiles: dropdown, contador y CRUD de perfiles."""

    # ── Profile bar (v4.2) ────────────────────────────────────────

    def _build_profile_bar(self) -> None:
        """Barra arriba del CTkTabview con dropdown de perfil + acciones."""
        bar = ctk.CTkFrame(
            self, fg_color=theme.BG_SECONDARY, corner_radius=8,
            border_width=1, border_color=theme.BORDER, height=44,
        )
        bar.pack(fill="x", padx=16, pady=(16, 6))

        ctk.CTkLabel(
            bar, text="✍ Perfil activo:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=(12, 6))

        # Dropdown de perfiles
        profiles = self._pipeline.list_profiles()
        values = [p.name for p in profiles] or ["(sin perfiles)"]
        active = self._pipeline.profile_manager.get(self._pipeline.active_profile_id)
        active_name = active.name if active else values[0]
        self._profile_dropdown = ctk.CTkOptionMenu(
            bar, values=values,
            fg_color=theme.BG_TERTIARY,
            button_color=theme.ACCENT_ORANGE,
            button_hover_color=theme.ACCENT_ORANGE_HOVER,
            text_color=theme.TEXT_PRIMARY,
            width=200,
            command=self._on_profile_select,
        )
        self._profile_dropdown.set(active_name)
        self._profile_dropdown.pack(side="left", padx=4)

        # Botones +/✏️/🗑️
        for emoji, _tip, cmd, color in (
            ("➕", "Crear perfil",  self._profile_create, theme.ACCENT_GREEN),
            ("✏️", "Renombrar perfil", self._profile_rename, theme.ACCENT_BLUE),
            ("🗑️", "Eliminar perfil", self._profile_delete, theme.ACCENT_RED),
        ):
            ctk.CTkButton(
                bar, text=emoji, width=34, height=28,
                font=theme.get_font(size=12),
                fg_color=theme.BG_TERTIARY, hover_color=color,
                text_color=theme.TEXT_PRIMARY, corner_radius=6,
                command=cmd,
            ).pack(side="left", padx=2)

        # Contador de glifos
        self._profile_count_label = ctk.CTkLabel(
            bar, text="",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            fg_color=theme.BG_TERTIARY, corner_radius=12,
            padx=10, pady=2,
        )
        self._profile_count_label.pack(side="right", padx=12)
        self._update_profile_count()

    def _update_profile_count(self) -> None:
        try:
            n = len(self._pipeline.bank._entries)
            self._profile_count_label.configure(text=f"📁 {n} glifo{'s' if n != 1 else ''}")
        except Exception:
            pass

    def _refresh_profile_dropdown(self) -> None:
        profiles = self._pipeline.list_profiles()
        values = [p.name for p in profiles] or ["(sin perfiles)"]
        self._profile_dropdown.configure(values=values)
        active = self._pipeline.profile_manager.get(self._pipeline.active_profile_id)
        if active:
            self._profile_dropdown.set(active.name)

    def _on_profile_select(self, display_name: str) -> None:
        profiles = self._pipeline.list_profiles()
        target = next((p for p in profiles if p.name == display_name), None)
        if target is None or target.id == self._pipeline.active_profile_id:
            return
        ok = self._pipeline.switch_profile(target.id)
        if not ok:
            self.toast("No se pudo cambiar de perfil", "error")
            return
        self.toast(f"Perfil activo: {target.name}", "success")
        self._persist_active_profile(target.id)
        self._reload_and_refresh_all()
        self._update_profile_count()

    def _persist_active_profile(self, profile_id: str) -> None:
        """Guarda el id del perfil activo en settings.json."""
        try:
            data: dict = {}
            if config.SETTINGS_FILE.exists():
                with open(config.SETTINGS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
            data["active_profile_id"] = profile_id
            with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("No se pudo persistir active_profile_id: %s", exc)

    def _profile_create(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Crear perfil de letra")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("400x220")
        safe_grab(win, self)
        win.resizable(False, False)

        ctk.CTkLabel(
            win, text="📁 Nuevo perfil de letra",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 8))
        ctk.CTkLabel(
            win, text="Nombre (ej. 'Letra Emiliano'):",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=24)
        entry = ctk.CTkEntry(
            win, width=300, height=34,
            font=theme.FONT_BODY,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
            border_color=theme.ACCENT_BLUE,
        )
        entry.pack(padx=24, pady=6)
        entry.focus_set()

        result_lbl = ctk.CTkLabel(
            win, text="", font=theme.FONT_SMALL, text_color=theme.ACCENT_RED,
        )
        result_lbl.pack()

        def _create():
            name = entry.get().strip()
            if not name:
                result_lbl.configure(text="⚠ Escribe un nombre")
                return
            try:
                prof = self._pipeline.create_profile(name)
            except Exception as exc:
                logger.error("create_profile lanzó: %s", exc, exc_info=True)
                result_lbl.configure(text=f"⚠ Error: {exc}")
                return
            self.toast(f"Perfil '{prof.name}' creado", "success")
            self._refresh_profile_dropdown()
            # Switch al perfil recién creado
            self._pipeline.switch_profile(prof.id)
            self._persist_active_profile(prof.id)
            self._profile_dropdown.set(prof.name)
            self._reload_and_refresh_all()
            self._update_profile_count()
            win.destroy()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=12)
        ctk.CTkButton(
            btn_row, text="Cancelar", width=100, height=34,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
            hover_color=theme.BORDER, command=win.destroy,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row, text="✓ Crear", width=140, height=34,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.get_font("bold", 11),
            command=_create,
        ).pack(side="left", padx=4)
        entry.bind("<Return>", lambda e: _create())

    def _profile_rename(self) -> None:
        active = self._pipeline.profile_manager.get(self._pipeline.active_profile_id)
        if active is None:
            return
        win = ctk.CTkToplevel(self)
        win.title("Renombrar perfil")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("400x200")
        safe_grab(win, self)
        win.resizable(False, False)

        ctk.CTkLabel(
            win, text=f"✏️ Renombrar '{active.name}'",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 8))
        entry = ctk.CTkEntry(
            win, width=300, height=34,
            font=theme.FONT_BODY,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
            border_color=theme.ACCENT_BLUE,
        )
        entry.insert(0, active.name)
        entry.select_range(0, "end")
        entry.pack(padx=24, pady=6)
        entry.focus_set()

        def _rename():
            new_name = entry.get().strip()
            if not new_name or new_name == active.name:
                win.destroy()
                return
            ok = self._pipeline.rename_profile(active.id, new_name)
            if ok:
                self.toast("Perfil renombrado", "success")
                self._refresh_profile_dropdown()
            else:
                self.toast("No se pudo renombrar", "error")
            win.destroy()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=12)
        ctk.CTkButton(
            btn_row, text="Cancelar", width=100, height=34,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
            hover_color=theme.BORDER, command=win.destroy,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row, text="✓ Guardar", width=140, height=34,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.get_font("bold", 11),
            command=_rename,
        ).pack(side="left", padx=4)
        entry.bind("<Return>", lambda e: _rename())

    def _profile_delete(self) -> None:
        active_id = self._pipeline.active_profile_id
        active = self._pipeline.profile_manager.get(active_id)
        if active is None:
            return
        if active_id == config.DEFAULT_PROFILE_ID:
            self.toast("No se puede eliminar el perfil 'default'", "warning")
            return
        ok = messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar el perfil '{active.name}'?\n\n"
            "Solo se elimina del índice — los archivos quedan en disco como respaldo.\n"
            "Para borrarlos manualmente, vacía la carpeta del perfil.",
        )
        if not ok:
            return
        if self._pipeline.delete_profile(active_id, delete_data=False):
            self.toast(f"Perfil '{active.name}' eliminado del índice", "success")
            self._persist_active_profile(config.DEFAULT_PROFILE_ID)
            self._refresh_profile_dropdown()
            self._reload_and_refresh_all()
            self._update_profile_count()
        else:
            self.toast("No se pudo eliminar el perfil", "error")

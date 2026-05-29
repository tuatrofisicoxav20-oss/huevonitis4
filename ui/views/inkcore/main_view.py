"""InkCoreView — vista principal del módulo de tinta manuscrita.

Hereda comportamiento por tab de mixins separados:
  PipelinePanelMixin  → pipeline_panel.py
  ExtractorTabMixin   → extractor_tab.py
  BulkCaptureTabMixin → bulk_capture_tab.py
  BankTabMixin        → bank_tab.py
  WriterTabMixin      → writer_tab.py
  ReviewTabMixin      → review_tab.py
"""
import json
import logging
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import config
from core.inkcore.pipeline import InkCorePipeline
from core.inkcore.reporter import InkCoreReporter
from core.models import GlyphEntry
from ui import theme
from ui.views.base_view import BaseView
from ui.views.inkcore.bank_tab import BankTabMixin
from ui.views.inkcore.bulk_capture_tab import BulkCaptureTabMixin
from ui.views.inkcore.bulk_capture_tab_filters import BulkCaptureFiltersMixin
from ui.views.inkcore.bulk_capture_tab_grid import BulkCaptureGridMixin
from ui.views.inkcore.extractor_tab import ExtractorTabMixin
from ui.views.inkcore.extractor_tab_build import ExtractorTabBuildMixin
from ui.views.inkcore.extractor_tab_grid import ExtractorTabGridMixin
from ui.views.inkcore.pipeline_panel import PipelinePanelMixin
from ui.views.inkcore.replicator_tab import ReplicatorTabMixin
from ui.views.inkcore.review_tab import ReviewTabMixin
from ui.views.inkcore.review_tab_row import ReviewTabRowMixin
from ui.views.inkcore.writer_tab import WriterTabMixin

logger = logging.getLogger(__name__)

try:
    from PIL import ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False


class InkCoreView(
    PipelinePanelMixin,
    ExtractorTabBuildMixin,
    ExtractorTabMixin,
    ExtractorTabGridMixin,
    BulkCaptureTabMixin,
    BulkCaptureGridMixin,
    BulkCaptureFiltersMixin,
    BankTabMixin,
    WriterTabMixin,
    ReviewTabMixin,
    ReviewTabRowMixin,
    ReplicatorTabMixin,
    BaseView,
):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._pipeline: InkCorePipeline = app.inkcore
        self._reporter = InkCoreReporter()
        self._extracted: list[GlyphEntry] = []
        self._preview_photo = None
        self._image_path: str | None = None
        self._glyph_photos: list = []
        self._review_photos: list = []
        self._original_img = None
        self._adj_collapsed = False
        self._review_checkboxes: list = []
        self._review_check_vars: list = []
        self._thumb_cache: dict[tuple, "ImageTk.PhotoImage"] = {}
        self._writer_page_photos: list = []
        # PERF: tabs cuyo contenido quedó desactualizado y se refrescarán de
        # forma diferida la próxima vez que se muestren (evita reconstruir grids
        # no visibles en cada micro-acción del banco/revisión).
        self._tabs_dirty: set[str] = set()
        self._build()

    def _get_thumb(self, path: str, w: int, h: int) -> "ImageTk.PhotoImage | None":
        """Carga y cachea thumbnail de un glifo PNG."""
        key = (path, w, h)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        if not PIL_OK or not Path(path).exists():
            return None
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            bg = Image.new("RGBA", img.size, (22, 32, 50, 255))
            bg.paste(img, mask=img.split()[3])
            thumb = bg.convert("RGB")
            thumb.thumbnail((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self._thumb_cache[key] = photo
            if len(self._thumb_cache) > 300:
                oldest = next(iter(self._thumb_cache))
                del self._thumb_cache[oldest]
            return photo
        except Exception:
            return None

    def _build(self):
        self._build_profile_bar()
        self._tabs = ctk.CTkTabview(
            self,
            fg_color="transparent",
            segmented_button_fg_color=theme.BG_SECONDARY,
            segmented_button_selected_color=theme.ACCENT_ORANGE,
            segmented_button_unselected_color=theme.BG_SECONDARY,
            segmented_button_selected_hover_color=theme.ACCENT_ORANGE_HOVER,
            segmented_button_unselected_hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            command=self._on_tab_change,
        )
        self._tabs.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._tabs.add("📷 Extractor")
        self._tabs.add("📦 Captura masiva")
        self._tabs.add("🗂 Banco")
        self._tabs.add("✍️ Escritor")
        self._tabs.add("✅ Revisión")
        self._tabs.add("🔁 Reproducir")
        self._build_extractor(self._tabs.tab("📷 Extractor"))
        self._build_bulk_capture(self._tabs.tab("📦 Captura masiva"))
        self._build_bank(self._tabs.tab("🗂 Banco"))
        self._build_writer(self._tabs.tab("✍️ Escritor"))
        self._build_review(self._tabs.tab("✅ Revisión"))
        self._build_replicator(self._tabs.tab("🔁 Reproducir"))
        # Estado de sesión bulk
        self._bulk_session = None
        self._bulk_cancel_event = None
        self._bulk_selected_idx: int | None = None
        self._bulk_card_widgets: list = []
        self._bulk_filter_conf_val: str = "Todos"
        self._bulk_filter_status_val: str = "Pendientes"
        self._bulk_filter_char_val: str = "(todos)"

    def on_show(self):
        # Al ENTRAR a la vista sí releemos el banco del disco (pudo cambiar
        # fuera de aquí). Las micro-acciones posteriores ya NO releen disco.
        try:
            self._pipeline.reload_bank()
        except Exception as exc:
            logger.error("on_show: reload_bank falló: %s", exc, exc_info=True)
        self._reload_and_refresh_all()
        self._refresh_detector_chip()
        self._maybe_load_pending_text()

    # Nombres exactos de los tabs que cuelgan del banco (con emoji).
    _BANK_TAB = "🗂 Banco"
    _REVIEW_TAB = "✅ Revisión"

    def _on_tab_change(self) -> None:
        """Refresca de forma diferida un tab que quedó marcado como sucio.

        El refresco de banco/revisión es caro (reconstruye cientos de widgets);
        en vez de rehacer el tab no visible en cada acción, lo marcamos sucio y
        lo reconstruimos solo cuando el usuario lo abre.
        """
        try:
            name = self._tabs.get()
        except Exception:
            return
        if name not in self._tabs_dirty:
            return
        self._tabs_dirty.discard(name)
        try:
            if name == self._BANK_TAB:
                self._do_refresh_bank_ui()
            elif name == self._REVIEW_TAB:
                self._do_refresh_review_ui()
        except Exception as exc:
            logger.error("_on_tab_change(%s) falló: %s", name, exc, exc_info=True)

    def _maybe_load_pending_text(self) -> None:
        """Carga texto pendiente de Study si el escritor está vacío."""
        try:
            st = self.app.app_state
        except AttributeError:
            return
        pending = getattr(st, "study_text", None)
        if not pending:
            return
        current = self._writer_text.get("0.0", "end").strip()
        if not current:
            self._writer_text.delete("0.0", "end")
            self._writer_text.insert("0.0", pending)
            try:
                self._tabs.set("✍️ Escritor")
            except Exception:
                pass
            self.toast("Texto importado desde Estudio", "success")
        st.study_text = ""

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
        for emoji, tip, cmd, color in (
            ("➕", "Crear perfil",  self._profile_create, theme.ACCENT_GREEN),
            ("✏️", "Renombrar perfil", self._profile_rename, theme.ACCENT_BLUE),
            ("🗑️", "Eliminar perfil", self._profile_delete, theme.ACCENT_RED),
        ):
            ctk.CTkButton(
                bar, text=emoji, width=34, height=28,
                font=("Segoe UI", 12),
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
        win.grab_set()
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
            font=("Segoe UI", 11, "bold"),
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
        win.grab_set()
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
            font=("Segoe UI", 11, "bold"),
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

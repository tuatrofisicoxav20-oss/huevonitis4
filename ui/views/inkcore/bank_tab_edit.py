"""BankTabEditMixin — edición de glifos del Banco de InkCoreView.

Acciones por glifo (cycle tier, eliminar), alta manual desde imagen,
selección múltiple + batch, y recarga/refresco de los tabs afectados.
"""
import contextlib
import logging
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.diagnostics import diagnostics
from ui import theme

logger = logging.getLogger(__name__)


# Cycle Bronze → Silver → Gold → Bronze para el botón ⬆️
_TIER_CYCLE = {"Bronze": "Silver", "Silver": "Gold", "Gold": "Bronze"}


class BankTabEditMixin:
    """Edición de glifos del banco: acciones por glifo, alta manual y batch."""

    # ── Acciones por glifo ────────────────────────────────────────

    def _bank_cycle_tier(self, glyph) -> None:
        """Cicla el tier de un glifo: Bronze → Silver → Gold → Bronze."""
        new_tier = _TIER_CYCLE.get(glyph.tier, "Silver")
        logger.info("_bank_cycle_tier: %r %s → %s", glyph.char, glyph.tier, new_tier)
        try:
            ok = self._pipeline.bank.approve_glyph(glyph, new_tier=new_tier)
        except Exception as exc:
            logger.error("_bank_cycle_tier: bank.approve_glyph lanzó: %s", exc, exc_info=True)
            self.toast(f"Error al promover: {exc}", "error")
            return
        if not ok:
            self.toast(f"'{glyph.char}' no se encontró en el banco", "warning")
            return
        self.toast(f"'{glyph.char}': {glyph.tier} → {new_tier}", "success")
        self._reload_and_refresh_all()

    def _bank_delete_glyph(self, glyph) -> None:
        """Elimina un glifo individual del banco con confirmación."""
        if not messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar el glifo '{glyph.char}' (tier {glyph.tier})?\n"
            "Esta acción borra el PNG y la entrada del manifest.",
        ):
            return
        logger.info("_bank_delete_glyph: %r path=%s", glyph.char, glyph.image_path)
        try:
            self._pipeline.bank.remove_glyph(glyph)
        except Exception as exc:
            logger.error("_bank_delete_glyph: bank.remove_glyph lanzó: %s", exc, exc_info=True)
            self.toast(f"Error al eliminar: {exc}", "error")
            return
        self.toast(f"'{glyph.char}' eliminado", "warning")
        self._reload_and_refresh_all()

    # ── Agregar manualmente desde imagen ──────────────────────────

    def _add_glyph_manual(self) -> None:
        """Diálogo: elegir PNG/JPG → pedir char → bank.add_glyph."""
        path = filedialog.askopenfilename(
            title="Elegir imagen del glifo",
            filetypes=[
                ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
                ("Todos", "*.*"),
            ],
        )
        if not path:
            return
        self._open_add_glyph_modal(path)

    def _open_add_glyph_modal(self, source_path: str) -> None:
        """Modal: muestra preview + Entry(1 char) + Guardar."""
        win = ctk.CTkToplevel(self)
        win.title("Agregar glifo")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("420x340")
        win.grab_set()
        win.resizable(False, False)

        ctk.CTkLabel(
            win, text="📝 Agregar glifo desde imagen",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 4))

        ctk.CTkLabel(
            win, text=Path(source_path).name,
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 8))

        # Preview de la imagen
        photo = self._get_thumb(source_path, 80, 80)
        if photo is not None:
            preview_lbl = ctk.CTkLabel(
                win, image=photo, text="",
                fg_color=theme.BG_TERTIARY, corner_radius=8,
            )
            preview_lbl.pack(pady=8)

        ctk.CTkLabel(
            win, text="Carácter que representa este glifo:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(pady=(8, 2))

        entry = ctk.CTkEntry(
            win, width=200, height=40,
            font=("Segoe UI", 22),
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.ACCENT_BLUE,
            justify="center",
            placeholder_text="ej. a",
        )
        entry.pack(pady=4)
        entry.focus_set()

        result_lbl = ctk.CTkLabel(
            win, text="", font=theme.FONT_SMALL,
            text_color=theme.ACCENT_RED,
        )
        result_lbl.pack(pady=(2, 0))

        def _save():
            new_char = entry.get().strip()
            if not new_char:
                result_lbl.configure(text="⚠ Escribe un carácter")
                return
            ch = new_char[:1]
            logger.info("_add_glyph_manual: guardando %r desde %s", ch, source_path)
            try:
                entry_added = self._pipeline.bank.add_glyph(ch, source_path)
            except Exception as exc:
                logger.error("_add_glyph_manual: lanzó: %s", exc, exc_info=True)
                result_lbl.configure(text=f"⚠ Error: {exc}")
                return
            if entry_added is None:
                result_lbl.configure(text="⚠ Rechazado (duplicado perceptual o sin archivo)")
                return
            self.toast(f"Glifo '{ch}' agregado al banco", "success")
            win.destroy()
            self._reload_and_refresh_all()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=10)
        ctk.CTkButton(
            btn_row, text="Cancelar", width=100, height=34,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            command=win.destroy,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row, text="✓ Agregar", width=140, height=34,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 11, "bold"),
            command=_save,
        ).pack(side="left", padx=4)
        entry.bind("<Return>", lambda e: _save())

    # ── Selección múltiple + batch ────────────────────────────────

    def _update_bank_selection_bar(self) -> None:
        """Pack/forget la barra de batch según haya o no seleccionados."""
        try:
            count = sum(1 for v in self._bank_selection_vars.values() if v.get())
        except Exception:
            count = 0
        if count > 0:
            self._bank_selection_count_lbl.configure(
                text=f"{count} glifo{'s' if count != 1 else ''} seleccionado{'s' if count != 1 else ''}",
            )
            try:
                if not self._bank_batch_bar.winfo_ismapped():
                    self._bank_batch_bar.pack(fill="x", padx=12, pady=(4, 10))
            except Exception:
                pass
        else:
            try:
                if self._bank_batch_bar.winfo_ismapped():
                    self._bank_batch_bar.pack_forget()
            except Exception:
                pass

    def _bank_clear_selection(self) -> None:
        for var in self._bank_selection_vars.values():
            with contextlib.suppress(Exception):
                var.set(False)
        self._update_bank_selection_bar()
        # Re-render para limpiar checkboxes visualmente
        self._do_refresh_bank_ui()

    def _bank_batch_delete(self) -> None:
        """Elimina todos los glifos seleccionados con confirmación única."""
        selected_paths = [p for p, v in self._bank_selection_vars.items() if v.get()]
        if not selected_paths:
            self.toast("Sin selección", "warning")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación batch",
            f"¿Eliminar {len(selected_paths)} glifo(s) seleccionado(s)?\n"
            "Esta acción borra los PNGs y las entradas del manifest.",
        ):
            return
        all_entries = self._pipeline.bank.get_all()
        path_to_entry = {e.image_path: e for e in all_entries}
        removed = 0
        for p in selected_paths:
            entry = path_to_entry.get(p)
            if entry is None:
                logger.warning("_bank_batch_delete: path %s no está en banco", p)
                continue
            try:
                self._pipeline.bank.remove_glyph(entry)
                removed += 1
            except Exception as exc:
                logger.error("_bank_batch_delete: error en %s: %s", p, exc, exc_info=True)
        logger.info("_bank_batch_delete: %d/%d eliminados", removed, len(selected_paths))
        self.toast(f"{removed} glifos eliminados", "success" if removed else "warning")
        self._reload_and_refresh_all()

    def _reload_and_refresh_all(self):
        """Refresca banco + revisión desde el estado EN MEMORIA del banco.

        Ya NO relee el manifest del disco: tras approve/reject/rename/cycle el
        estado en memoria es la verdad (esos métodos mutan self._entries y hacen
        save()). Releer en cada micro-acción disparaba I/O + parse JSON + backfill
        + N stat() innecesarios. La recarga de disco vive en on_show / _refresh_bank.

        Solo se reconstruye el tab visible (banco o revisión); el otro se marca
        sucio y se reconstruye al abrirse (ver _on_tab_change). Reconstruir un grid
        de cientos de widgets que nadie está viendo era el grueso de la lentitud.
        """
        try:
            visible = self._tabs.get()
        except Exception:
            visible = None
        refreshers = {
            self._BANK_TAB: self._do_refresh_bank_ui,
            self._REVIEW_TAB: self._do_refresh_review_ui,
        }
        for name, fn in refreshers.items():
            if name == visible:
                try:
                    fn()
                except Exception as exc:
                    logger.error("%s refresh failed: %s", name, exc, exc_info=True)
                    diagnostics.log_error("reload_and_refresh_all", exc)
            else:
                self._tabs_dirty.add(name)
        # Profile bar counter (v4.2) — actualizar si el método existe
        with contextlib.suppress(AttributeError, Exception):
            self._update_profile_count()

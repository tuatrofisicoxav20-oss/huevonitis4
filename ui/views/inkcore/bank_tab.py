"""BankTabMixin — tab 🗂 Banco de InkCoreView."""
import logging
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.diagnostics import diagnostics
from ui import theme

logger = logging.getLogger(__name__)


# Cycle Bronze → Silver → Gold → Bronze para el botón ⬆️
_TIER_CYCLE = {"Bronze": "Silver", "Silver": "Gold", "Gold": "Bronze"}


class BankTabMixin:
    """Tab del banco de glifos y su lógica de refresco; mezclado en InkCoreView."""

    # ── Build ──────────────────────────────────────────────────────

    def _build_bank(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=10)

        self._bank_summary = ctk.CTkLabel(
            top, text="Cargando banco...",
            font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY,
        )
        self._bank_summary.pack(side="left")

        ctk.CTkButton(
            top, text="🔄  Recargar", width=100, height=30,
            fg_color=theme.BG_TERTIARY, font=theme.FONT_SMALL,
            hover_color=theme.BORDER,
            command=self._refresh_bank,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            top, text="📊 Ver Informe", width=130, height=30,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
            command=self._show_report,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            top, text="➕ Agregar desde imagen", width=180, height=30,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.FONT_SMALL,
            command=self._add_glyph_manual,
        ).pack(side="right", padx=4)

        filter_row = ctk.CTkFrame(parent, fg_color="transparent")
        filter_row.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(
            filter_row, text="Filtrar:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")

        self._bank_filter_entry = ctk.CTkEntry(
            filter_row, placeholder_text="Carácter...",
            width=80, fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY, border_color=theme.BORDER,
        )
        self._bank_filter_entry.pack(side="left", padx=8)
        self._bank_filter_entry.bind("<Return>", lambda e: self._refresh_bank())

        self._tier_filter = ctk.CTkOptionMenu(
            filter_row,
            values=["Todos", "Gold", "Silver", "Bronze"],
            fg_color=theme.BG_TERTIARY,
            button_color=theme.ACCENT_ORANGE,
            button_hover_color=theme.ACCENT_ORANGE_HOVER,
            text_color=theme.TEXT_PRIMARY,
            width=110,
            command=lambda v: self._refresh_bank(),
        )
        self._tier_filter.pack(side="left")

        # Selection mode toggle
        self._bank_select_mode = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            filter_row, text="Selección múltiple",
            variable=self._bank_select_mode,
            onvalue=True, offvalue=False,
            progress_color=theme.ACCENT_BLUE,
            font=theme.FONT_SMALL,
            command=self._refresh_bank,
        ).pack(side="right", padx=8)

        self._bank_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._bank_scroll.pack(fill="both", expand=True, padx=8, pady=4)

        # Batch action bar — visible solo cuando hay items seleccionados
        self._bank_batch_bar = ctk.CTkFrame(
            parent, fg_color=theme.BG_SECONDARY, corner_radius=8,
            border_width=1, border_color=theme.BORDER,
        )
        # No se empaqueta inicialmente; se hace pack/forget según selección
        self._bank_selection_count_lbl = ctk.CTkLabel(
            self._bank_batch_bar, text="",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        )
        self._bank_selection_count_lbl.pack(side="left", padx=12, pady=8)

        self._bank_batch_delete_btn = ctk.CTkButton(
            self._bank_batch_bar, text="🗑️  Eliminar seleccionados",
            width=200, height=30,
            fg_color=theme.ACCENT_RED, hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_SMALL,
            command=self._bank_batch_delete,
        )
        self._bank_batch_delete_btn.pack(side="left", padx=4, pady=8)

        # Mover a perfil — disabled hasta F3
        self._bank_batch_move_btn = ctk.CTkButton(
            self._bank_batch_bar, text="📁  Mover a perfil…",
            width=160, height=30,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            text_color=theme.TEXT_MUTED, font=theme.FONT_SMALL,
            state="disabled",
        )
        self._bank_batch_move_btn.pack(side="left", padx=4, pady=8)

        ctk.CTkLabel(
            self._bank_batch_bar,
            text="(Disponible al activar perfiles)",
            font=("Segoe UI", 8), text_color=theme.TEXT_MUTED,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            self._bank_batch_bar, text="✖ Limpiar selección",
            width=140, height=30,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            font=theme.FONT_SMALL,
            command=self._bank_clear_selection,
        ).pack(side="right", padx=12, pady=8)

        # Estado de selección — image_path → BooleanVar
        self._bank_selection_vars: dict[str, ctk.BooleanVar] = {}

    # ── Logic ──────────────────────────────────────────────────────

    def _refresh_bank(self):
        self._pipeline.reload_bank()
        self._do_refresh_bank_ui()

    def _do_refresh_bank_ui(self):
        for w in self._bank_scroll.winfo_children():
            w.destroy()
        self._glyph_photos.clear()
        # Reset selección al refrescar (los path pueden cambiar después de ops)
        self._bank_selection_vars = {}
        self._update_bank_selection_bar()

        cov = self._pipeline.bank_coverage()
        missing_str = ""
        if cov["alpha_missing"]:
            m = cov["alpha_missing"]
            missing_str = (
                f"  |  Faltan: {''.join(m[:8])}"
                f"{'…' if len(m) > 8 else ''}"
            )
        self._bank_summary.configure(
            text=(
                f"Total: {cov['total_glyphs']} glifos  |  "
                f"Letras: {cov['alpha_covered']}/27  |  "
                f"Calidad prom: {cov['avg_quality']:.0%}"
                + missing_str
            )
        )

        char_filter = self._bank_filter_entry.get().strip()
        tier_filter = self._tier_filter.get()
        glyphs = self._pipeline.bank.get_all(char_filter=char_filter, tier_filter=tier_filter)

        if not glyphs:
            ctk.CTkLabel(
                self._bank_scroll,
                text="Banco vacío. Ve al Extractor para agregar glifos\n"
                     "o usa ➕ Agregar desde imagen.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
                justify="center",
            ).pack(pady=30)
            return

        # Orden canónico: a-z con ñ en su posición (índice 14), luego 0-9, luego resto
        _ALPHA_ORDER = list("abcdefghijklmnñopqrstuvwxyz")

        def _char_sort_key(ch: str) -> tuple:
            ch_l = ch.lower()
            if ch_l in _ALPHA_ORDER:
                return (0, _ALPHA_ORDER.index(ch_l), ch)
            if ch.isdigit():
                return (1, int(ch), ch)
            return (2, ord(ch), ch)

        # Agrupar por carácter
        by_char: dict[str, list] = {}
        for g in glyphs:
            by_char.setdefault(g.char, []).append(g)

        # Si hay filtro de un solo char, mostrar flat (sin cabecera redundante)
        use_groups = len(by_char) > 1

        cols = 6
        for char in sorted(by_char.keys(), key=_char_sort_key):
            char_glyphs = by_char[char]
            if use_groups:
                # Cabecera de grupo con calidad promedio
                avg_q = sum(g.quality_score for g in char_glyphs) / len(char_glyphs)
                q_color = (theme.ACCENT_GREEN if avg_q >= 0.75
                           else theme.ACCENT_ORANGE if avg_q >= 0.50
                           else theme.ACCENT_RED)
                hdr = ctk.CTkFrame(
                    self._bank_scroll,
                    fg_color=theme.BG_SECONDARY, corner_radius=6,
                )
                hdr.pack(fill="x", pady=(10, 2), padx=4)
                ctk.CTkLabel(
                    hdr,
                    text=f"  {char.upper()}",
                    font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
                ).pack(side="left", padx=10, pady=4)
                ctk.CTkLabel(
                    hdr,
                    text=f"{len(char_glyphs)} muestra{'s' if len(char_glyphs) != 1 else ''}",
                    font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                ).pack(side="left", padx=4)
                ctk.CTkLabel(
                    hdr,
                    text=f"prom {avg_q:.0%}",
                    font=theme.FONT_SMALL, text_color=q_color,
                ).pack(side="right", padx=10, pady=4)

            current_row = None
            for i, g in enumerate(char_glyphs):
                if i % cols == 0:
                    current_row = ctk.CTkFrame(self._bank_scroll, fg_color="transparent")
                    current_row.pack(fill="x", pady=2, padx=4)
                self._build_bank_cell(current_row, g)

    def _build_bank_cell(self, parent, glyph) -> None:
        """Construye una celda con thumb, char/tier, calidad y botones de acción."""
        tc = self._tier_text_color(glyph.tier)
        tier_bg = theme.TIER_BG.get(glyph.tier, theme.CARD_BG)
        select_mode = bool(self._bank_select_mode.get())
        # Celda más alta para acomodar la fila de acciones (o checkbox + thumb)
        cell_h = 122
        cell = ctk.CTkFrame(
            parent,
            fg_color=tier_bg,
            corner_radius=8,
            width=78, height=cell_h,
            border_width=1,
            border_color=self._tier_border(glyph.tier),
        )
        cell.pack(side="left", padx=4)
        cell.pack_propagate(False)

        def _bh(c=cell, tb=tier_bg):
            c.bind("<Enter>", lambda e: c.configure(fg_color=theme.CARD_BG_HOVER), add="+")
            c.bind("<Leave>", lambda e: c.configure(fg_color=tb), add="+")
        _bh()

        # Checkbox en esquina superior izquierda (solo en modo selección)
        if select_mode:
            var = ctk.BooleanVar(value=False)
            self._bank_selection_vars[glyph.image_path] = var
            chk = ctk.CTkCheckBox(
                cell, text="", variable=var,
                width=14, height=14, checkbox_width=14, checkbox_height=14,
                fg_color=theme.ACCENT_BLUE,
                command=self._update_bank_selection_bar,
            )
            chk.place(x=2, y=2)

        photo = self._get_thumb(glyph.image_path, 50, 52)
        if photo is not None:
            ctk.CTkLabel(cell, image=photo, text="").pack(pady=(4, 0))
        else:
            ctk.CTkLabel(
                cell, text=glyph.char, font=("Segoe UI", 20),
                text_color=theme.TEXT_PRIMARY,
            ).pack(pady=8)

        ctk.CTkLabel(
            cell, text=f"{glyph.char}  {glyph.tier[0]}",
            font=theme.FONT_SMALL, text_color=tc,
        ).pack()
        ctk.CTkLabel(
            cell, text=f"{glyph.quality_score:.0%}",
            font=("", 8), text_color=theme.TEXT_MUTED,
        ).pack()

        # Botones de acción
        btn_row = ctk.CTkFrame(cell, fg_color="transparent")
        btn_row.pack(side="bottom", pady=(0, 3))

        ctk.CTkButton(
            btn_row, text="✏️", width=20, height=20,
            font=("Segoe UI", 10),
            fg_color=theme.BG_TERTIARY, hover_color=theme.ACCENT_BLUE,
            text_color=theme.TEXT_PRIMARY, corner_radius=4,
            command=lambda g=glyph: self._open_rename_modal(g),
        ).pack(side="left", padx=1)

        ctk.CTkButton(
            btn_row, text="⬆️", width=20, height=20,
            font=("Segoe UI", 10),
            fg_color=theme.BG_TERTIARY, hover_color=theme.ACCENT_GREEN,
            text_color=theme.TEXT_PRIMARY, corner_radius=4,
            command=lambda g=glyph: self._bank_cycle_tier(g),
        ).pack(side="left", padx=1)

        ctk.CTkButton(
            btn_row, text="🗑️", width=20, height=20,
            font=("Segoe UI", 10),
            fg_color=theme.BG_TERTIARY, hover_color=theme.ACCENT_RED,
            text_color=theme.TEXT_PRIMARY, corner_radius=4,
            command=lambda g=glyph: self._bank_delete_glyph(g),
        ).pack(side="left", padx=1)

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
            try:
                var.set(False)
            except Exception:
                pass
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
        """Recarga el banco una sola vez y actualiza banco + revisión."""
        try:
            self._pipeline.reload_bank()
        except Exception as exc:
            logger.error("reload_bank failed: %s", exc, exc_info=True)
            diagnostics.log_error("reload_and_refresh_all", exc)
        try:
            self._do_refresh_bank_ui()
        except Exception as exc:
            logger.error("_do_refresh_bank_ui failed: %s", exc, exc_info=True)
        try:
            self._do_refresh_review_ui()
        except Exception as exc:
            logger.error("_do_refresh_review_ui failed: %s", exc, exc_info=True)
        # Profile bar counter (v4.2) — actualizar si el método existe
        try:
            self._update_profile_count()
        except (AttributeError, Exception):
            pass

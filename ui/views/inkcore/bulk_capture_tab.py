"""BulkCaptureTabMixin — tab 📦 Captura masiva de InkCoreView."""
import logging
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class BulkCaptureTabMixin:
    """Tab de captura masiva con revisión en lote; mezclado en InkCoreView."""

    # ── Build ──────────────────────────────────────────────────────

    def _build_bulk_capture(self, parent):
        header = ctk.CTkFrame(parent, fg_color=theme.BG_SECONDARY, height=68, corner_radius=8)
        header.pack(fill="x", padx=8, pady=8)
        header.pack_propagate(False)

        self._bulk_status = ctk.CTkLabel(
            header,
            text="Sin sesión activa. Carga imágenes o un PDF para empezar.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._bulk_status.pack(side="left", padx=16)

        btn_row = ctk.CTkFrame(header, fg_color="transparent")
        btn_row.pack(side="right", padx=8)

        self._bulk_progress_bar = ctk.CTkProgressBar(
            header, mode="indeterminate", width=120,
            progress_color=theme.ACCENT_ORANGE,
        )

        self.primary_button(btn_row, "📂 Cargar archivos", self._bulk_load_files, 150).pack(
            side="left", padx=4)
        self.secondary_button(btn_row, "📁 Cargar carpeta", self._bulk_load_folder, 140).pack(
            side="left", padx=4)
        self._bulk_cancel_btn = ctk.CTkButton(
            btn_row, text="✕ Cancelar", width=90, height=30,
            fg_color=theme.ACCENT_RED, hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_SMALL, state="disabled",
            command=self._bulk_cancel,
        )
        self._bulk_cancel_btn.pack(side="left", padx=4)

        self._bulk_filters_frame = ctk.CTkFrame(parent, fg_color="transparent")

        flt_inner = ctk.CTkFrame(self._bulk_filters_frame, fg_color="transparent")
        flt_inner.pack(fill="x", padx=8, pady=4)

        ctk.CTkLabel(flt_inner, text="Confianza:", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTED, width=72).pack(side="left")
        self._bulk_filter_conf_btn = ctk.CTkSegmentedButton(
            flt_inner,
            values=["Todos", "Necesita revisión", "Alta confianza"],
            command=self._bulk_on_filter_conf,
            selected_color=theme.ACCENT_ORANGE,
            selected_hover_color=theme.ACCENT_ORANGE_HOVER,
            unselected_color=theme.BG_TERTIARY,
            font=theme.FONT_SMALL,
        )
        self._bulk_filter_conf_btn.set("Todos")
        self._bulk_filter_conf_btn.pack(side="left", padx=8)

        ctk.CTkLabel(flt_inner, text="Estado:", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTED, width=52).pack(side="left", padx=(16, 0))
        self._bulk_filter_status_btn = ctk.CTkSegmentedButton(
            flt_inner,
            values=["Pendientes", "Aprobados", "Rechazados", "Todos"],
            command=self._bulk_on_filter_status,
            selected_color=theme.ACCENT_BLUE,
            selected_hover_color=theme.ACCENT_BLUE_HOVER,
            unselected_color=theme.BG_TERTIARY,
            font=theme.FONT_SMALL,
        )
        self._bulk_filter_status_btn.set("Pendientes")
        self._bulk_filter_status_btn.pack(side="left", padx=8)

        ctk.CTkLabel(flt_inner, text="Carácter:", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTED, width=60).pack(side="left", padx=(16, 0))
        self._bulk_filter_char_combo = ctk.CTkComboBox(
            flt_inner, values=["(todos)"], width=80,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
            border_color=theme.BORDER, font=theme.FONT_SMALL,
            command=self._bulk_on_filter_char,
        )
        self._bulk_filter_char_combo.set("(todos)")
        self._bulk_filter_char_combo.pack(side="left", padx=4)

        self._bulk_grid_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._bulk_grid_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 0))

        self._bulk_placeholder = ctk.CTkLabel(
            self._bulk_grid_scroll,
            text="Sin candidatos. Carga archivos para extraer glifos.",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self._bulk_placeholder.pack(pady=80)

        footer = ctk.CTkFrame(parent, fg_color=theme.BG_SECONDARY, height=52, corner_radius=8)
        footer.pack(fill="x", padx=8, pady=(4, 8))
        footer.pack_propagate(False)

        self._bulk_stats_lbl = ctk.CTkLabel(
            footer, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        )
        self._bulk_stats_lbl.pack(side="left", padx=16)

        self._bulk_approve_all_btn = ctk.CTkButton(
            footer, text="✅ Aprobar Gold/Silver", state="disabled",
            command=self._bulk_approve_high_conf, width=200,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.FONT_SMALL,
        )
        self._bulk_approve_all_btn.pack(side="left", padx=4)

        self._bulk_commit_btn = ctk.CTkButton(
            footer, text="💾 Guardar aprobados al banco", state="disabled",
            command=self._bulk_commit_to_bank, width=240,
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
        )
        self._bulk_commit_btn.pack(side="right", padx=8)

        ctk.CTkLabel(footer,
                     text="A=aprobar  R=rechazar  E=editar  Flechas=navegar",
                     font=("Segoe UI", 9), text_color=theme.TEXT_MUTED,
        ).pack(side="right", padx=12)

        self._bulk_grid_scroll.bind("<Key>", self._bulk_on_key)

    # ── Logic ──────────────────────────────────────────────────────

    def _bulk_load_files(self):
        paths = filedialog.askopenfilenames(
            title="Seleccionar imágenes o PDFs",
            filetypes=[
                ("Soportados", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp *.pdf"),
                ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
                ("PDF", "*.pdf"),
            ],
        )
        if not paths:
            return
        self._bulk_run(list(paths))

    def _bulk_load_folder(self):
        folder = filedialog.askdirectory(title="Carpeta con imágenes")
        if not folder:
            return
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp", ".pdf"}
        paths = sorted(
            str(p) for p in Path(folder).iterdir() if p.suffix.lower() in exts
        )
        if not paths:
            self.toast("Carpeta sin imágenes soportadas", "warning")
            return
        self._bulk_run(paths)

    def _bulk_run(self, paths: list[str]):
        cfg = self._get_pipeline_config() if self._use_pipeline_var.get() else None
        if cfg is None:
            from core.inkcore.extraction_pipeline import PipelineConfig
            cfg = PipelineConfig(
                detectors=["classic_cv"],
                labelers=[],
                detector_fusion="union",
                labeler_voting="highest_conf",
            )

        import threading as _threading
        self._bulk_cancel_event = _threading.Event()
        self._bulk_progress_bar.pack(side="left", padx=(8, 0))
        self._bulk_progress_bar.start()
        self._bulk_cancel_btn.configure(state="normal")
        self._bulk_status.configure(text="Procesando…", text_color=theme.ACCENT_ORANGE)
        self._bulk_approve_all_btn.configure(state="disabled")
        self._bulk_commit_btn.configure(state="disabled")

        cancel_event = self._bulk_cancel_event

        def worker():
            try:
                from core.inkcore.bulk_capture import BulkCaptureRunner

                def cb(frac, msg):
                    if self.winfo_exists():
                        self.after(0, lambda m=msg: self._bulk_status.configure(
                            text=m, text_color=theme.ACCENT_ORANGE))
                runner = BulkCaptureRunner(cfg, progress_cb=cb, cancel_event=cancel_event)
                session = runner.run(paths)
                if self.winfo_exists():
                    self.after(0, lambda s=session: self._bulk_on_session_ready(s))
            except Exception as exc:
                logger.error("_bulk_run worker: %s", exc, exc_info=True)
                if self.winfo_exists():
                    self.after(0, lambda e=exc: (
                        self.toast(f"Error en captura masiva: {e}", "error"),
                        self._bulk_reset_ui(),
                    ))

        _threading.Thread(target=worker, daemon=True).start()

    def _bulk_cancel(self):
        if self._bulk_cancel_event:
            self._bulk_cancel_event.set()
        self.toast("Cancelando…", "info")
        self._bulk_cancel_btn.configure(state="disabled")

    def _bulk_reset_ui(self):
        self._bulk_progress_bar.stop()
        self._bulk_progress_bar.pack_forget()
        self._bulk_cancel_btn.configure(state="disabled")

    def _bulk_on_session_ready(self, session):
        self._bulk_session = session
        self._bulk_reset_ui()
        self._bulk_filters_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._bulk_filter_conf_val = "Todos"
        self._bulk_filter_status_val = "Pendientes"
        self._bulk_filter_char_val = "(todos)"
        self._bulk_filter_conf_btn.set("Todos")
        self._bulk_filter_status_btn.set("Pendientes")
        self._bulk_update_char_filter()
        self._bulk_render_grid()
        self._bulk_update_stats()
        s = session.stats()
        review_note = f" ({s['needs_review']} necesitan revisión)" if s["needs_review"] else ""
        self.toast(f"Captura: {s['total']} glifos extraídos{review_note}", "success")

    def _bulk_update_char_filter(self):
        if not self._bulk_session:
            return
        chars = sorted({c.display_char for c in self._bulk_session.candidates})
        self._bulk_filter_char_combo.configure(values=["(todos)"] + chars)
        self._bulk_filter_char_combo.set(self._bulk_filter_char_val)

    def _bulk_filtered_candidates(self) -> list:
        if not self._bulk_session:
            return []
        result = self._bulk_session.candidates
        sv = self._bulk_filter_status_val
        if sv == "Pendientes":
            result = [c for c in result if c.decision == "pending"]
        elif sv == "Aprobados":
            result = [c for c in result if c.decision == "approved"]
        elif sv == "Rechazados":
            result = [c for c in result if c.decision == "rejected"]
        cv = self._bulk_filter_conf_val
        if cv == "Necesita revisión":
            result = [c for c in result if c.needs_review]
        elif cv == "Alta confianza":
            result = [c for c in result if not c.needs_review]
        fchar = self._bulk_filter_char_val
        if fchar and fchar != "(todos)":
            result = [c for c in result if c.display_char == fchar]
        return result

    def _bulk_on_filter_conf(self, val):
        self._bulk_filter_conf_val = val
        self._bulk_render_grid()
        self._bulk_update_stats()

    def _bulk_on_filter_status(self, val):
        self._bulk_filter_status_val = val
        self._bulk_render_grid()
        self._bulk_update_stats()

    def _bulk_on_filter_char(self, val):
        self._bulk_filter_char_val = val
        self._bulk_render_grid()
        self._bulk_update_stats()

    def _bulk_render_grid(self):
        for w in self._bulk_grid_scroll.winfo_children():
            w.destroy()
        self._bulk_card_widgets = []
        self._bulk_selected_idx = None

        candidates = self._bulk_filtered_candidates()
        if not candidates:
            lbl = ctk.CTkLabel(
                self._bulk_grid_scroll,
                text="Sin candidatos con los filtros actuales.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            )
            lbl.pack(pady=80)
            return

        cols = 7
        row_frame = None
        for i, cand in enumerate(candidates):
            if i % cols == 0:
                row_frame = ctk.CTkFrame(self._bulk_grid_scroll, fg_color="transparent")
                row_frame.pack(fill="x", pady=2)
            card = self._bulk_make_card(row_frame, cand, i)
            card.pack(side="left", padx=3, pady=2)
            self._bulk_card_widgets.append((cand, card))

        self._bulk_approve_all_btn.configure(state="normal")
        self._bulk_commit_btn.configure(state="normal")
        self._bulk_grid_scroll.focus_set()

    def _bulk_make_card(self, parent, cand, idx: int) -> ctk.CTkFrame:
        DECISION_COLORS = {
            "pending":  theme.BG_TERTIARY,
            "approved": "#1A3A1A",
            "rejected": "#3A1A1A",
        }
        border_colors = {
            "pending": theme.BORDER,
            "approved": theme.ACCENT_GREEN,
            "rejected": theme.ACCENT_RED,
        }
        bg = DECISION_COLORS.get(cand.decision, theme.BG_TERTIARY)
        border = border_colors.get(cand.decision, theme.BORDER)

        card = ctk.CTkFrame(parent, fg_color=bg, corner_radius=8,
                            width=88, height=110,
                            border_width=2, border_color=border)
        card.pack_propagate(False)

        thumb_size = 56
        thumb = None
        if _PIL_OK and cand.glyph.image_path:
            thumb = self._get_thumb(cand.glyph.image_path, thumb_size, thumb_size)
        if thumb:
            ctk.CTkLabel(card, image=thumb, text="").pack(pady=(6, 2))
        else:
            ctk.CTkLabel(card, text="?", font=("Segoe UI", 24),
                         text_color=theme.TEXT_MUTED).pack(pady=(6, 2))

        char_lbl = ctk.CTkLabel(
            card, text=cand.display_char,
            font=("Segoe UI", 18, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        char_lbl.pack()

        lc = cand.glyph.label_confidence
        if lc is None:
            conf_text = cand.glyph.tier
            conf_color = theme.TEXT_MUTED
        elif lc >= 0.7:
            conf_text = f"{lc:.0%}"
            conf_color = theme.ACCENT_GREEN
        elif lc >= 0.4:
            conf_text = f"{lc:.0%}"
            conf_color = theme.ACCENT_YELLOW
        else:
            conf_text = f"{lc:.0%}"
            conf_color = theme.ACCENT_RED
        ctk.CTkLabel(card, text=conf_text, font=("Segoe UI", 9),
                     text_color=conf_color).pack()

        state_icons = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
        ctk.CTkLabel(card, text=state_icons.get(cand.decision, ""),
                     font=("Segoe UI", 10)).pack()

        def on_click(e, c=cand, i=idx):
            self._bulk_select(i)
        def on_dbl(e, c=cand, i=idx):
            self._bulk_toggle_decision(i)
        def on_right(e, c=cand, i=idx):
            self._bulk_edit_char_popup(i)

        for w in [card] + list(card.winfo_children()):
            w.bind("<Button-1>", on_click, add="+")
            w.bind("<Double-Button-1>", on_dbl, add="+")
            w.bind("<Button-3>", on_right, add="+")

        return card

    def _bulk_select(self, idx: int):
        if self._bulk_selected_idx is not None and self._bulk_selected_idx < len(self._bulk_card_widgets):
            prev_cand, prev_card = self._bulk_card_widgets[self._bulk_selected_idx]
            border = {"pending": theme.BORDER, "approved": theme.ACCENT_GREEN,
                      "rejected": theme.ACCENT_RED}.get(prev_cand.decision, theme.BORDER)
            prev_card.configure(border_color=border)
        self._bulk_selected_idx = idx
        if idx < len(self._bulk_card_widgets):
            _, card = self._bulk_card_widgets[idx]
            card.configure(border_color=theme.ACCENT_ORANGE)
        self._bulk_grid_scroll.focus_set()

    def _bulk_toggle_decision(self, idx: int):
        if not self._bulk_session or idx >= len(self._bulk_card_widgets):
            return
        cand, _ = self._bulk_card_widgets[idx]
        if cand.decision == "pending":
            cand.decision = "approved"
        elif cand.decision == "approved":
            cand.decision = "rejected"
        else:
            cand.decision = "pending"
        self._bulk_render_grid()
        self._bulk_update_stats()
        if idx < len(self._bulk_card_widgets):
            self._bulk_select(idx)

    def _bulk_edit_char_popup(self, idx: int):
        if not self._bulk_session or idx >= len(self._bulk_card_widgets):
            return
        cand, _ = self._bulk_card_widgets[idx]

        win = ctk.CTkToplevel(self)
        win.title("Editar carácter")
        win.geometry("280x140")
        win.grab_set()

        ctk.CTkLabel(win, text=f"Carácter actual: {cand.display_char!r}",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(pady=(16, 4))
        entry = ctk.CTkEntry(win, placeholder_text="Nuevo carácter",
                             fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
                             width=200)
        entry.pack(pady=4)
        entry.insert(0, cand.display_char)
        entry.focus()

        def save():
            new_char = entry.get().strip()
            if new_char:
                cand.user_label = new_char[:1]
                cand.decision = "approved"
            win.destroy()
            self._bulk_render_grid()
            self._bulk_update_stats()

        entry.bind("<Return>", lambda e: save())
        ctk.CTkButton(win, text="Guardar", command=save,
                      fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
                      width=200).pack(pady=8)

    def _bulk_on_key(self, event):
        if not self._bulk_session or not self._bulk_card_widgets:
            return
        key = event.keysym.lower()
        idx = self._bulk_selected_idx
        n = len(self._bulk_card_widgets)

        if key in ("right", "down"):
            self._bulk_select(min(n - 1, (idx or 0) + 1))
        elif key in ("left", "up"):
            self._bulk_select(max(0, (idx or 0) - 1))
        elif key == "a" and idx is not None:
            cand, _ = self._bulk_card_widgets[idx]
            cand.decision = "approved"
            self._bulk_render_grid()
            self._bulk_update_stats()
            self._bulk_select(min(n - 1, idx + 1))
        elif key == "r" and idx is not None:
            cand, _ = self._bulk_card_widgets[idx]
            cand.decision = "rejected"
            self._bulk_render_grid()
            self._bulk_update_stats()
            self._bulk_select(min(n - 1, idx + 1))
        elif key == "e" and idx is not None:
            self._bulk_edit_char_popup(idx)
        elif key == "space" and idx is not None:
            self._bulk_toggle_decision(idx)
        elif key == "escape":
            self._bulk_select(-1)
            self._bulk_selected_idx = None
        elif event.state & 0x4:  # Ctrl
            if key == "a":
                for c, _ in self._bulk_card_widgets:
                    c.decision = "approved"
                self._bulk_render_grid()
                self._bulk_update_stats()
            elif key == "d":
                for c, _ in self._bulk_card_widgets:
                    c.decision = "rejected"
                self._bulk_render_grid()
                self._bulk_update_stats()

    def _bulk_approve_high_conf(self):
        if not self._bulk_session:
            return
        count = 0
        for cand in self._bulk_session.candidates:
            if cand.decision == "pending" and cand.glyph.tier in ("Gold", "Silver"):
                cand.decision = "approved"
                count += 1
        self._bulk_render_grid()
        self._bulk_update_stats()
        self.toast(f"{count} candidatos Gold/Silver aprobados", "success")

    def _bulk_update_stats(self):
        if not self._bulk_session:
            self._bulk_stats_lbl.configure(text="")
            return
        s = self._bulk_session.stats()
        self._bulk_stats_lbl.configure(
            text=(f"Total: {s['total']}  ⏳{s['pending']}  ✅{s['approved']}"
                  f"  ❌{s['rejected']}  ⚠️{s['needs_review']}")
        )

    def _bulk_commit_to_bank(self):
        if not self._bulk_session:
            return
        from tkinter import messagebox
        approved = [c for c in self._bulk_session.candidates if c.decision == "approved"]
        if not approved:
            self.toast("No hay candidatos aprobados para guardar", "warning")
            return
        if not messagebox.askyesno(
            "Confirmar",
            f"¿Guardar {len(approved)} glifos al banco?\n"
            "Esto modifica permanentemente tu banco de tipografía.",
        ):
            return
        saved = 0
        failed = 0
        for c in approved:
            try:
                result = self._pipeline.bank.add_glyph(
                    c.display_char, c.glyph.image_path,
                    predicted_char=c.glyph.predicted_char,
                    label_confidence=c.glyph.label_confidence,
                    detector_sources=c.glyph.detector_sources,
                    quality_override={
                        "score": c.glyph.quality_score,
                        "tier": c.glyph.tier,
                        "ink_coverage": c.glyph.ink_coverage,
                    },
                )
                if result is not None:
                    saved += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error("bulk_commit: no se pudo guardar glifo: %s", exc)
                failed += 1

        msg = f"Guardados {saved} glifos al banco"
        if failed:
            msg += f" ({failed} fallaron o duplicados)"
        self.toast(msg, "success" if not failed else "warning")

        self._bulk_session = None
        self._bulk_card_widgets = []
        self._bulk_selected_idx = None
        self._bulk_filters_frame.pack_forget()
        for w in self._bulk_grid_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._bulk_grid_scroll,
            text="Sesión completada. Carga más archivos para continuar.",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        ).pack(pady=80)
        self._bulk_stats_lbl.configure(text="")
        self._bulk_approve_all_btn.configure(state="disabled")
        self._bulk_commit_btn.configure(state="disabled")
        self._bulk_status.configure(
            text="Sin sesión activa. Carga imágenes o un PDF para empezar.",
            text_color=theme.TEXT_MUTED,
        )
        self._reload_and_refresh_all()

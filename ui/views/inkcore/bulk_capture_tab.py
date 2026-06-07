"""BulkCaptureTabMixin — tab 📦 Captura masiva de InkCoreView."""
import contextlib
import logging
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
            header, width=160,
            progress_color=theme.ACCENT_ORANGE,
        )
        self._bulk_progress_bar.set(0)

        self.primary_button(btn_row, "📄 Cargar PDF de plantilla escaneada",
                            self._bulk_load_pdf, 250).pack(side="left", padx=4)
        self.secondary_button(btn_row, "🖼 Imágenes sueltas",
                              self._bulk_load_images, 150).pack(side="left", padx=4)
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
            text="↑ Carga un PDF de plantilla escaneada para empezar.\n\n"
                 "Escribe en la plantilla con tu letra, escanéala con Adobe Scan\n"
                 "y cárgala aquí para extraer 400–700 glifos en una sesión.",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            justify="center",
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

    def _bulk_load_pdf(self):
        path = filedialog.askopenfilename(
            title="Seleccionar PDF escaneado",
            filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            from pdf2image import convert_from_path, pdfinfo_from_path
        except ImportError:
            self.toast(
                "pdf2image no instalado. Ejecuta: pip install pdf2image", "error",
            )
            return
        try:
            info = pdfinfo_from_path(path)
            total_pages = int(info["Pages"])
            preview_imgs = convert_from_path(path, dpi=100, first_page=1, last_page=1)
            preview_img = preview_imgs[0]
        except Exception as exc:
            self.toast(f"Error al leer el PDF: {exc}", "error")
            return
        self._show_pdf_preview_modal(path, total_pages, preview_img)

    def _show_pdf_preview_modal(self, pdf_path: str, total_pages: int, preview_img):
        win = ctk.CTkToplevel(self)
        win.title("Confirmar PDF")
        win.geometry("520x640")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        ctk.CTkLabel(
            win,
            text=f"📄 PDF con {total_pages} página{'s' if total_pages != 1 else ''}",
            font=theme.FONT_TITLE,
        ).pack(pady=(20, 4))

        est_min = total_pages * 30
        est_max = total_pages * 90
        ctk.CTkLabel(
            win,
            text=f"Tiempo estimado: {est_min}–{est_max} segundos",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 10))

        preview_img.thumbnail((400, 380))
        ctkimg = ctk.CTkImage(
            light_image=preview_img, dark_image=preview_img, size=preview_img.size,
        )
        img_lbl = ctk.CTkLabel(win, image=ctkimg, text="")
        img_lbl.image = ctkimg  # keep ref
        img_lbl.pack(pady=6)

        ctk.CTkLabel(
            win,
            text="Verifica que la primera página se ve bien:\n"
                 "✓ Página derecha (no rotada 90°)\n"
                 "✓ Texto legible, sin borrosidad\n"
                 "✓ Sin sombras grandes ni partes cortadas",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY, justify="left",
        ).pack(pady=8, padx=24)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=14)

        ctk.CTkButton(
            btn_row, text="Procesar PDF", width=160,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            command=lambda: (win.destroy(), self._bulk_run_pdf(pdf_path)),
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_row, text="Cargar otro", width=110,
            command=lambda: (win.destroy(), self._bulk_load_pdf()),
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_row, text="Cancelar", width=90,
            fg_color=theme.BG_TERTIARY,
            command=win.destroy,
        ).pack(side="left", padx=4)

    def _bulk_run_pdf(self, pdf_path: str):
        cfg = self._get_pipeline_config() if self._use_pipeline_var.get() else None
        if cfg is None:
            from core.inkcore.extraction_pipeline import PipelineConfig
            cfg = PipelineConfig(
                detectors=["classic_cv"],
                labelers=[],
                detector_fusion="union",
                labeler_voting="highest_conf",
                min_quality=0.15,
            )

        import threading as _threading
        self._bulk_cancel_event = _threading.Event()
        self._bulk_progress_bar.pack(side="left", padx=(8, 0))
        self._bulk_progress_bar.set(0)
        self._bulk_cancel_btn.configure(state="normal")
        self._bulk_status.configure(text="Iniciando…", text_color=theme.ACCENT_ORANGE)
        self._bulk_approve_all_btn.configure(state="disabled")
        self._bulk_commit_btn.configure(state="disabled")
        with contextlib.suppress(Exception):
            self.app.begin_background_work()

        cancel_event = self._bulk_cancel_event

        def cb(frac: float, msg: str):
            def _update():
                self._bulk_progress_bar.set(frac)
                self._bulk_status.configure(text=msg, text_color=theme.ACCENT_ORANGE)
            if self.winfo_exists():
                self.after(0, _update)

        def worker():
            try:
                from core.inkcore.bulk_capture import BulkCaptureRunner
                runner = BulkCaptureRunner(
                    cfg, progress_cb=cb, cancel_event=cancel_event, pdf_dpi=300,
                )
                session = runner.run_pdf(pdf_path)
                if self.winfo_exists():
                    self.after(0, lambda s=session: self._bulk_on_session_ready(s))
            except Exception as exc:
                logger.error("_bulk_run_pdf worker: %s", exc, exc_info=True)
                if self.winfo_exists():
                    self.after(0, lambda e=exc: (
                        self.toast(f"Error al procesar PDF: {e}", "error"),
                        self._bulk_reset_ui(),
                    ))

        _threading.Thread(target=worker, daemon=True).start()

    def _bulk_load_images(self):
        paths = filedialog.askopenfilenames(
            title="Seleccionar imágenes",
            filetypes=[
                ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
                ("Todos", "*.*"),
            ],
        )
        if not paths:
            return
        self._bulk_run(list(paths))

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
        self._bulk_progress_bar.set(0)
        self._bulk_cancel_btn.configure(state="normal")
        self._bulk_status.configure(
            text=f"Procesando {len(paths)} imagen{'es' if len(paths) != 1 else ''}…",
            text_color=theme.ACCENT_ORANGE,
        )
        self._bulk_approve_all_btn.configure(state="disabled")
        self._bulk_commit_btn.configure(state="disabled")
        with contextlib.suppress(Exception):
            self.app.begin_background_work()

        cancel_event = self._bulk_cancel_event

        def worker():
            try:
                from core.inkcore.bulk_capture import BulkCaptureRunner

                def cb(frac: float, msg: str):
                    def _update():
                        self._bulk_progress_bar.set(frac)
                        self._bulk_status.configure(text=msg, text_color=theme.ACCENT_ORANGE)
                    if self.winfo_exists():
                        self.after(0, _update)
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
        self._bulk_progress_bar.pack_forget()
        self._bulk_progress_bar.set(0)
        self._bulk_cancel_btn.configure(state="disabled")
        self._bulk_status.configure(
            text="Sin sesión activa. Carga un PDF o imágenes para empezar.",
            text_color=theme.TEXT_MUTED,
        )
        with contextlib.suppress(Exception):
            self.app.end_background_work()

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
        # Construir línea de status informativa
        timing = f" · {session.elapsed_s:.1f}s" if session.elapsed_s > 0 else ""
        source = (f"{session.total_pages} págs · " if session.is_pdf else "")
        self._bulk_status.configure(
            text=f"Sesión activa — {source}{s['total']} glifos{timing}  ·  "
                 f"⚠️ {s['needs_review']} revisión  ·  "
                 f"Aprueba con A / rechaza con R",
            text_color=theme.ACCENT_GREEN,
        )

        review_note = f" ({s['needs_review']} necesitan revisión)" if s["needs_review"] else ""
        self.toast(f"✓ {s['total']} glifos extraídos{review_note}", "success")

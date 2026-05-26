import contextlib
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from core.export.pdf_exporter import export_text_pdf
from core.ocr.engine import OCREngine
from core.studycore.builder import build_study_bundle, build_study_bundle_from_document, grade_answer
from core.studycore.models import Flashcard, QuizQuestion, StudyBundle
from ui import theme
from ui.animations import count_up
from ui.views.base_view import BaseView

# ── Utilidades de análisis rápido (pre-ingesta) ───────────────────────────────

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
# Segundos estimados por página según backend
_SECS_PER_PAGE = {"tesseract": 8, "paddleocr": 15, "doctr": 12, "easyocr": 10}


def _quick_analyze(path: str, backend_name: str) -> dict:
    """
    Análisis rápido sin OCR: detecta tipo, cuenta páginas y estima el tiempo.
    Se ejecuta en worker thread — NO tocar widgets aquí.
    """
    p = Path(path)
    info: dict = {
        "name": p.name,
        "backend": backend_name,
        "needs_ocr": False,
        "pages": 1,
        "type": "unknown",
        "type_label": "Tipo desconocido",
        "estimated_secs": 0,
    }

    try:
        if p.is_dir():
            imgs = [f for f in p.iterdir() if f.suffix.lower() in _IMAGE_EXTS]
            info.update({
                "type": "folder",
                "type_label": f"Carpeta de imágenes — {len(imgs)} archivos",
                "needs_ocr": True,
                "pages": len(imgs),
            })

        elif p.suffix.lower() == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(str(p)) as pdf:
                    info["pages"] = len(pdf.pages)
            except Exception:
                info["pages"] = 0

            from core.ocr.document_readers.pdf_classifier import classify_pdf
            pdf_type = classify_pdf(str(p))
            _labels = {
                "text": ("text_pdf", "PDF con texto digital — sin OCR requerido", False),
                "scan": ("scan_pdf", "PDF escaneado — OCR completo requerido", True),
                "mixed": ("mixed_pdf", "PDF mixto — texto + páginas escaneadas", True),
            }
            t, label, needs = _labels.get(pdf_type, ("unknown", "PDF", True))
            info.update({"type": t, "type_label": label, "needs_ocr": needs})

        elif p.suffix.lower() == ".docx":
            info.update({
                "type": "docx",
                "type_label": "Documento Word — extracción directa",
                "needs_ocr": False,
                "pages": 1,
            })
        elif p.suffix.lower() == ".doc":
            info.update({
                "type": "unsupported",
                "type_label": "⚠ .doc no compatible — convierte a .docx primero",
                "needs_ocr": False,
                "pages": 0,
            })

        elif p.suffix.lower() in _IMAGE_EXTS:
            info.update({
                "type": "image",
                "type_label": "Imagen — OCR requerido",
                "needs_ocr": True,
                "pages": 1,
            })

    except Exception:
        pass

    # Estimación de tiempo
    pages = info["pages"] if isinstance(info["pages"], int) and info["pages"] > 0 else 1
    if not info["needs_ocr"]:
        secs = max(0, round(pages * 0.1, 1))
    else:
        per = _SECS_PER_PAGE.get(backend_name, 8)
        secs = pages * per
    info["estimated_secs"] = secs
    return info


# ── Diálogo de preview pre-ingesta ───────────────────────────────────────────

class _ImportPreviewDialog(ctk.CTkToplevel):
    """Diálogo modal con info rápida del documento antes de procesar."""

    _BLOCK_COLORS = {
        "text_pdf": "#2d6a4f",
        "scan_pdf": "#7b4f00",
        "mixed_pdf": "#5a4a00",
        "docx": "#1a4a7a",
        "image": "#5a2a6a",
        "folder": "#1a5a6a",
    }

    def __init__(self, parent, info: dict, on_confirm):
        super().__init__(parent)
        self._confirmed = False
        self._on_confirm = on_confirm

        name = info.get("name", "Documento")
        self.title(f"Importar — {name}")
        self.geometry("460x310")
        self.resizable(False, False)
        self.transient(parent)
        self._build(info)
        self.after(50, self.lift)

    def _build(self, info: dict):
        from ui import theme

        ctk.CTkLabel(self, text="Vista previa de importación",
                     font=theme.FONT_HEADING, text_color=theme.TEXT_PRIMARY
                     ).pack(anchor="w", padx=20, pady=(16, 8))

        card = ctk.CTkFrame(self, fg_color=theme.CARD_BG, corner_radius=10)
        card.pack(fill="x", padx=20, pady=4)

        rows = [
            ("Archivo",       info.get("name", "—")),
            ("Tipo detectado", info.get("type_label", "—")),
            ("Páginas",       str(info.get("pages", "?"))),
            ("Backend OCR",   info.get("backend", "—") if info.get("needs_ocr") else "Sin OCR"),
        ]
        secs = info.get("estimated_secs", 0)
        if secs >= 60:
            time_str = f"~{int(secs // 60)} min {int(secs % 60)} s"
        elif secs >= 1:
            time_str = f"~{int(secs)} s"
        else:
            time_str = "< 1 s"
        rows.append(("Tiempo estimado", time_str))

        for label, value in rows:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=3)
            ctk.CTkLabel(row, text=label + ":", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED, width=140, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=theme.FONT_BODY,
                         text_color=theme.TEXT_PRIMARY, anchor="w").pack(side="left")

        # Advertencia si OCR puede tardar mucho
        if info.get("needs_ocr") and info.get("estimated_secs", 0) > 60:
            ctk.CTkLabel(
                self,
                text="⚠ La operación puede tardar varios minutos. Puedes cancelar en cualquier momento.",
                font=theme.FONT_SMALL, text_color=theme.ACCENT_ORANGE,
                wraplength=420, justify="left",
            ).pack(padx=20, pady=(6, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(12, 16))

        ctk.CTkButton(
            btn_row, text="▶ Procesar", width=130,
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_BODY, command=self._confirm,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btn_row, text="✕ Cancelar", width=100,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY,
            command=self.destroy,
        ).pack(side="left")

    def _confirm(self):
        self._confirmed = True
        self.destroy()
        self._on_confirm()


from ui.views.study_view_flashcards import StudyFlashcardsMixin
from ui.views.study_view_tabs import StudyTabsBuildMixin


class StudyView(StudyTabsBuildMixin, StudyFlashcardsMixin, BaseView):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._ocr = OCREngine()
        self._bundle: StudyBundle | None = None
        self._flashcards: list[Flashcard] = []
        self._card_index: int = 0
        self._card_front: bool = True
        self._quiz_questions: list[QuizQuestion] = []
        self._quiz_index: int = 0
        self._quiz_score: int = 0
        self._quiz_active: bool = False
        self._quiz_next_job = None
        self._cancel_event: threading.Event | None = None
        self._last_document = None  # Document estructurado del último import
        self._build()

    def _build(self):
        paned = ctk.CTkFrame(self, fg_color="transparent")
        paned.pack(fill="both", expand=True, padx=20, pady=20)
        paned.columnconfigure(0, weight=45)
        paned.columnconfigure(1, weight=55)
        paned.rowconfigure(0, weight=1)

        left = self.card_frame(paned)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._build_left(left)

        right = self.card_frame(paned)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_right(right)

    def _build_left(self, parent):
        ctk.CTkLabel(parent, text="Texto de Estudio", font=theme.FONT_HEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 4))

        self._text_input = ctk.CTkTextbox(parent, font=theme.FONT_BODY,
                                          fg_color=theme.BG_TERTIARY,
                                          text_color=theme.TEXT_PRIMARY, wrap="word")
        self._text_input.pack(fill="both", expand=True, padx=12, pady=4)

        # Selector de backend OCR (visible siempre)
        backend_row = ctk.CTkFrame(parent, fg_color="transparent")
        backend_row.pack(fill="x", padx=12, pady=(4, 0))
        ctk.CTkLabel(backend_row, text="OCR:", font=theme.FONT_SMALL,
                     text_color=theme.TEXT_MUTED, width=36).pack(side="left")
        try:
            _avail = {k: v for k, v in self._ocr.available_backends().items()}
        except Exception:
            _avail = {"tesseract": True}
        backend_names = sorted(_avail.keys())
        self._backend_var = ctk.StringVar(value=self._ocr.backend_name)
        ctk.CTkOptionMenu(
            backend_row, values=backend_names, variable=self._backend_var,
            fg_color=theme.BG_TERTIARY, button_color=theme.ACCENT_BLUE,
            text_color=theme.TEXT_PRIMARY, width=130,
            command=self._on_backend_change,
        ).pack(side="left", padx=(0, 8))
        # Indicadores de disponibilidad
        for name, ok in sorted(_avail.items()):
            color = theme.ACCENT_GREEN if ok else theme.TEXT_MUTED
            ctk.CTkLabel(backend_row, text=f"{'●' if ok else '○'} {name}",
                         font=theme.FONT_SMALL, text_color=color).pack(side="left", padx=3)

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(4, 6))

        self.primary_button(btn_row, "📥 Importar...", self._import_document, 120).pack(side="left", padx=4)
        self.primary_button(btn_row, "📁 Carpeta", self._import_folder, 90).pack(side="left", padx=4)
        self.primary_button(btn_row, "📷 Imagen", self._ocr_image, 90).pack(side="left", padx=4)
        self.secondary_button(btn_row, "🗑 Limpiar", self._clear_text, 90).pack(side="left", padx=4)

        # Fila de progreso (barra + label + botón cancelar)
        prog_row = ctk.CTkFrame(parent, fg_color="transparent")
        prog_row.pack(fill="x", padx=12, pady=(0, 8))
        self._progress = ctk.CTkProgressBar(prog_row, mode="determinate",
                                            fg_color=theme.BG_TERTIARY,
                                            progress_color=theme.ACCENT_BLUE)
        self._progress.set(0)
        self._progress.pack(side="left", fill="x", expand=True)
        self._progress_label = ctk.CTkLabel(prog_row, text="", font=theme.FONT_SMALL,
                                            text_color=theme.TEXT_MUTED, width=160, anchor="w")
        self._progress_label.pack(side="left", padx=(6, 0))
        self._cancel_btn = ctk.CTkButton(prog_row, text="✕ Cancelar", width=90,
                                         fg_color=theme.ACCENT_RED, hover_color="#b03030",
                                         font=theme.FONT_SMALL, command=self._cancel_import)
        self._cancel_btn.pack(side="left", padx=(6, 0))
        prog_row.pack_forget()
        self._prog_row = prog_row

    def _build_right(self, parent):
        self._tabs = ctk.CTkTabview(parent, fg_color="transparent",
                                    segmented_button_fg_color=theme.BG_TERTIARY,
                                    segmented_button_selected_color=theme.ACCENT_BLUE,
                                    segmented_button_unselected_color=theme.BG_TERTIARY,
                                    text_color=theme.TEXT_PRIMARY)
        self._tabs.pack(fill="both", expand=True, padx=8, pady=8)

        self._tabs.add("Resumen")
        self._tabs.add("Bloques")
        self._tabs.add("Flashcards")
        self._tabs.add("Examen")
        self._tabs.add("Conceptos")

        self._build_summary_tab(self._tabs.tab("Resumen"))
        self._build_blocks_tab(self._tabs.tab("Bloques"))
        self._build_flashcard_tab(self._tabs.tab("Flashcards"))
        self._build_exam_tab(self._tabs.tab("Examen"))
        self._build_concepts_tab(self._tabs.tab("Conceptos"))

    def _on_backend_change(self, new_name: str):
        self._ocr.switch_backend(new_name)
        self.toast(f"Backend OCR: {new_name}", "info")

    # ── Importación ────────────────────────────────────────────────────────────

    def _import_document(self):
        """Importa cualquier formato soportado con preview previo."""
        path = filedialog.askopenfilename(
            title="Importar documento",
            filetypes=[
                ("Documentos", "*.pdf *.docx *.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
                ("PDF", "*.pdf"),
                ("Word (.docx)", "*.docx"),
                ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
                ("Todos", "*.*"),
            ],
        )
        if path:
            self._show_import_preview(path)

    def _import_folder(self):
        """Importa carpeta de imágenes con preview previo."""
        path = filedialog.askdirectory(title="Seleccionar carpeta de imágenes")
        if path:
            self._show_import_preview(path)

    def _ocr_image(self):
        path = filedialog.askopenfilename(
            title="Seleccionar imagen",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp")],
        )
        if path:
            self._show_import_preview(path)

    def _show_import_preview(self, path: str) -> None:
        """Análisis rápido en thread → muestra diálogo de preview → procesa al confirmar."""
        self._show_progress(True, "Analizando tipo de documento…")

        def _analyze():
            info = _quick_analyze(path, self._ocr.backend_name)
            if self.winfo_exists():
                self.after(0, lambda: self._on_preview_ready(path, info))

        threading.Thread(target=_analyze, daemon=True).start()

    def _on_preview_ready(self, path: str, info: dict) -> None:
        self._show_progress(False)
        dlg = _ImportPreviewDialog(self, info=info, on_confirm=lambda: self._ingest_path(path))
        dlg.grab_set()
        dlg.focus()

    # ── Acciones post-ingesta ──────────────────────────────────────────────────

    def _reprocess(self) -> None:
        """Re-procesa el documento actual invalidando el caché."""
        if self._last_document is None:
            self.toast("No hay documento cargado", "warning")
            return
        src = self._last_document.source_path
        try:
            from core.ocr.result_cache import OCRResultCache
            OCRResultCache().invalidate(src)
        except Exception:
            pass
        self._ingest_path(src)

    def _write_with_my_hand(self) -> None:
        """Transfiere el texto actual a InkCore Escritor y navega allí."""
        text = self._get_text()
        if not text:
            self.toast("Importa o escribe texto primero", "warning")
            return
        try:
            st = self.app.app_state
            st.study_text = text
            st.study_document = self._last_document
            self.app.navigate("inkcore")
        except Exception:
            self.toast("Módulo de reescritura no disponible en esta versión", "info")

    def _ingest_path(self, path: str):
        """Handler unificado: ingesta cualquier ruta (archivo o carpeta)."""
        self._cancel_event = threading.Event()
        self._show_progress(True, "Analizando…")

        def _progress_cb(fraction: float, msg: str):
            if self.winfo_exists():
                self.after(0, lambda f=fraction, m=msg: self._update_progress(f, m))

        def _read():
            try:
                doc = self._ocr.ingest_document(
                    path, progress_cb=_progress_cb, cancel_event=self._cancel_event
                )
                text = doc.full_text()
                cancelled = self._cancel_event.is_set()

                def _done():
                    self._last_document = doc
                    self._on_ocr_done(text)
                    self._update_blocks_tab(doc)
                    if cancelled:
                        self.toast("Cancelado — texto parcial importado", "warning")
                    else:
                        type_labels = {
                            "text_pdf": "PDF con texto digital",
                            "scan_pdf": "PDF escaneado",
                            "mixed_pdf": "PDF mixto",
                            "docx": "Word",
                            "image": "Imagen",
                            "folder": "Carpeta",
                        }
                        label = type_labels.get(doc.source_type, doc.source_type)
                        backend = f" · {doc.ocr_backend_used}" if doc.ocr_backend_used else ""
                        ms = doc.extraction_time_ms
                        time_str = f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms}ms"
                        self.toast(
                            f"{label}{backend} — {doc.page_count} pág. ({time_str})",
                            "success",
                        )

                self.after(0, _done)
            except Exception as exc:
                self.after(0, lambda exc=exc: self._on_import_error(str(exc)))

        threading.Thread(target=_read, daemon=True).start()

    def _on_ocr_done(self, text: str):
        if not self.winfo_exists():
            return
        self._show_progress(False)
        self._text_input.delete("0.0", "end")
        self._text_input.insert("0.0", text)

    def _import_word(self):
        path = filedialog.askopenfilename(
            title="Seleccionar Word (.docx)", filetypes=[("Word (.docx)", "*.docx")]
        )
        if path:
            self._ingest_path(path)

    def _import_pdf(self):
        path = filedialog.askopenfilename(
            title="Seleccionar PDF", filetypes=[("PDF", "*.pdf")]
        )
        if path:
            self._ingest_path(path)

    def _cancel_import(self):
        if self._cancel_event:
            self._cancel_event.set()

    def _on_import_error(self, msg: str):
        self._show_progress(False)
        self.toast(f"Error al importar: {msg}", "error")

    def _update_progress(self, fraction: float, msg: str):
        if not self.winfo_exists():
            return
        self._progress.set(max(0.0, min(1.0, fraction)))
        self._progress_label.configure(text=msg[:40])

    def _clear_text(self):
        self._text_input.delete("0.0", "end")

    def _show_progress(self, show: bool, msg: str = ""):
        if show:
            self._progress.set(0)
            self._progress_label.configure(text=msg)
            self._prog_row.pack(fill="x", padx=12, pady=(0, 8))
        else:
            self._prog_row.pack_forget()
            self._progress.set(0)
            self._progress_label.configure(text="")

    def _get_text(self) -> str:
        return self._text_input.get("0.0", "end").strip()

    def _ensure_bundle(self):
        text = self._get_text()
        if not text:
            self.toast("Ingresa o importa texto primero", "warning")
            return False
        if self._last_document is not None and self._last_document.pages:
            self._bundle = build_study_bundle_from_document(self._last_document)
        else:
            self._bundle = build_study_bundle(text)
        return True

    def _gen_summary(self):
        if not self._ensure_bundle():
            return
        self._summary_box.configure(state="normal")
        self._summary_box.delete("0.0", "end")
        self._summary_box.insert("0.0", self._bundle.summary or "(Sin resumen generado)")
        self._summary_box.configure(state="disabled")
        self.toast("Resumen generado", "success")

    def _export_summary_pdf(self):
        if not self._bundle:
            self.toast("Genera el resumen primero", "warning")
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF", "*.pdf")])
        if path:
            ok = export_text_pdf(self._bundle.summary, path, title="Resumen")
            self.toast("PDF exportado" if ok else "Error al exportar", "success" if ok else "error")

    def _export_markdown(self):
        """Exporta el documento importado o el texto actual como Markdown."""
        if self._last_document is not None:
            md_content = self._last_document.to_markdown()
        else:
            text = self._get_text()
            if not text:
                self.toast("No hay texto para exportar", "warning")
                return
            md_content = text

        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Texto", "*.txt")],
            title="Exportar como Markdown",
        )
        if not path:
            return
        try:
            import os
            fd, tmp = __import__("tempfile").mkstemp(
                dir=os.path.dirname(path), suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(md_content)
            os.replace(tmp, path)
            self.toast("Markdown exportado", "success")
        except Exception as exc:
            self.toast(f"Error al exportar: {exc}", "error")

    def on_hide(self):
        """Cancel any pending after-jobs when navigating away."""
        if self._quiz_next_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._quiz_next_job)
            self._quiz_next_job = None

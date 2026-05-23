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

        elif p.suffix.lower() in (".docx", ".doc"):
            info.update({
                "type": "docx",
                "type_label": "Documento Word — extracción directa",
                "needs_ocr": False,
                "pages": 1,
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


class StudyView(BaseView):
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

    def _build_summary_tab(self, parent):
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=8)
        self.primary_button(btn_row, "📋 Generar Resumen", self._gen_summary).pack(side="left", padx=4)
        self.secondary_button(btn_row, "📄 Exportar PDF", self._export_summary_pdf, 130).pack(side="left", padx=4)
        self.secondary_button(btn_row, "📝 Markdown", self._export_markdown, 100).pack(side="left")

        self._summary_box = ctk.CTkTextbox(parent, font=theme.FONT_BODY,
                                           fg_color=theme.BG_TERTIARY,
                                           text_color=theme.TEXT_PRIMARY,
                                           state="disabled", wrap="word")
        self._summary_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ── Tab Bloques ────────────────────────────────────────────────────────────

    def _build_blocks_tab(self, parent):
        """Vista de estructura del documento: bloques tipados."""
        # Barra de info + acciones post-ingesta
        info_row = ctk.CTkFrame(parent, fg_color="transparent")
        info_row.pack(fill="x", padx=8, pady=(8, 4))
        self._blocks_info = ctk.CTkLabel(
            info_row, text="Importa un documento para ver su estructura",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self._blocks_info.pack(side="left", fill="x", expand=True)

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(0, 4))
        self.secondary_button(btn_row, "🔄 Re-procesar", self._reprocess, 130).pack(side="left", padx=(0, 6))
        self.secondary_button(btn_row, "✍️ Reescribir", self._write_with_my_hand, 120).pack(side="left", padx=(0, 6))
        self.secondary_button(btn_row, "📝 Markdown", self._export_markdown, 100).pack(side="left")

        # Lista scrollable de bloques
        self._blocks_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._blocks_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._blocks_placeholder = ctk.CTkLabel(
            self._blocks_scroll,
            text="Sin documento cargado",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self._blocks_placeholder.pack(pady=40)

    _BLOCK_TYPE_COLORS = {
        "heading":   ("#d4a017", "#7a5500"),  # dorado
        "list_item": ("#2a7fbf", "#1a4a7a"),  # azul
        "code":      ("#3a8a4a", "#1a4a2a"),  # verde
        "caption":   ("#8a6a3a", "#5a3a10"),  # marrón
        "paragraph": ("#555555", "#2a2a2a"),  # gris neutro
        "unknown":   ("#444444", "#222222"),
    }

    def _update_blocks_tab(self, doc) -> None:
        """Rellena el tab Bloques con la estructura del Document."""
        if not self.winfo_exists():
            return

        # Limpiar contenido anterior
        for w in self._blocks_scroll.winfo_children():
            w.destroy()

        if doc is None or not doc.pages:
            self._blocks_info.configure(text="Sin documento cargado")
            ctk.CTkLabel(self._blocks_scroll, text="Sin documento cargado",
                         font=theme.FONT_BODY, text_color=theme.TEXT_MUTED).pack(pady=40)
            return

        # Info resumida
        total_blocks = sum(len(p.blocks) for p in doc.pages)
        backend = f" · {doc.ocr_backend_used}" if doc.ocr_backend_used else " · sin OCR"
        ms = doc.extraction_time_ms
        time_str = f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms}ms"
        type_labels = {
            "text_pdf": "PDF texto",  "scan_pdf": "PDF escaneado",
            "mixed_pdf": "PDF mixto", "docx": "Word",
            "image": "Imagen",        "folder": "Carpeta",
        }
        type_str = type_labels.get(doc.source_type, doc.source_type)
        self._blocks_info.configure(
            text=f"{type_str}{backend} | {doc.page_count} pág. | {total_blocks} bloques | {time_str}"
        )

        mode = ctk.get_appearance_mode().lower()

        for page in doc.pages:
            # Separador de página
            sep = ctk.CTkFrame(self._blocks_scroll, fg_color=theme.BG_TERTIARY,
                               corner_radius=6, height=24)
            sep.pack(fill="x", pady=(8, 2))
            ctk.CTkLabel(sep, text=f"── Página {page.page_number} ──",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(padx=8)

            for block in page.blocks:
                btype = block.block_type.value if hasattr(block.block_type, "value") else str(block.block_type)
                colors = self._BLOCK_TYPE_COLORS.get(btype, self._BLOCK_TYPE_COLORS["unknown"])
                chip_color = colors[1] if mode == "dark" else colors[0]

                row = ctk.CTkFrame(self._blocks_scroll, fg_color="transparent")
                row.pack(fill="x", padx=4, pady=1)

                chip = ctk.CTkLabel(row, text=btype, font=theme.FONT_SMALL,
                                    fg_color=chip_color, text_color=theme.TEXT_PRIMARY,
                                    corner_radius=4, width=80)
                chip.pack(side="left", padx=(0, 6))

                # Texto truncado (evitar widgets muy altos)
                preview = block.text.replace("\n", " ")
                if len(preview) > 120:
                    preview = preview[:117] + "…"
                hint = ""
                if block.is_handwritten:
                    hint = " ✍"
                ctk.CTkLabel(row, text=preview + hint,
                             font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
                             anchor="w", justify="left").pack(side="left", fill="x", expand=True)

    def _build_flashcard_tab(self, parent):
        self._card_counter = ctk.CTkLabel(parent, text="", font=theme.FONT_SMALL,
                                          text_color=theme.TEXT_SECONDARY)
        self._card_counter.pack(pady=(8, 4))

        self.primary_button(parent, "🃏 Generar Flashcards", self._gen_flashcards).pack(pady=4)

        self._card_frame = ctk.CTkFrame(parent, fg_color=theme.CARD_BG,
                                        corner_radius=14, border_width=2,
                                        border_color=theme.ACCENT_BLUE,
                                        cursor="hand2")
        self._card_frame.pack(fill="both", expand=True, padx=20, pady=8)

        self._card_text = ctk.CTkLabel(self._card_frame, text="Genera las flashcards primero",
                                       font=("Segoe UI", 14), text_color=theme.TEXT_PRIMARY,
                                       wraplength=350, justify="center")
        self._card_text.place(relx=0.5, rely=0.5, anchor="center")

        self._card_hint = ctk.CTkLabel(self._card_frame, text="",
                                       font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED)
        self._card_hint.place(relx=0.5, rely=0.85, anchor="center")

        self._card_frame.bind("<Button-1>", lambda e: self._flip_card())

        nav = ctk.CTkFrame(parent, fg_color="transparent")
        nav.pack(fill="x", padx=20, pady=(0, 10))
        self.secondary_button(nav, "← Anterior", self._prev_card, 110).pack(side="left")
        ctk.CTkButton(nav, text="Voltear 🔄", width=110, command=self._flip_card,
                      fg_color=theme.ACCENT_ORANGE, hover_color=theme.ACCENT_ORANGE_HOVER,
                      font=theme.FONT_BODY).pack(side="left", padx=8)
        self.secondary_button(nav, "Siguiente →", self._next_card, 110).pack(side="left")

    def _build_exam_tab(self, parent):
        self.primary_button(parent, "🎯 Iniciar Examen", self._start_exam).pack(pady=(12, 8))

        self._exam_progress = ctk.CTkLabel(parent, text="", font=theme.FONT_SMALL,
                                           text_color=theme.TEXT_SECONDARY)
        self._exam_progress.pack()

        self._exam_q = ctk.CTkLabel(parent, text="Presiona 'Iniciar Examen' para comenzar",
                                    font=("Segoe UI", 14), text_color=theme.TEXT_PRIMARY,
                                    wraplength=380, justify="center")
        self._exam_q.pack(fill="x", padx=16, pady=12)

        self._exam_entry = ctk.CTkEntry(parent, placeholder_text="Tu respuesta...",
                                        font=theme.FONT_BODY, fg_color=theme.BG_TERTIARY,
                                        text_color=theme.TEXT_PRIMARY, height=38)
        self._exam_entry.pack(fill="x", padx=16, pady=4)
        self._exam_entry.bind("<Return>", lambda e: self._submit_answer())

        self.primary_button(parent, "Responder ✓", self._submit_answer).pack(pady=6)

        self._exam_feedback = ctk.CTkLabel(parent, text="", font=theme.FONT_BODY,
                                           text_color=theme.ACCENT_GREEN)
        self._exam_feedback.pack(pady=4)

    def _build_concepts_tab(self, parent):
        self.primary_button(parent, "🔑 Generar Conceptos", self._gen_concepts).pack(pady=(12, 8))
        self._concepts_frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._concepts_frame.pack(fill="both", expand=True, padx=8, pady=4)

    def _on_backend_change(self, new_name: str):
        self._ocr.switch_backend(new_name)
        self.toast(f"Backend OCR: {new_name}", "info")

    # ── Importación ────────────────────────────────────────────────────────────

    def _import_document(self):
        """Importa cualquier formato soportado con preview previo."""
        path = filedialog.askopenfilename(
            title="Importar documento",
            filetypes=[
                ("Documentos", "*.pdf *.docx *.doc *.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx *.doc"),
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
                self.after(0, lambda: self._on_import_error(str(exc)))

        threading.Thread(target=_read, daemon=True).start()

    def _on_ocr_done(self, text: str):
        if not self.winfo_exists():
            return
        self._show_progress(False)
        self._text_input.delete("0.0", "end")
        self._text_input.insert("0.0", text)

    def _import_word(self):
        path = filedialog.askopenfilename(
            title="Seleccionar Word", filetypes=[("Word", "*.docx *.doc")]
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

    def _gen_flashcards(self):
        if not self._ensure_bundle():
            return
        self._flashcards = self._bundle.flashcards
        self._card_index = 0
        self._card_front = True
        if self._flashcards:
            self._show_card()
            self.toast(f"{len(self._flashcards)} flashcards generadas", "success")
        else:
            self.toast("No se pudieron generar flashcards de este texto", "warning")

    def _show_card(self):
        if not self._flashcards:
            return
        idx = self._card_index % len(self._flashcards)
        card = self._flashcards[idx]
        self._card_counter.configure(text=f"Tarjeta {idx + 1} de {len(self._flashcards)}")
        if self._card_front:
            self._card_text.configure(text=card.question, text_color=theme.TEXT_PRIMARY)
            self._card_hint.configure(text="(Haz clic para ver la respuesta)")
            self._card_frame.configure(border_color=theme.ACCENT_BLUE)
        else:
            self._card_text.configure(text=card.answer, text_color=theme.ACCENT_GREEN)
            self._card_hint.configure(text=f"Tema: {card.topic}")
            self._card_frame.configure(border_color=theme.ACCENT_GREEN)

    def _flip_card(self):
        if not self._flashcards:
            return
        self._card_front = not self._card_front
        self._animate_card_flip()

    def _animate_card_flip(self):
        """Simulate a 3D card flip by scaling text width down then up."""
        original_wraplength = 350
        steps_shrink = 5
        steps_grow = 5
        step_ms = 20

        def shrink(i):
            if not self.winfo_exists():
                return
            t = i / steps_shrink
            scale = 1.0 - t
            wl = max(1, int(original_wraplength * scale))
            try:
                self._card_text.configure(wraplength=wl, text="")
                self._card_frame.configure(
                    border_color=theme.ACCENT_BLUE if self._card_front else theme.ACCENT_GREEN
                )
            except Exception:
                pass
            if i < steps_shrink:
                self.after(step_ms, lambda: shrink(i + 1))
            else:
                self._show_card()
                self.after(step_ms, lambda: grow(0))

        def grow(i):
            if not self.winfo_exists():
                return
            t = (i + 1) / steps_grow
            wl = max(1, int(original_wraplength * t))
            with contextlib.suppress(Exception):
                self._card_text.configure(wraplength=wl)
            if i < steps_grow - 1:
                self.after(step_ms, lambda: grow(i + 1))
            else:
                with contextlib.suppress(Exception):
                    self._card_text.configure(wraplength=original_wraplength)

        shrink(0)

    def _next_card(self):
        if not self._flashcards:
            return
        self._card_index = (self._card_index + 1) % len(self._flashcards)
        self._card_front = True
        self._show_card()

    def _prev_card(self):
        if not self._flashcards:
            return
        self._card_index = (self._card_index - 1) % len(self._flashcards)
        self._card_front = True
        self._show_card()

    def _start_exam(self):
        if not self._ensure_bundle():
            return
        self._quiz_questions = self._bundle.quiz_questions
        if not self._quiz_questions:
            self.toast("No se pudieron generar preguntas de este texto", "warning")
            return
        self._quiz_index = 0
        self._quiz_score = 0
        self._quiz_active = True
        self._show_question()
        self.toast(f"Examen iniciado: {len(self._quiz_questions)} preguntas", "info")

    def _show_question(self):
        if not self._quiz_questions:
            self._quiz_active = False
            return
        if self._quiz_index >= len(self._quiz_questions):
            pct = int(self._quiz_score / len(self._quiz_questions) * 100)
            color = theme.ACCENT_GREEN if pct >= 60 else theme.ACCENT_ORANGE
            self._exam_q.configure(
                text=f"🎉 Examen terminado\n\nPuntaje: {self._quiz_score}/{len(self._quiz_questions)}",
                text_color=color,
            )
            self._exam_progress.configure(text="")
            self._quiz_active = False
            # Animate score percentage counting up
            count_up(self._exam_feedback, pct, prefix="Resultado: ", suffix="%",
                     steps=25, step_ms=28, is_float=False)
            self._exam_feedback.configure(text_color=color)
            return
        q = self._quiz_questions[self._quiz_index]
        self._exam_q.configure(text=q.question, text_color=theme.TEXT_PRIMARY)
        self._exam_progress.configure(
            text=f"Pregunta {self._quiz_index + 1} de {len(self._quiz_questions)}  |  Puntaje: {self._quiz_score}"
        )
        self._exam_entry.delete(0, "end")
        self._exam_feedback.configure(text="")

    def _submit_answer(self):
        if not self._quiz_active or self._quiz_index >= len(self._quiz_questions):
            return
        given = self._exam_entry.get().strip()
        q = self._quiz_questions[self._quiz_index]
        score = grade_answer(q.expected_answer, given, q.keywords)
        if score >= 40:
            self._quiz_score += 1
            self._exam_feedback.configure(text=f"✓ ¡Correcto! ({score}%)", text_color=theme.ACCENT_GREEN)
        else:
            self._exam_feedback.configure(
                text=f"✗ Respuesta esperada: {q.expected_answer[:80]}",
                text_color=theme.ACCENT_RED,
            )
        self._quiz_index += 1
        if self._quiz_next_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._quiz_next_job)
        self._quiz_next_job = self.after(1400, self._show_question)

    def on_hide(self):
        """Cancel any pending after-jobs when navigating away."""
        if self._quiz_next_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._quiz_next_job)
            self._quiz_next_job = None

    def _gen_concepts(self):
        if not self._ensure_bundle():
            return
        for w in self._concepts_frame.winfo_children():
            w.destroy()
        terms = self._bundle.key_terms
        if not terms:
            ctk.CTkLabel(self._concepts_frame, text="No se encontraron conceptos",
                         font=theme.FONT_BODY, text_color=theme.TEXT_MUTED).pack(pady=20)
            return
        row = ctk.CTkFrame(self._concepts_frame, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=4)
        for col_count, term in enumerate(terms, start=1):
            chip = ctk.CTkFrame(row, fg_color=theme.ACCENT_BLUE, corner_radius=20)
            chip.pack(side="left", padx=4, pady=4)
            ctk.CTkLabel(chip, text=f"  {term}  ", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_PRIMARY).pack(padx=6, pady=4)
            if col_count % 4 == 0:
                row = ctk.CTkFrame(self._concepts_frame, fg_color="transparent")
                row.pack(fill="x", padx=4, pady=2)
        self.toast(f"{len(terms)} conceptos identificados", "success")

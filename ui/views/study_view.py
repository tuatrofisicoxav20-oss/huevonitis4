import contextlib
import threading

import customtkinter as ctk

from core.ocr.engine import OCREngine
from core.studycore.models import Flashcard, QuizQuestion, StudyBundle
from ui import theme
from ui.views.base_view import BaseView
from ui.views.study_view_bundle import StudyBundleMixin
from ui.views.study_view_flashcards import StudyFlashcardsMixin
from ui.views.study_view_import import StudyImportMixin
from ui.views.study_view_tabs import StudyTabsBuildMixin


class StudyView(
    StudyTabsBuildMixin,
    StudyFlashcardsMixin,
    StudyImportMixin,
    StudyBundleMixin,
    BaseView,
):
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
                                         fg_color=theme.ACCENT_RED, hover_color=theme.ACCENT_RED_HOVER,
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

    def on_hide(self):
        """Cancel any pending after-jobs when navigating away."""
        if self._quiz_next_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._quiz_next_job)
            self._quiz_next_job = None

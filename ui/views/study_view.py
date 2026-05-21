import contextlib
import threading
from tkinter import filedialog

import customtkinter as ctk

from core.export.pdf_exporter import export_text_pdf
from core.ocr.engine import OCREngine
from core.studycore.builder import build_study_bundle, grade_answer
from core.studycore.models import Flashcard, QuizQuestion, StudyBundle
from ui import theme
from ui.animations import count_up
from ui.views.base_view import BaseView


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
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 6))

        self._text_input = ctk.CTkTextbox(parent, font=theme.FONT_BODY,
                                          fg_color=theme.BG_TERTIARY,
                                          text_color=theme.TEXT_PRIMARY, wrap="word")
        self._text_input.pack(fill="both", expand=True, padx=12, pady=4)

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=10)

        self.primary_button(btn_row, "📷 Imagen (OCR)", self._ocr_image, 130).pack(side="left", padx=4)
        self.primary_button(btn_row, "📄 Word", self._import_word, 90).pack(side="left", padx=4)
        self.secondary_button(btn_row, "🗑 Limpiar", self._clear_text, 90).pack(side="left", padx=4)

        self._progress = ctk.CTkProgressBar(parent, mode="indeterminate",
                                            fg_color=theme.BG_TERTIARY,
                                            progress_color=theme.ACCENT_BLUE)
        self._progress.pack(fill="x", padx=12, pady=(0, 8))
        self._progress.pack_forget()

    def _build_right(self, parent):
        self._tabs = ctk.CTkTabview(parent, fg_color="transparent",
                                    segmented_button_fg_color=theme.BG_TERTIARY,
                                    segmented_button_selected_color=theme.ACCENT_BLUE,
                                    segmented_button_unselected_color=theme.BG_TERTIARY,
                                    text_color=theme.TEXT_PRIMARY)
        self._tabs.pack(fill="both", expand=True, padx=8, pady=8)

        self._tabs.add("Resumen")
        self._tabs.add("Flashcards")
        self._tabs.add("Examen")
        self._tabs.add("Conceptos")

        self._build_summary_tab(self._tabs.tab("Resumen"))
        self._build_flashcard_tab(self._tabs.tab("Flashcards"))
        self._build_exam_tab(self._tabs.tab("Examen"))
        self._build_concepts_tab(self._tabs.tab("Conceptos"))

    def _build_summary_tab(self, parent):
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=8)
        self.primary_button(btn_row, "📋 Generar Resumen", self._gen_summary).pack(side="left", padx=4)
        self.secondary_button(btn_row, "📄 Exportar PDF", self._export_summary_pdf, 130).pack(side="left")

        self._summary_box = ctk.CTkTextbox(parent, font=theme.FONT_BODY,
                                           fg_color=theme.BG_TERTIARY,
                                           text_color=theme.TEXT_PRIMARY,
                                           state="disabled", wrap="word")
        self._summary_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

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

    def _ocr_image(self):
        path = filedialog.askopenfilename(
            title="Seleccionar imagen",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp")],
        )
        if not path:
            return
        self._show_progress(True)
        self.toast("Procesando imagen con OCR...", "info")

        def worker():
            text = self._ocr.extract_text(path)
            self.after(0, lambda: self._on_ocr_done(text))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ocr_done(self, text: str):
        if not self.winfo_exists():
            return
        self._show_progress(False)
        self._text_input.delete("0.0", "end")
        self._text_input.insert("0.0", text)
        self.toast("OCR completado", "success")

    def _import_word(self):
        path = filedialog.askopenfilename(
            title="Seleccionar Word", filetypes=[("Word", "*.docx *.doc")]
        )
        if not path:
            return
        self.toast("Importando Word…", "info")

        def _read():
            text = self._ocr.read_docx(path)
            def _done():
                self._text_input.delete("0.0", "end")
                self._text_input.insert("0.0", text)
                self.toast("Archivo Word importado", "success")
            self.after(0, _done)

        threading.Thread(target=_read, daemon=True).start()

    def _clear_text(self):
        self._text_input.delete("0.0", "end")

    def _show_progress(self, show: bool):
        if show:
            self._progress.pack(fill="x", padx=12, pady=(0, 8))
            self._progress.start()
        else:
            self._progress.stop()
            self._progress.pack_forget()

    def _get_text(self) -> str:
        return self._text_input.get("0.0", "end").strip()

    def _ensure_bundle(self):
        text = self._get_text()
        if not text:
            self.toast("Ingresa o importa texto primero", "warning")
            return False
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
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF", "*.pdf")])
        if path:
            ok = export_text_pdf(self._bundle.summary, path, title="Resumen")
            self.toast("PDF exportado" if ok else "Error al exportar", "success" if ok else "error")

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

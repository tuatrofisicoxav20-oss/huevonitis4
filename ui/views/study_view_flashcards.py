"""StudyFlashcardsMixin — flashcards (con animación de flip), exam y conceptos.

Separado de study_view.py. Depende de:
  • self._bundle, self._flashcards, self._quiz_questions, etc.
  • self._ensure_bundle() (en StudyView principal)
  • Widgets: self._card_*, self._exam_*, self._concepts_frame
"""
import contextlib

import customtkinter as ctk

from core.studycore.builder import grade_answer
from ui import theme
from ui.animations import count_up


class StudyFlashcardsMixin:
    """Lógica de flashcards (flip animado), examen (grading) y conceptos."""

    # ── Flashcards ──────────────────────────────────────────────────

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
        """Simula un flip 3D escalando wraplength del texto a 0 y de vuelta."""
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
                    border_color=theme.ACCENT_BLUE if self._card_front else theme.ACCENT_GREEN,
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

    # ── Examen ──────────────────────────────────────────────────────

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
            self._exam_feedback.configure(text=f"✓ ¡Correcto! ({score}%)",
                                          text_color=theme.ACCENT_GREEN)
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

    # ── Conceptos ──────────────────────────────────────────────────

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

"""StudyTabsBuildMixin — construye los 5 tabs (Resumen, Bloques, Flashcards, Examen, Conceptos).

Separado de study_view.py para mantener cada archivo manejable. Solo
construye widgets; los handlers (_gen_summary, _gen_flashcards, etc.)
viven en StudyView.
"""
import customtkinter as ctk

from ui import theme

# U2: la paleta de bloques vive en theme.DOC_BLOCK_COLORS (tokens)
_BLOCK_TYPE_COLORS = theme.DOC_BLOCK_COLORS


class StudyTabsBuildMixin:
    """Construcción de los 5 tabs de StudyView."""

    _BLOCK_TYPE_COLORS = _BLOCK_TYPE_COLORS

    def _build_summary_tab(self, parent):
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=8)
        self.primary_button(btn_row, "📋 Generar Resumen", self._gen_summary).pack(side="left", padx=4)
        self.secondary_button(btn_row, "📄 Exportar PDF", self._export_summary_pdf, 130).pack(side="left", padx=4)
        self.secondary_button(btn_row, "📝 Markdown", self._export_markdown, 100).pack(side="left")

        self._summary_box = ctk.CTkTextbox(
            parent, font=theme.FONT_BODY,
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            state="disabled", wrap="word",
        )
        self._summary_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _build_blocks_tab(self, parent):
        """Vista de estructura del documento: bloques tipados."""
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

        self._blocks_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._blocks_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._blocks_placeholder = ctk.CTkLabel(
            self._blocks_scroll,
            text="Sin documento cargado",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self._blocks_placeholder.pack(pady=40)

    def _update_blocks_tab(self, doc) -> None:
        """Rellena el tab Bloques con la estructura del Document."""
        if not self.winfo_exists():
            return
        for w in self._blocks_scroll.winfo_children():
            w.destroy()

        if doc is None or not doc.pages:
            self._blocks_info.configure(text="Sin documento cargado")
            ctk.CTkLabel(self._blocks_scroll, text="Sin documento cargado",
                         font=theme.FONT_BODY, text_color=theme.TEXT_MUTED).pack(pady=40)
            return

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
            sep = ctk.CTkFrame(self._blocks_scroll, fg_color=theme.BG_TERTIARY,
                               corner_radius=6, height=24)
            sep.pack(fill="x", pady=(8, 2))
            ctk.CTkLabel(sep, text=f"── Página {page.page_number} ──",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(padx=8)

            for block in page.blocks:
                btype = block.block_type.value if hasattr(block.block_type, "value") else str(block.block_type)
                colors = _BLOCK_TYPE_COLORS.get(btype, _BLOCK_TYPE_COLORS["unknown"])
                chip_color = colors[1] if mode == "dark" else colors[0]

                row = ctk.CTkFrame(self._blocks_scroll, fg_color="transparent")
                row.pack(fill="x", padx=4, pady=1)

                chip = ctk.CTkLabel(row, text=btype, font=theme.FONT_SMALL,
                                    fg_color=chip_color, text_color=theme.TEXT_PRIMARY,
                                    corner_radius=4, width=80)
                chip.pack(side="left", padx=(0, 6))

                preview = block.text.replace("\n", " ")
                if len(preview) > 120:
                    preview = preview[:117] + "…"
                hint = " ✍" if block.is_handwritten else ""
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
                                       font=theme.get_font(size=14), text_color=theme.TEXT_PRIMARY,
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
                                    font=theme.get_font(size=14), text_color=theme.TEXT_PRIMARY,
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

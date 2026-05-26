"""ExtractorTabBuildMixin — construye toda la UI del tab Extractor.

Separado de extractor_tab.py para mantener cada archivo manejable.
La lógica (extract, label, save_to_bank, etc.) sigue en extractor_tab.py.
"""
import customtkinter as ctk

from ui import theme


class ExtractorTabBuildMixin:
    """Construcción de widgets de Extractor (panel izquierdo + derecho)."""

    def _build_extractor(self, parent):
        main = ctk.CTkFrame(parent, fg_color="transparent")
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=42)
        main.columnconfigure(1, weight=58)
        main.rowconfigure(0, weight=1)

        left = self.card_frame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_extractor_left(left)

        right = self.card_frame(main)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_extractor_right(right)

    def _build_extractor_left(self, parent):
        ctk.CTkLabel(
            parent, text="Imagen de apunte",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(padx=14, pady=(14, 4), anchor="w")

        self._img_preview = ctk.CTkLabel(
            parent,
            text="Sin imagen\n\nPresiona 'Cargar imagen'",
            fg_color=theme.BG_TERTIARY,
            corner_radius=8,
            text_color=theme.TEXT_MUTED,
            height=200,
        )
        self._img_preview.pack(fill="x", padx=12, pady=4)

        btn_row0 = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row0.pack(fill="x", padx=12, pady=(4, 2))
        self.primary_button(btn_row0, "📷 Cargar imagen", self._load_image).pack(side="left")
        self._img_name_label = ctk.CTkLabel(
            btn_row0, text="Sin imagen cargada",
            font=theme.FONT_SMALL, text_color=theme.ACCENT_RED,
        )
        self._img_name_label.pack(side="left", padx=8)

        self._build_adjustments(parent)
        self._build_auto_mode_section(parent)
        self._build_reference_text(parent)
        self._build_pipeline_panel(parent)
        self._build_action_bar(parent)

    def _build_adjustments(self, parent):
        adj_header = ctk.CTkFrame(parent, fg_color="transparent")
        adj_header.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            adj_header, text="Ajustes de imagen",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")
        self._adj_toggle_btn = ctk.CTkButton(
            adj_header, text="▼", width=28, height=22,
            fg_color="transparent", hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_MUTED, font=("Segoe UI", 10),
            command=self._toggle_adjustments,
        )
        self._adj_toggle_btn.pack(side="right")

        self._adj_frame = ctk.CTkFrame(
            parent, fg_color=theme.BG_TERTIARY, corner_radius=8,
            border_width=1, border_color=theme.BORDER,
        )
        self._adj_frame.pack(fill="x", padx=12, pady=(0, 6))
        adj_frame = self._adj_frame

        sliders_grid = ctk.CTkFrame(adj_frame, fg_color="transparent")
        sliders_grid.pack(fill="x", padx=8, pady=(4, 8))
        sliders_grid.columnconfigure(1, weight=1)

        def make_slider(row, label, from_, to, default, callback=None):
            ctk.CTkLabel(
                sliders_grid, text=label, font=theme.FONT_SMALL,
                text_color=theme.TEXT_SECONDARY, width=70, anchor="w",
            ).grid(row=row, column=0, sticky="w", pady=2)
            val_lbl = ctk.CTkLabel(
                sliders_grid, text=str(default),
                font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, width=32,
            )
            val_lbl.grid(row=row, column=2, padx=(4, 0))
            slider = ctk.CTkSlider(
                sliders_grid, from_=from_, to=to,
                number_of_steps=int(to - from_),
                progress_color=theme.ACCENT_ORANGE,
                button_color=theme.ACCENT_ORANGE,
                button_hover_color=theme.ACCENT_ORANGE_HOVER,
            )
            slider.set(default)
            slider.grid(row=row, column=1, sticky="ew", padx=4)

            def on_change(v, lbl=val_lbl, cb=callback):
                lbl.configure(text=f"{float(v):+.0f}" if float(v) != 0 else "0")
                if cb:
                    cb()

            slider.configure(command=on_change)
            return slider

        self._brightness_slider = make_slider(0, "Brillo", -80, 80, 0, self._apply_preview)
        self._contrast_slider   = make_slider(1, "Contraste", -80, 80, 0, self._apply_preview)
        self._rotation_slider   = make_slider(2, "Rotación", -15, 15, 0, self._apply_preview)

        remove_lines_row = ctk.CTkFrame(adj_frame, fg_color="transparent")
        remove_lines_row.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(
            remove_lines_row, text="Quitar líneas de cuaderno",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")
        self._remove_lines_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            remove_lines_row, text="", variable=self._remove_lines_var,
            onvalue=True, offvalue=False,
            progress_color=theme.ACCENT_GREEN,
            button_color=theme.ACCENT_GREEN_LIGHT,
            width=40,
        ).pack(side="right")

    def _build_auto_mode_section(self, parent):
        auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        auto_row.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(
            auto_row, text="🤖 Modo automático (sin texto de referencia)",
            font=theme.FONT_SMALL, text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        self._auto_mode_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            auto_row, text="", variable=self._auto_mode_var,
            onvalue=True, offvalue=False,
            progress_color=theme.ACCENT_BLUE,
            button_color=theme.ACCENT_BLUE_HOVER,
            width=40,
            command=self._on_auto_mode_toggle,
        ).pack(side="right")

        self._auto_hint_label = ctk.CTkLabel(
            parent,
            text=("Detecta y clasifica cada letra automáticamente; "
                  "filtra líneas y ruido. Calidad depende del labeler instalado."),
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            wraplength=460, justify="left",
        )
        self._auto_hint_label.pack(anchor="w", padx=14, pady=(0, 4))

    def _build_reference_text(self, parent):
        self._adj_ref_label = ctk.CTkLabel(
            parent,
            text=("Texto de referencia — una línea por renglón. "
                  "Los espacios separan palabras (mejora la alineación); "
                  "comas y puntos y coma se ignoran automáticamente."),
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
            wraplength=460, justify="left",
        )
        self._adj_ref_label.pack(anchor="w", padx=12, pady=(8, 2))
        self._ref_text = ctk.CTkTextbox(
            parent, font=theme.FONT_BODY,
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            height=80,
            border_color=theme.BORDER, border_width=1,
        )
        self._ref_text.pack(fill="x", padx=12, pady=(0, 4))
        self._ref_example_label = ctk.CTkLabel(
            parent,
            text=("Ejemplo: hola mundo abcdefg  /  segunda línea: ñoño piña"),
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._ref_example_label.pack(anchor="w", padx=14, pady=(0, 4))

    def _build_action_bar(self, parent):
        action_row = ctk.CTkFrame(parent, fg_color="transparent")
        action_row.pack(fill="x", padx=12, pady=4)
        self._extract_btn = ctk.CTkButton(
            action_row,
            text="⚙️  Procesar y extraer",
            command=self._extract,
            height=38,
            fg_color=theme.ACCENT_ORANGE,
            hover_color=theme.ACCENT_ORANGE_HOVER,
            font=("Segoe UI", 12, "bold"),
            corner_radius=9,
        )
        self._extract_btn.pack(side="left", padx=(0, 6))
        self.secondary_button(action_row, "🔍 Ver preprocesamiento",
                              self._show_preprocess_preview, width=160).pack(side="left")

        self._extract_error = ctk.CTkLabel(
            parent, text="",
            font=theme.FONT_SMALL, text_color=theme.ACCENT_RED,
        )
        self._extract_error.pack(anchor="w", padx=14)

        self._extract_status = ctk.CTkLabel(
            parent, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._extract_status.pack(anchor="w", padx=14)

        self._extract_progress = ctk.CTkProgressBar(
            parent, mode="indeterminate",
            fg_color=theme.BG_TERTIARY,
            progress_color=theme.ACCENT_GREEN,
            height=6,
            corner_radius=3,
        )
        self._extract_progress.pack(fill="x", padx=12, pady=2)
        self._extract_progress.pack_forget()

    def _toggle_adjustments(self):
        self._adj_collapsed = not self._adj_collapsed
        if self._adj_collapsed:
            self._adj_frame.pack_forget()
            self._adj_toggle_btn.configure(text="▶")
        else:
            self._adj_frame.pack(fill="x", padx=12, pady=(0, 6),
                                 before=self._adj_ref_label)
            self._adj_toggle_btn.configure(text="▼")

    def _build_extractor_right(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            header, text="Glifos extraídos",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")

        self._glyph_count_label = ctk.CTkLabel(
            header, text="0 glifos",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        )
        self._glyph_count_label.pack(side="right")

        self._detector_chip = ctk.CTkLabel(
            header, text="  ⚙ inicializando…  ",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            fg_color=theme.BG_TERTIARY, corner_radius=10,
            height=22,
        )
        self._detector_chip.pack(side="right", padx=(0, 6))
        self.after(50, self._refresh_pipeline_chip)

        self._glyphs_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._glyphs_scroll.pack(fill="both", expand=True, padx=8, pady=4)

        footer = ctk.CTkFrame(parent, fg_color="transparent")
        footer.pack(fill="x", padx=12, pady=8)

        self._quality_summary = ctk.CTkLabel(
            footer, text="",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        )
        self._quality_summary.pack(side="left")

        ctk.CTkButton(
            footer,
            text="💾  Guardar en banco",
            command=self._save_to_bank,
            height=34,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 11, "bold"),
            corner_radius=8,
        ).pack(side="right")

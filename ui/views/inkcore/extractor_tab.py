"""ExtractorTabMixin — tab 📷 Extractor de InkCoreView."""
import logging
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import config
from core.inkcore.extractor import ExtractionOptions
from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class ExtractorTabMixin:
    """Tab de extracción individual de glifos; mezclado en InkCoreView."""

    # ── Build ──────────────────────────────────────────────────────

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

        self._adj_ref_label = ctk.CTkLabel(
            parent,
            text="Texto de referencia — una línea por renglón, sin comas entre letras:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
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
        ctk.CTkLabel(
            parent,
            text="Ejemplo: abcdefghijklmnñ  /  segunda línea: opqrstuvwxyz",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=14, pady=(0, 4))

        self._build_pipeline_panel(parent)

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

    # ── Image loading ──────────────────────────────────────────────

    def _load_image(self):
        path = filedialog.askopenfilename(
            title="Cargar imagen de apunte",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp")],
        )
        if not path:
            return
        self._image_path = path
        name = Path(path).name
        self._img_name_label.configure(text=f"✓ {name}", text_color=theme.ACCENT_GREEN)
        self._extract_error.configure(text="")
        logger.info("Imagen cargada: %s", path)
        if _PIL_OK:
            try:
                self._original_img = Image.open(path).convert("RGB")
                self._apply_preview()
            except Exception as e:
                logger.warning("No se pudo abrir imagen para preview: %s", e)
                self._img_preview.configure(text=name)
        else:
            self._img_preview.configure(text=name)

    def _apply_preview(self, *_):
        if not _PIL_OK or self._original_img is None:
            return
        img = self._original_img.copy()
        rot = float(self._rotation_slider.get())
        if abs(rot) > 0.1:
            img = img.rotate(rot, expand=False, fillcolor=(255, 255, 255))
        br = float(self._brightness_slider.get())
        if abs(br) > 0.5:
            factor = 1.0 + br / 100.0
            img = ImageEnhance.Brightness(img).enhance(max(0.1, factor))
        co = float(self._contrast_slider.get())
        if abs(co) > 0.5:
            factor = 1.0 + co / 100.0
            img = ImageEnhance.Contrast(img).enhance(max(0.1, factor))
        img.thumbnail((380, 200), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._img_preview.configure(image=photo, text="")
        self._img_preview._image_ref = photo

    # ── Extraction ─────────────────────────────────────────────────

    def _extract(self):
        logger.info("_extract() llamado")
        if not self._image_path:
            logger.warning("_extract: sin imagen")
            self._extract_error.configure(
                text="⚠ Primero debes cargar una imagen con el botón '📷 Cargar imagen'"
            )
            self.toast("Carga una imagen primero", "warning")
            return

        ref = self._ref_text.get("1.0", "end").strip()
        logger.info("_extract: texto de referencia = %r", ref[:80])
        if not ref:
            logger.warning("_extract: texto de referencia vacío")
            self._extract_error.configure(
                text="⚠ Escribe el texto de referencia en el cuadro de texto de arriba"
            )
            self.toast("Escribe el texto de referencia", "warning")
            return

        self._extract_error.configure(text="")
        use_p = bool(self._use_pipeline_var.get())
        cfg = self._get_pipeline_config() if use_p else None
        opts = ExtractionOptions(
            remove_lines=self._remove_lines_var.get(),
            brightness=float(self._brightness_slider.get()),
            contrast=float(self._contrast_slider.get()),
            rotation_deg=float(self._rotation_slider.get()),
            use_pipeline=use_p,
            pipeline_config=cfg,
            min_quality=float(self._min_quality_slider.get()) if use_p else config.MIN_GLYPH_QUALITY,
        )
        logger.info("_extract: opts=%s, iniciando hilo", opts)

        self._extract_progress.pack(fill="x", padx=12, pady=2)
        self._extract_progress.start()
        self._extract_btn.configure(state="disabled")
        self._extract_status.configure(
            text="Procesando imagen...", text_color=theme.ACCENT_ORANGE,
        )
        self.toast("Extrayendo glifos...", "info")

        image_path = self._image_path

        def worker():
            logger.info("worker: iniciando extracción")
            try:
                glyphs = self._pipeline.extract(image_path, ref, opts)
                logger.info("worker: extracción completada — %d glifos", len(glyphs))
            except Exception as exc:
                logger.error("worker: error en extracción: %s", exc, exc_info=True)
                glyphs = []
            try:
                self.after(0, lambda: self._on_extracted(glyphs))
            except Exception as e:
                logger.error("worker: error al programar callback: %s", e)

        threading.Thread(target=worker, daemon=True).start()
        logger.info("_extract: hilo iniciado")

    def _on_extracted(self, glyphs: list):
        if not self.winfo_exists():
            return
        self._extract_progress.stop()
        self._extract_progress.pack_forget()
        self._extract_btn.configure(state="normal")
        self._extracted = glyphs
        self._show_extracted_grid()
        if glyphs:
            gold   = sum(1 for g in glyphs if g.tier == "Gold")
            silver = sum(1 for g in glyphs if g.tier == "Silver")
            bronze = sum(1 for g in glyphs if g.tier == "Bronze")
            self._extract_status.configure(
                text=(f"✓ {len(glyphs)} glifos  —  "
                      f"🥇 Gold: {gold}  🥈 Silver: {silver}  🥉 Bronze: {bronze}"),
                text_color=theme.ACCENT_GREEN,
            )
            self.toast(f"{len(glyphs)} glifos extraídos", "success")
        else:
            self._extract_status.configure(
                text="Sin glifos — sube brillo/contraste, o prueba sin 'Quitar líneas'",
                text_color=theme.ACCENT_RED,
            )
            self.toast("Sin glifos. Revisa el log: ~/.local/share/huevonitis4/app.log", "warning")

    def _show_extracted_grid(self):
        for w in self._glyphs_scroll.winfo_children():
            w.destroy()
        self._glyph_photos.clear()
        self._glyph_count_label.configure(text=f"{len(self._extracted)} glifos")

        if not self._extracted:
            ctk.CTkLabel(
                self._glyphs_scroll, text="Sin glifos",
                text_color=theme.TEXT_MUTED, font=theme.FONT_BODY,
            ).pack(pady=20)
            self._quality_summary.configure(text="")
            return

        avg_q = sum(g.quality_score for g in self._extracted) / len(self._extracted)

        if avg_q >= 0.75:
            q_color = theme.ACCENT_GREEN
            q_label = "Excelente"
        elif avg_q >= 0.5:
            q_color = theme.ACCENT_ORANGE
            q_label = "Buena"
        else:
            q_color = theme.ACCENT_RED
            q_label = "Baja"

        self._quality_summary.configure(
            text=f"Calidad promedio: {avg_q:.0%} ({q_label})",
            text_color=q_color,
        )

        LOW_QUALITY = 0.4
        cols = 8
        current_row = None
        for i, g in enumerate(self._extracted):
            if i % cols == 0:
                current_row = ctk.CTkFrame(self._glyphs_scroll, fg_color="transparent")
                current_row.pack(fill="x", pady=2)
            tc = self._tier_text_color(g.tier)
            low_q = g.quality_score < LOW_QUALITY
            cell = ctk.CTkFrame(
                current_row,
                fg_color=theme.CARD_BG,
                corner_radius=6,
                width=54, height=68,
                border_width=1,
                border_color=theme.ACCENT_RED if low_q else self._tier_border(g.tier),
            )
            cell.pack(side="left", padx=3)
            cell.pack_propagate(False)

            del_btn = ctk.CTkButton(
                cell, text="×", width=16, height=16,
                font=("Segoe UI", 10, "bold"),
                fg_color="#3a1a1a", hover_color=theme.ACCENT_RED,
                text_color=theme.ACCENT_RED, corner_radius=8,
                command=lambda idx=i: self._delete_extracted_glyph(idx),
            )
            del_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-1, y=1)

            photo = self._get_thumb(g.image_path, 42, 46)
            if photo is not None:
                ctk.CTkLabel(cell, image=photo, text="").pack(pady=(4, 0))
            else:
                ctk.CTkLabel(
                    cell, text="?", font=("Segoe UI", 16),
                    text_color=theme.TEXT_MUTED,
                ).pack(pady=(8, 0))

            ctk.CTkLabel(cell, text=g.char or "?", font=theme.FONT_SMALL, text_color=tc).pack()
            ctk.CTkLabel(cell, text=f"{g.quality_score:.0%}",
                         font=("", 8), text_color=theme.TEXT_MUTED).pack()

    @staticmethod
    def _tier_text_color(tier: str) -> str:
        return {
            "Gold":   theme.ACCENT_YELLOW,
            "Silver": "#C0C0C0",
            "Bronze": "#CD7F32",
        }.get(tier, "#888")

    @staticmethod
    def _tier_border(tier: str) -> str:
        return {
            "Gold":   theme.ACCENT_GREEN,
            "Silver": theme.ACCENT_ORANGE,
            "Bronze": theme.BORDER,
        }.get(tier, theme.BORDER)

    def _delete_extracted_glyph(self, idx: int):
        if 0 <= idx < len(self._extracted):
            self._extracted.pop(idx)
            self._show_extracted_grid()

    def _save_to_bank(self):
        if not self._extracted:
            self.toast("No hay glifos para guardar", "warning")
            return
        saved = self._pipeline.save_glyphs_to_bank(self._extracted)
        dupes = len(self._extracted) - saved
        msg = f"{saved} glifos guardados"
        if dupes:
            msg += f"  ({dupes} duplicados omitidos)"
        self.toast(msg, "success")
        self._refresh_bank()

    # ── Preprocess preview ─────────────────────────────────────────

    def _show_preprocess_preview(self):
        if not self._image_path:
            self.toast("Carga una imagen primero", "warning")
            return
        opts = ExtractionOptions(
            remove_lines=self._remove_lines_var.get(),
            brightness=float(self._brightness_slider.get()),
            contrast=float(self._contrast_slider.get()),
            rotation_deg=float(self._rotation_slider.get()),
        )
        self.toast("Generando preview de preprocesamiento…", "info")

        def worker():
            preview = self._pipeline.extractor.get_preprocessed_preview(self._image_path, opts)
            self.after(0, lambda: self._open_preview_window(preview))

        threading.Thread(target=worker, daemon=True).start()

    def _open_preview_window(self, img):
        if not self.winfo_exists():
            return
        if img is None:
            self.toast("No se pudo generar preview", "error")
            return
        win = ctk.CTkToplevel(self)
        win.title("Preview de preprocesamiento")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.grab_set()

        ctk.CTkLabel(
            win, text="Original  |  Máscara limpia",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_SECONDARY,
        ).pack(pady=(12, 4))

        max_w = 900
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

        if _PIL_OK:
            photo = ImageTk.PhotoImage(img)
            lbl = ctk.CTkLabel(win, image=photo, text="")
            lbl.pack(padx=16, pady=8)
            lbl._photo_ref = photo

        ctk.CTkLabel(
            win,
            text="Izquierda: imagen procesada  |  Derecha: máscara binaria (tinta detectada)",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 4))
        ctk.CTkButton(
            win, text="Cerrar", command=win.destroy,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY, width=100,
        ).pack(pady=(0, 12))
        win.geometry(f"{img.width + 32}x{img.height + 120}")

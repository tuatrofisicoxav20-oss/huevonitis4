import logging
import threading
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from core.diagnostics import diagnostics
from core.inkcore.ai.classifier import FallbackGlyphClassifier
from core.inkcore.extractor import ExtractionOptions
from core.inkcore.pipeline import InkCorePipeline
from core.inkcore.renderer import RenderOptions
from core.inkcore.reporter import InkCoreReporter
from core.models import GlyphEntry
from ui import theme
from ui.views.base_view import BaseView

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False


class InkCoreView(BaseView):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._pipeline: InkCorePipeline = app.inkcore
        self._classifier = FallbackGlyphClassifier()
        self._reporter = InkCoreReporter()
        self._extracted: list[GlyphEntry] = []
        self._preview_photo = None
        self._image_path: str | None = None
        self._glyph_photos: list = []
        self._review_photos: list = []
        self._original_img: Image.Image | None = None
        self._adj_collapsed = False
        self._review_checkboxes: list = []
        self._review_check_vars: list = []
        # Cache de thumbnails: (path, w, h) -> PhotoImage (instance-level)
        self._thumb_cache: dict[tuple, ImageTk.PhotoImage] = {}
        # Lista de PhotoImages para páginas del escritor (evita GC)
        self._writer_page_photos: list = []
        self._build()

    def _get_thumb(self, path: str, w: int, h: int) -> "ImageTk.PhotoImage | None":
        """Carga y cachea thumbnail de un glifo PNG. Retorna PhotoImage o None."""
        key = (path, w, h)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        if not PIL_OK or not Path(path).exists():
            return None
        try:
            img = Image.open(path).convert("RGBA")
            bg = Image.new("RGBA", img.size, (22, 32, 50, 255))
            bg.paste(img, mask=img.split()[3])
            thumb = bg.convert("RGB")
            thumb.thumbnail((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self._thumb_cache[key] = photo
            # Limitar cache a 300 entradas (FIFO)
            if len(self._thumb_cache) > 300:
                oldest = next(iter(self._thumb_cache))
                del self._thumb_cache[oldest]
            return photo
        except Exception:
            return None

    def _build(self):
        self._tabs = ctk.CTkTabview(
            self,
            fg_color="transparent",
            segmented_button_fg_color=theme.BG_SECONDARY,
            segmented_button_selected_color=theme.ACCENT_ORANGE,
            segmented_button_unselected_color=theme.BG_SECONDARY,
            segmented_button_selected_hover_color=theme.ACCENT_ORANGE_HOVER,
            segmented_button_unselected_hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
        )
        self._tabs.pack(fill="both", expand=True, padx=16, pady=16)
        self._tabs.add("📷 Extractor")
        self._tabs.add("🗂 Banco")
        self._tabs.add("✍️ Escritor")
        self._tabs.add("✅ Revisión")
        self._build_extractor(self._tabs.tab("📷 Extractor"))
        self._build_bank(self._tabs.tab("🗂 Banco"))
        self._build_writer(self._tabs.tab("✍️ Escritor"))
        self._build_review(self._tabs.tab("✅ Revisión"))

    # ── Extractor tab ──────────────────────────────────────────────

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

        # Image preview
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

        # ── Adjustments (collapsible) ──────────────────────────────
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

        # ── Reference text ─────────────────────────────────────────
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

        # Action buttons
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

        # Green progress bar during extraction
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

    # ── Bank tab ───────────────────────────────────────────────────

    def _build_bank(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=10)

        self._bank_summary = ctk.CTkLabel(
            top, text="Cargando banco...",
            font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY,
        )
        self._bank_summary.pack(side="left")

        ctk.CTkButton(
            top, text="🔄  Recargar", width=100, height=30,
            fg_color=theme.BG_TERTIARY, font=theme.FONT_SMALL,
            hover_color=theme.BORDER,
            command=self._refresh_bank,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            top, text="📊 Ver Informe", width=130, height=30,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
            command=self._show_report,
        ).pack(side="right", padx=4)

        filter_row = ctk.CTkFrame(parent, fg_color="transparent")
        filter_row.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(
            filter_row, text="Filtrar:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")

        self._bank_filter_entry = ctk.CTkEntry(
            filter_row, placeholder_text="Carácter...",
            width=80, fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY, border_color=theme.BORDER,
        )
        self._bank_filter_entry.pack(side="left", padx=8)
        self._bank_filter_entry.bind("<Return>", lambda e: self._refresh_bank())

        self._tier_filter = ctk.CTkOptionMenu(
            filter_row,
            values=["Todos", "Gold", "Silver", "Bronze"],
            fg_color=theme.BG_TERTIARY,
            button_color=theme.ACCENT_ORANGE,
            button_hover_color=theme.ACCENT_ORANGE_HOVER,
            text_color=theme.TEXT_PRIMARY,
            width=110,
            command=lambda v: self._refresh_bank(),
        )
        self._tier_filter.pack(side="left")

        self._bank_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._bank_scroll.pack(fill="both", expand=True, padx=8, pady=4)

    # ── Writer tab ─────────────────────────────────────────────────

    def _build_writer(self, parent):
        main = ctk.CTkFrame(parent, fg_color="transparent")
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=50)
        main.columnconfigure(1, weight=50)
        main.rowconfigure(0, weight=1)

        left = self.card_frame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            left, text="Texto a escribir",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(padx=14, pady=(14, 6), anchor="w")

        self._writer_text = ctk.CTkTextbox(
            left, font=theme.FONT_BODY,
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.BORDER, border_width=1,
        )
        self._writer_text.pack(fill="both", expand=True, padx=12, pady=4)

        opts = ctk.CTkFrame(left, fg_color="transparent")
        opts.pack(fill="x", padx=12, pady=6)
        opts.columnconfigure(1, weight=1)

        for row, (label, attr, lo, hi, default) in enumerate([
            ("Tamaño:", "_size_slider", 20, 80, 40),
            ("Jitter:",  "_jitter_slider", 0, 12, 3),
        ]):
            ctk.CTkLabel(
                opts, text=label,
                font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
            ).grid(row=row, column=0, sticky="w")
            s = ctk.CTkSlider(
                opts, from_=lo, to=hi, number_of_steps=hi - lo,
                progress_color=theme.ACCENT_GREEN,
                button_color=theme.ACCENT_GREEN,
                button_hover_color=theme.ACCENT_GREEN_HOVER,
            )
            s.set(default)
            s.grid(row=row, column=1, padx=8, sticky="ew")
            setattr(self, attr, s)

        ctk.CTkLabel(
            opts, text="Estilo:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).grid(row=2, column=0, sticky="w")
        self._style_menu = ctk.CTkOptionMenu(
            opts,
            values=["Limpio", "Escolar", "Universitario", "Relajado"],
            fg_color=theme.BG_TERTIARY,
            button_color=theme.ACCENT_GREEN,
            button_hover_color=theme.ACCENT_GREEN_HOVER,
            text_color=theme.TEXT_PRIMARY,
        )
        self._style_menu.grid(row=2, column=1, padx=8, sticky="ew")

        # Selector de fondo
        bg_frame = ctk.CTkFrame(left, fg_color="transparent")
        bg_frame.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(
            bg_frame, text="Fondo:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")
        self._bg_style_var = ctk.StringVar(value="hoja_blanca")
        for bg_val, bg_label in [
            ("hoja_blanca", "Hoja blanca"),
            ("libreta", "Libreta"),
            ("hoja_cuadricula", "Cuadrícula"),
        ]:
            ctk.CTkRadioButton(
                bg_frame, text=bg_label, variable=self._bg_style_var, value=bg_val,
                font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
                fg_color=theme.ACCENT_GREEN,
                hover_color=theme.ACCENT_GREEN_HOVER,
                border_color=theme.BORDER,
            ).pack(side="left", padx=6)

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=6)

        ctk.CTkButton(
            btn_row, text="👁  Preview",
            command=self._preview_handwriting,
            height=34,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 11, "bold"),
            corner_radius=8,
        ).pack(side="left", padx=(0, 6))

        self.secondary_button(btn_row, "💾 Exportar PNG", self._export_png, 130).pack(side="left")

        right = self.card_frame(main)
        right.grid(row=0, column=1, sticky="nsew")

        preview_header = ctk.CTkFrame(right, fg_color="transparent")
        preview_header.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(
            preview_header, text="Preview",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        self._page_count_label = ctk.CTkLabel(
            preview_header, text="",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._page_count_label.pack(side="right")

        self._writer_preview_scroll = ctk.CTkScrollableFrame(
            right, fg_color=theme.BG_TERTIARY, corner_radius=8,
        )
        self._writer_preview_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._writer_preview_label = ctk.CTkLabel(
            self._writer_preview_scroll,
            text="El resultado aparecerá aquí",
            text_color=theme.TEXT_MUTED,
            font=theme.FONT_BODY,
        )
        self._writer_preview_label.pack(expand=True, pady=40)

    # ── Image loading + live adjustment preview ────────────────────

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
        logger.info(f"Imagen cargada: {path}")
        if PIL_OK:
            try:
                self._original_img = Image.open(path).convert("RGB")
                self._apply_preview()
            except Exception as e:
                logger.warning(f"No se pudo abrir imagen para preview: {e}")
                self._img_preview.configure(text=name)
        else:
            self._img_preview.configure(text=name)

    def _apply_preview(self, *_):
        if not PIL_OK or self._original_img is None:
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
        logger.info(f"_extract: texto de referencia = {ref[:80]!r}")
        if not ref:
            logger.warning("_extract: texto de referencia vacío")
            self._extract_error.configure(
                text="⚠ Escribe el texto de referencia en el cuadro de texto de arriba"
            )
            self.toast("Escribe el texto de referencia", "warning")
            return

        self._extract_error.configure(text="")
        opts = ExtractionOptions(
            remove_lines=self._remove_lines_var.get(),
            brightness=float(self._brightness_slider.get()),
            contrast=float(self._contrast_slider.get()),
            rotation_deg=float(self._rotation_slider.get()),
        )
        logger.info(f"_extract: opts={opts}, iniciando hilo")

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
                logger.info(f"worker: extracción completada — {len(glyphs)} glifos")
            except Exception as exc:
                logger.error(f"worker: error en extracción: {exc}", exc_info=True)
                glyphs = []
            try:
                self.after(0, lambda: self._on_extracted(glyphs))
            except Exception as e:
                logger.error(f"worker: error al programar callback: {e}")

        threading.Thread(target=worker, daemon=True).start()
        logger.info("_extract: hilo iniciado")

    def _on_extracted(self, glyphs: list[GlyphEntry]):
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

        # Quality indicator: Green=Gold avg, Orange=Silver avg, Red=Bronze avg
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
        """Coloured border per tier — green=Gold, orange=Silver, dim=Bronze."""
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

    # ── Bank refresh ───────────────────────────────────────────────

    def _refresh_bank(self):
        """Recarga el banco desde disco y actualiza la UI."""
        self._pipeline.reload_bank()
        self._do_refresh_bank_ui()

    def _do_refresh_bank_ui(self):
        """Actualiza solo la UI del banco sin recargar el JSON desde disco."""
        for w in self._bank_scroll.winfo_children():
            w.destroy()
        self._glyph_photos.clear()

        cov = self._pipeline.bank_coverage()
        missing_str = ""
        if cov["alpha_missing"]:
            m = cov["alpha_missing"]
            missing_str = (
                f"  |  Faltan: {''.join(m[:8])}"
                f"{'…' if len(m) > 8 else ''}"
            )
        self._bank_summary.configure(
            text=(
                f"Total: {cov['total_glyphs']} glifos  |  "
                f"Letras: {cov['alpha_covered']}/27  |  "
                f"Calidad prom: {cov['avg_quality']:.0%}"
                + missing_str
            )
        )

        char_filter = self._bank_filter_entry.get().strip()
        tier_filter = self._tier_filter.get()
        glyphs = self._pipeline.bank.get_all(char_filter=char_filter, tier_filter=tier_filter)

        if not glyphs:
            ctk.CTkLabel(
                self._bank_scroll,
                text="Banco vacío. Ve al Extractor para agregar glifos.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=30)
            return

        cols = 6
        current_row = None
        for i, g in enumerate(glyphs):
            if i % cols == 0:
                current_row = ctk.CTkFrame(self._bank_scroll, fg_color="transparent")
                current_row.pack(fill="x", pady=3)
            tc = self._tier_text_color(g.tier)
            tier_bg = theme.TIER_BG.get(g.tier, theme.CARD_BG)
            cell = ctk.CTkFrame(
                current_row,
                fg_color=tier_bg,
                corner_radius=8,
                width=70, height=82,
                border_width=1,
                border_color=self._tier_border(g.tier),
            )
            cell.pack(side="left", padx=4)
            cell.pack_propagate(False)

            def _bh(c=cell, tb=tier_bg):
                c.bind("<Enter>", lambda e: c.configure(fg_color=theme.CARD_BG_HOVER), add="+")
                c.bind("<Leave>", lambda e: c.configure(fg_color=tb), add="+")
            _bh()

            photo = self._get_thumb(g.image_path, 50, 52)
            if photo is not None:
                ctk.CTkLabel(cell, image=photo, text="").pack(pady=(4, 0))
            else:
                ctk.CTkLabel(
                    cell, text=g.char, font=("Segoe UI", 20),
                    text_color=theme.TEXT_PRIMARY,
                ).pack(pady=8)

            ctk.CTkLabel(
                cell, text=f"{g.char}  {g.tier[0]}",
                font=theme.FONT_SMALL, text_color=tc,
            ).pack()
            ctk.CTkLabel(
                cell, text=f"{g.quality_score:.0%}",
                font=("", 8), text_color=theme.TEXT_MUTED,
            ).pack()

    def _reload_and_refresh_all(self):
        """Recarga el banco una sola vez y actualiza ambas UIs (banco + revisión)."""
        try:
            self._pipeline.reload_bank()
        except Exception as exc:
            logger.error(f"reload_bank failed: {exc}", exc_info=True)
            diagnostics.log_error("reload_and_refresh_all", exc)
        try:
            self._do_refresh_bank_ui()
        except Exception as exc:
            logger.error(f"_do_refresh_bank_ui failed: {exc}", exc_info=True)
        try:
            self._do_refresh_review_ui()
        except Exception as exc:
            logger.error(f"_do_refresh_review_ui failed: {exc}", exc_info=True)

    # ── Writer ─────────────────────────────────────────────────────

    def _preview_handwriting(self):
        text = self._writer_text.get("0.0", "end").strip()
        if not text:
            self.toast("Escribe algo primero", "warning")
            return
        bg_style = self._bg_style_var.get()
        opts = RenderOptions(
            font_size=int(self._size_slider.get()),
            jitter_px=int(self._jitter_slider.get()),
            style=self._style_menu.get(),
            background_style=bg_style,
        )

        def worker():
            try:
                renderer = self._pipeline.renderer
                if renderer is None:
                    self.after(0, lambda: self._show_preview_pages([]))
                    return
                pages = renderer.render_pages(text, opts)
            except Exception as exc:
                logger.error(f"render_pages error: {exc}", exc_info=True)
                pages = []
            self.after(0, lambda: self._show_preview_pages(pages))

        threading.Thread(target=worker, daemon=True).start()
        self.toast("Renderizando...", "info")

    def _show_preview_pages(self, pages: list):
        if not self.winfo_exists():
            return
        for w in self._writer_preview_scroll.winfo_children():
            w.destroy()
        if not pages:
            ctk.CTkLabel(
                self._writer_preview_scroll,
                text="Error al renderizar. ¿El banco tiene glifos?",
                text_color=theme.ACCENT_RED, font=theme.FONT_BODY,
            ).pack(pady=20)
            self._page_count_label.configure(text="")
            return

        n_pages = len(pages)
        self._page_count_label.configure(
            text=f"{n_pages} {'página' if n_pages == 1 else 'páginas'}"
        )

        if PIL_OK:
            max_w = 500
            self._preview_photo = None  # liberar referencia anterior
            self._writer_page_photos = []  # lista para evitar GC
            for i, img in enumerate(pages):
                if img.width > max_w:
                    img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._writer_page_photos.append(photo)
                lbl = ctk.CTkLabel(self._writer_preview_scroll, image=photo, text="")
                lbl.pack(pady=(8 if i == 0 else 4))
                lbl._photo_ref = photo
                # Separador entre páginas
                if i < n_pages - 1:
                    sep = ctk.CTkFrame(
                        self._writer_preview_scroll,
                        height=3, fg_color=theme.BORDER, corner_radius=0,
                    )
                    sep.pack(fill="x", padx=8, pady=4)

        self.toast(f"Preview listo ({n_pages} páginas)", "success")

    def _export_png(self):
        text = self._writer_text.get("0.0", "end").strip()
        if not text:
            self.toast("Escribe algo primero", "warning")
            return
        bg_style = self._bg_style_var.get()
        opts = RenderOptions(
            font_size=int(self._size_slider.get()),
            jitter_px=int(self._jitter_slider.get()),
            style=self._style_menu.get(),
            background_style=bg_style,
        )
        renderer = self._pipeline.renderer
        if renderer is None:
            self.toast("El banco no está listo", "error")
            return
        self.toast("Renderizando…", "info")

        def _render():
            try:
                pages = renderer.render_pages(text, opts)
            except Exception as exc:
                logger.error(f"render_pages export error: {exc}", exc_info=True)
                self.after(0, lambda: self.toast("Error al renderizar", "error"))
                return
            self.after(0, lambda: self._export_png_finish(pages))

        threading.Thread(target=_render, daemon=True).start()

    def _export_png_finish(self, pages):
        if not pages:
            self.toast("Error al renderizar", "error")
            return

        if len(pages) == 1:
            path = filedialog.asksaveasfilename(
                defaultextension=".png",
                filetypes=[("PNG", "*.png")],
                title="Exportar página",
            )
            if not path:
                return
            pages[0].save(path)
            self.toast("PNG exportado", "success")
        else:
            # Exportar páginas numeradas o PDF
            from pathlib import Path as _Path
            path = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf"), ("PNG primer página", "*.png")],
                title=f"Exportar {len(pages)} páginas",
            )
            if not path:
                return
            suffix = _Path(path).suffix.lower()
            if suffix == ".pdf":
                try:
                    pages[0].save(
                        path, save_all=True, append_images=pages[1:],
                        resolution=150,
                    )
                    self.toast(f"PDF exportado ({len(pages)} páginas)", "success")
                except Exception as exc:
                    # Fallback: exportar PNGs numerados
                    logger.warning(f"PDF export failed: {exc}; falling back to numbered PNGs")
                    base = str(_Path(path).with_suffix(""))
                    for i, pg in enumerate(pages, 1):
                        pg.save(f"{base}_p{i:02d}.png")
                    self.toast(f"{len(pages)} PNGs exportados", "success")
            else:
                base = str(_Path(path).with_suffix(""))
                for i, pg in enumerate(pages, 1):
                    pg.save(f"{base}_p{i:02d}.png")
                self.toast(f"{len(pages)} PNGs exportados", "success")

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

        if PIL_OK:
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

    # ── Review tab ─────────────────────────────────────────────────

    def _build_review(self, parent):
        # Stats bar (pills)
        self._review_stats_bar = ctk.CTkFrame(parent, fg_color="transparent")
        self._review_stats_bar.pack(fill="x", padx=12, pady=(10, 4))

        # Placeholder labels — populated in _refresh_review
        self._review_pending_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🔴  …  pendientes",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_RED,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_pending_lbl.pack(side="left", padx=4)

        self._review_silver_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🟡  …  Silver",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_YELLOW,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_silver_lbl.pack(side="left", padx=4)

        self._review_gold_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🟢  …  Gold",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_GREEN,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_gold_lbl.pack(side="left", padx=4)

        ctk.CTkButton(
            self._review_stats_bar,
            text="📄 Exportar informe PDF",
            height=28, width=180,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
            command=self._export_report_pdf,
        ).pack(side="right", padx=4)

        # Scrollable review list
        self._review_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._review_scroll.pack(fill="both", expand=True, padx=8, pady=4)

        # Batch action bar
        batch_bar = ctk.CTkFrame(
            parent,
            fg_color=theme.BG_SECONDARY,
            corner_radius=8,
            border_width=1,
            border_color=theme.BORDER,
        )
        batch_bar.pack(fill="x", padx=12, pady=(4, 10))

        ctk.CTkButton(
            batch_bar, text="☑ Seleccionar todos",
            width=160, height=30,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.BORDER,
            font=theme.FONT_SMALL,
            command=self._review_select_all,
        ).pack(side="left", padx=8, pady=6)

        ctk.CTkButton(
            batch_bar, text="✅ Aprobar seleccionados",
            width=180, height=30,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.FONT_SMALL,
            command=lambda: self._review_batch_action("approve"),
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkButton(
            batch_bar, text="❌ Rechazar seleccionados",
            width=180, height=30,
            fg_color=theme.ACCENT_RED,
            hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_SMALL,
            command=lambda: self._review_batch_action("reject"),
        ).pack(side="left", padx=4, pady=6)

    def _refresh_review(self):
        """Recarga el banco desde disco y actualiza la UI de revisión."""
        self._pipeline.reload_bank()
        self._do_refresh_review_ui()

    def _do_refresh_review_ui(self):
        """Actualiza solo la UI de revisión sin recargar el JSON desde disco."""
        t0 = time.perf_counter()
        for w in self._review_scroll.winfo_children():
            w.destroy()
        self._review_photos.clear()
        self._review_checkboxes.clear()
        self._review_check_vars.clear()

        queue = self._pipeline.bank.get_review_queue()
        all_entries = self._pipeline.bank.get_all()
        silver_count = sum(1 for e in all_entries if e.tier == "Silver")
        gold_count = sum(1 for e in all_entries if e.tier == "Gold")

        self._review_pending_lbl.configure(text=f"🔴  {len(queue)}  pendientes")
        self._review_silver_lbl.configure(text=f"🟡  {silver_count}  Silver")
        self._review_gold_lbl.configure(text=f"🟢  {gold_count}  Gold")

        if not queue:
            ctk.CTkLabel(
                self._review_scroll,
                text="Sin glifos pendientes de revisión.\nTodos los glifos son Silver o Gold.",
                font=theme.FONT_BODY,
                text_color=theme.ACCENT_GREEN,
            ).pack(pady=40)
            return

        # Column headers
        header = ctk.CTkFrame(self._review_scroll, fg_color=theme.BG_SECONDARY, corner_radius=6)
        header.pack(fill="x", padx=2, pady=(2, 4))
        for text, w in [("☑", 30), ("Img", 70), ("Letra", 80), ("Calidad", 140),
                         ("Score/Tier", 100), ("Flags", 180), ("Acciones", 200)]:
            ctk.CTkLabel(
                header, text=text, width=w,
                font=("Segoe UI", 9, "bold"),
                text_color=theme.TEXT_SECONDARY,
            ).pack(side="left", padx=4, pady=4)

        for glyph in queue:
            self._build_review_row(glyph)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        diagnostics.log_timing("refresh_review_ui", elapsed_ms)
        diagnostics.log_event("ui", "refresh_review", f"{len(queue)} pendientes")

    def _build_review_row(self, glyph):
        tier_color = theme.TIER_COLORS.get(glyph.tier, "#888")
        row_bg = theme.CARD_BG

        row = ctk.CTkFrame(
            self._review_scroll,
            fg_color=row_bg,
            corner_radius=8,
            border_width=1,
            border_color=theme.BORDER,
        )
        row.pack(fill="x", padx=2, pady=3)

        # Checkbox
        var = ctk.BooleanVar(value=False)
        self._review_check_vars.append(var)
        cb = ctk.CTkCheckBox(
            row, text="", variable=var, width=30,
            checkbox_width=18, checkbox_height=18,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
        )
        cb.pack(side="left", padx=(8, 4), pady=8)
        self._review_checkboxes.append((cb, glyph))

        # Image preview
        img_frame = ctk.CTkFrame(
            row, width=64, height=64,
            fg_color="#000000",
            corner_radius=6,
            border_width=2,
            border_color=tier_color,
        )
        img_frame.pack(side="left", padx=4, pady=8)
        img_frame.pack_propagate(False)

        photo = self._get_thumb(glyph.image_path, 56, 56)
        if photo is not None:
            ctk.CTkLabel(img_frame, image=photo, text="").place(relx=0.5, rely=0.5, anchor="center")
        else:
            ctk.CTkLabel(img_frame, text="?", font=("Segoe UI", 20),
                         text_color=theme.TEXT_MUTED).place(relx=0.5, rely=0.5, anchor="center")

        # Character label + rename button
        char_frame = ctk.CTkFrame(row, fg_color="transparent", width=80)
        char_frame.pack(side="left", padx=4, pady=8)
        char_frame.pack_propagate(False)
        ctk.CTkLabel(
            char_frame,
            text=glyph.char or "?",
            font=("Segoe UI", 22, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack()
        ctk.CTkButton(
            char_frame, text="✏️", width=28, height=22,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=("Segoe UI", 10),
            command=lambda g=glyph: self._open_rename_modal(g),
        ).pack()

        # Quality bar
        q = glyph.quality_score
        if q >= 0.75:
            bar_color = theme.ACCENT_GREEN
        elif q >= 0.50:
            bar_color = theme.ACCENT_ORANGE
        else:
            bar_color = theme.ACCENT_RED

        q_frame = ctk.CTkFrame(row, fg_color="transparent", width=140)
        q_frame.pack(side="left", padx=4, pady=8)
        q_frame.pack_propagate(False)
        bar = ctk.CTkProgressBar(
            q_frame, width=120, height=10,
            fg_color=theme.BG_TERTIARY,
            progress_color=bar_color,
            corner_radius=4,
        )
        bar.set(max(0.0, min(1.0, q)))
        bar.pack(pady=(6, 0))
        ctk.CTkLabel(
            q_frame,
            text=f"{q:.0%}",
            font=("Segoe UI", 9),
            text_color=bar_color,
        ).pack()

        # Score + tier badge
        score_frame = ctk.CTkFrame(row, fg_color="transparent", width=100)
        score_frame.pack(side="left", padx=4, pady=8)
        score_frame.pack_propagate(False)
        ctk.CTkLabel(
            score_frame,
            text=f"{q:.3f}",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        ).pack()
        tier_bg = theme.TIER_BG.get(glyph.tier, theme.CARD_BG)
        ctk.CTkLabel(
            score_frame,
            text=glyph.tier,
            font=("Segoe UI", 9, "bold"),
            text_color=tier_color,
            fg_color=tier_bg,
            corner_radius=8,
            padx=6, pady=2,
        ).pack(pady=2)

        # Flags
        flags_frame = ctk.CTkFrame(row, fg_color="transparent", width=180)
        flags_frame.pack(side="left", padx=4, pady=8)
        flags_frame.pack_propagate(False)
        # Derive flags from quality/tier since GlyphEntry doesn't store them
        flags = []
        if glyph.quality_score < 0.50:
            flags.append("low_quality")
        if glyph.tier == "Bronze":
            flags.append("bronze_tier")
        if glyph.ink_coverage < 0.05:
            flags.append("tinta_escasa")
        for flag in flags[:3]:
            ctk.CTkLabel(
                flags_frame,
                text=flag.replace("_", " "),
                font=("Segoe UI", 8),
                text_color=theme.ACCENT_ORANGE,
                fg_color=theme.BADGE_BG_ORANGE,
                corner_radius=6,
                padx=5, pady=1,
            ).pack(side="top", anchor="w", pady=1)

        # Action buttons
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=8, pady=8)

        ctk.CTkButton(
            btn_frame, text="✅", width=36, height=30,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 14),
            corner_radius=8,
            command=lambda g=glyph: self._review_approve(g),
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            btn_frame, text="❌", width=36, height=30,
            fg_color=theme.ACCENT_RED,
            hover_color=theme.ACCENT_RED_HOVER,
            font=("Segoe UI", 14),
            corner_radius=8,
            command=lambda g=glyph: self._review_reject(g),
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            btn_frame, text="🔄", width=36, height=30,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=("Segoe UI", 14),
            corner_radius=8,
            command=lambda g=glyph: self._open_rename_modal(g),
        ).pack(side="left", padx=2)

    def _review_approve(self, glyph):
        self._pipeline.bank.approve_glyph(glyph, new_tier="Silver")
        self.toast(f"'{glyph.char}' aprobado → Silver", "success")
        self._reload_and_refresh_all()

    def _review_reject(self, glyph):
        self._pipeline.bank.reject_glyph(glyph)
        self.toast(f"'{glyph.char}' eliminado del banco", "warning")
        self._reload_and_refresh_all()

    def _review_select_all(self):
        all_checked = all(v.get() for v in self._review_check_vars)
        for v in self._review_check_vars:
            v.set(not all_checked)

    def _review_batch_action(self, action: str):
        selected = [
            glyph for (cb, glyph), var
            in zip(self._review_checkboxes, self._review_check_vars)
            if var.get()
        ]
        if not selected:
            self.toast("Selecciona al menos un glifo", "warning")
            return
        if action == "approve":
            for g in selected:
                self._pipeline.bank.approve_glyph(g, new_tier="Silver")
            self.toast(f"{len(selected)} glifos aprobados → Silver", "success")
        elif action == "reject":
            for g in selected:
                self._pipeline.bank.reject_glyph(g)
            self.toast(f"{len(selected)} glifos eliminados", "warning")
        self._reload_and_refresh_all()

    def _open_rename_modal(self, glyph):
        win = ctk.CTkToplevel(self)
        win.title("Cambiar carácter")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("360x280")
        win.grab_set()
        win.resizable(False, False)

        ctk.CTkLabel(
            win, text="Cambiar letra del glifo",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 4))

        # Before / after preview row
        preview_row = ctk.CTkFrame(win, fg_color="transparent")
        preview_row.pack(pady=8)

        ctk.CTkLabel(
            preview_row, text=f"Actual: '{glyph.char}'",
            font=("Segoe UI", 14, "bold"), text_color=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=16)

        ctk.CTkLabel(preview_row, text="→",
                     font=("Segoe UI", 16), text_color=theme.TEXT_MUTED).pack(side="left")

        new_char_preview = ctk.CTkLabel(
            preview_row, text="?",
            font=("Segoe UI", 18, "bold"), text_color=theme.ACCENT_ORANGE,
        )
        new_char_preview.pack(side="left", padx=16)

        ctk.CTkLabel(
            win, text="Nuevo carácter:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=24, pady=(4, 0))

        entry = ctk.CTkEntry(
            win, width=200, height=36,
            font=("Segoe UI", 18),
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.ACCENT_BLUE,
            justify="center",
        )
        entry.pack(padx=24, pady=(2, 8))
        entry.focus_set()

        def on_key(*_):
            val = entry.get().strip()
            new_char_preview.configure(text=val[:1] if val else "?")

        entry.bind("<KeyRelease>", on_key)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=8)

        def _save():
            new_char = entry.get().strip()
            if not new_char:
                return
            self._pipeline.bank.rename_glyph(glyph, new_char[:1])
            self.toast(f"'{glyph.char}' renombrado a '{new_char[:1]}'", "success")
            win.destroy()
            self._reload_and_refresh_all()

        ctk.CTkButton(
            btn_row, text="Guardar",
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 11, "bold"),
            height=34, width=110,
            command=_save,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_row, text="Cancelar",
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            height=34, width=90,
            command=win.destroy,
        ).pack(side="left", padx=4)

        entry.bind("<Return>", lambda e: _save())

    def _show_report(self):
        report_data = self._reporter.generate_report(self._pipeline.bank)
        self._reporter.show_modal(self, report_data)

    def _export_report_pdf(self):
        report_data = self._reporter.generate_report(self._pipeline.bank)
        from datetime import datetime as _dt
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            title="Exportar informe PDF",
            initialfile=f"informe_glifos_{_dt.now().strftime('%Y%m%d')}.pdf",
        )
        if not path:
            return
        ok = self._reporter.export_pdf(report_data, path)
        if ok:
            self.toast("Informe PDF exportado", "success")
        else:
            self.toast("Error al exportar PDF (¿reportlab instalado?)", "error")

    def on_show(self):
        self._reload_and_refresh_all()

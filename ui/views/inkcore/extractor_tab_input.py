"""ExtractorTabInputMixin — entrada/preview del tab Extractor.

Separado de extractor_tab.py para mantener cada archivo manejable.
Agrupa lo previo a la extracción y las ventanas de preview:
  • Modo automático OCR-first (toggle + heurísticas + diálogo de confirmación)
  • Carga de imagen y preview con ajustes (brillo/contraste/rotación)
  • Ventana de preview de preprocesamiento (máscara binaria)

La lógica de extracción (extract, on_extracted, etc.) sigue en extractor_tab.py.
"""
import logging
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from core.inkcore.extractor import ExtractionOptions
from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class ExtractorTabInputMixin:
    """Carga de imagen, modo auto y previews; mezclado en InkCoreView."""

    def _on_auto_mode_toggle(self):
        """Modo auto OCR-first: TrOCR/Tesseract leen la imagen y dan el texto guía."""
        auto = bool(self._auto_mode_var.get())
        if auto:
            # text_color_disabled explícito: sin esto, CTkTextbox pinta el texto
            # con un gris por defecto que sobre BG_SECONDARY queda casi negro/invisible.
            self._ref_text.configure(
                state="disabled",
                fg_color=theme.BG_SECONDARY,
                text_color_disabled=theme.TEXT_MUTED,
            )
            self._adj_ref_label.configure(text_color=theme.TEXT_MUTED)
            # Indicar qué motor OCR se usará
            try:
                import transformers  # noqa: F401
                ocr_name = "TrOCR (handwriting)"
                color = theme.ACCENT_GREEN
            except ImportError:
                ocr_name = "Tesseract PSM 6 (texto continuo)"
                color = theme.ACCENT_ORANGE
            self._ref_example_label.configure(
                text=f"Modo automático: OCR leerá la imagen con {ocr_name}.",
                text_color=color,
            )
        else:
            self._ref_text.configure(state="normal", fg_color=theme.BG_TERTIARY)
            self._adj_ref_label.configure(text_color=theme.TEXT_SECONDARY)
            self._ref_example_label.configure(
                text="Ejemplo: hola mundo abcdefg  /  segunda línea: ñoño piña",
                text_color=theme.TEXT_MUTED,
            )

    # ── Modo auto: heurísticas + diálogo de confirmación ──────────

    @staticmethod
    def _looks_suspect(text: str) -> bool:
        """Detecta si el OCR devolvió algo que probablemente sea un error.

        Casos típicos:
          • Texto muy corto (1-2 chars) → probable basura
          • Palabras improbables tipo "humanization" en una imagen del alfabeto
          • Solo 1 "palabra" larga (sin espacios) y > 10 chars: muy raro
        """
        if not text:
            return True
        clean = text.strip()
        if len(clean) < 2:
            return True
        # Una palabra continua muy larga (>15 chars) sin espacios suele ser
        # alucinación del modelo TrOCR (intentando "leer" un grid de letras).
        if " " not in clean and len(clean) > 15:
            return True
        # Si ningún char es alfanumérico → basura
        if not any(c.isalnum() for c in clean):
            return True
        return False

    _QUICK_TEMPLATES = [
        ("a-z", "a b c d e f g h i j k l m n ñ o p q r s t u v w x y z"),
        ("A-Z", "A B C D E F G H I J K L M N Ñ O P Q R S T U V W X Y Z"),
        ("0-9", "0 1 2 3 4 5 6 7 8 9"),
        ("a-z + 0-9", "a b c d e f g h i j k l m n ñ o p q r s t u v w x y z\n0 1 2 3 4 5 6 7 8 9"),
    ]

    def _ask_user_ref_text(self, predicted: str, conf: float) -> str:
        """Modal: muestra el OCR sugerido + plantillas rápidas; usuario edita y confirma."""
        win = ctk.CTkToplevel(self)
        win.title("Confirmar texto de la imagen")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("520x460")
        win.grab_set()

        ctk.CTkLabel(
            win, text="📝 Confirma el texto de tu imagen",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 4))

        if conf > 0:
            color = theme.ACCENT_ORANGE if conf < 0.75 else theme.ACCENT_GREEN
            ctk.CTkLabel(
                win,
                text=f"OCR detectó (confianza {conf:.0%}). Edita si no es correcto:",
                font=theme.FONT_SMALL, text_color=color,
            ).pack(pady=(0, 4))
        else:
            ctk.CTkLabel(
                win, text="OCR no pudo leer la imagen. Escribe el texto manualmente:",
                font=theme.FONT_SMALL, text_color=theme.ACCENT_RED,
            ).pack(pady=(0, 4))

        textbox = ctk.CTkTextbox(
            win, font=theme.FONT_BODY,
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.ACCENT_BLUE, border_width=1,
            height=120,
        )
        textbox.pack(fill="x", padx=20, pady=8)
        if predicted:
            textbox.insert("1.0", predicted)
        textbox.focus_set()

        ctk.CTkLabel(
            win, text="💡 Plantillas rápidas:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=20, pady=(8, 4))

        tpl_frame = ctk.CTkFrame(win, fg_color="transparent")
        tpl_frame.pack(fill="x", padx=20)

        def _fill(template):
            textbox.delete("1.0", "end")
            textbox.insert("1.0", template)
            textbox.focus_set()

        for label, content in self._QUICK_TEMPLATES:
            ctk.CTkButton(
                tpl_frame, text=label, width=88, height=28,
                fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
                font=theme.FONT_SMALL,
                command=lambda c=content: _fill(c),
            ).pack(side="left", padx=4, pady=4)

        result = {"text": None}

        def _confirm():
            result["text"] = textbox.get("1.0", "end").strip()
            win.destroy()

        def _cancel():
            result["text"] = None
            win.destroy()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(12, 16))
        ctk.CTkButton(
            btn_row, text="Cancelar", command=_cancel,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
            width=110, height=36,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="✓ Procesar con este texto", command=_confirm,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 11, "bold"),
            width=240, height=36,
        ).pack(side="right")

        textbox.bind("<Control-Return>", lambda e: _confirm())
        win.wait_window()
        return result["text"] or ""

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
                # Sin este toast, el usuario veía "✓ cargada" pero el preview
                # quedaba en blanco sin saber por qué — ahora se le avisa.
                self.toast(
                    f"Imagen cargada pero no se pudo generar preview: {e}",
                    "warning",
                )
        else:
            self._img_preview.configure(text=name)
            self.toast("PIL no disponible — no se mostrará preview", "warning")

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
        # Deshabilitar el botón mientras corre el thread: sin esto, clicks
        # repetidos lanzan threads concurrentes que abren múltiples ventanas
        # de preview y compiten por los mismos sliders/imagen.
        try:
            self._preview_btn.configure(state="disabled", text="Procesando…")
        except (AttributeError, Exception):
            pass
        self.toast("Generando preview de preprocesamiento…", "info")
        image_path = self._image_path

        def _restore():
            try:
                self._preview_btn.configure(state="normal", text="🔍 Ver preprocesamiento")
            except (AttributeError, Exception):
                pass

        def worker():
            try:
                preview = self._pipeline.extractor.get_preprocessed_preview(image_path, opts)
            except Exception as exc:
                logger.exception("get_preprocessed_preview falló: %s", exc)
                preview = None
            def _done():
                _restore()
                self._open_preview_window(preview)
            try:
                self.after(0, _done)
            except Exception:
                pass

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

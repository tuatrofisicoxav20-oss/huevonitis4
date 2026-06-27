"""Diálogo de revisión OCR (Fase 0.6): foto a la izquierda, texto editable a la
derecha.

El paso HUMANO que hace funcionar el flujo pasar-en-limpio pese a los errores del
OCR. Corre TrOCR sobre la foto, vuelca la transcripción en un editor, resalta las
líneas de baja confianza para que el usuario sepa dónde mirar, y al aceptar
entrega el texto corregido (que alimenta al renderer del escritor).
"""
import contextlib
import logging
import threading

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# Líneas con confianza por debajo de esto se marcan como dudosas para revisar.
_LOW_CONF = 0.55


class OCRReviewDialog(ctk.CTkToplevel):
    """Ventana modal: revisar y corregir la transcripción de una foto."""

    def __init__(self, parent, image_path: str, on_accept, backend_name: str = "trocr"):
        super().__init__(parent)
        logger.info("OCRReviewDialog: abriendo para %s (backend=%s)", image_path, backend_name)
        self.title("Revisar transcripción — foto vs texto")
        self.geometry("1100x720")
        self._image_path = image_path
        self._on_accept = on_accept
        self._backend_name = backend_name
        self._extra_contrast = False
        try:
            self._build()
        except Exception:
            # Los errores de construcción de widgets (customtkinter en Py3.14)
            # suelen ir a stderr; los mandamos al log para poder diagnosticarlos.
            logger.exception("OCRReviewDialog._build falló")
            raise
        # Realización de la ventana como los modales que funcionan en el proyecto:
        # transient + lift, y grab_set DIFERIDO (si se llama antes de que la ventana
        # sea visible, Tk tira "grab failed: window not viewable").
        with contextlib.suppress(Exception):
            self.transient(parent)
        with contextlib.suppress(Exception):
            self.lift()
        self.after(200, self._safe_grab)
        self.after(120, self._run_ocr)

    def _safe_grab(self):
        with contextlib.suppress(Exception):
            self.grab_set()

    def report_callback_exception(self, exc, val, tb):
        """Tkinter manda acá las excepciones de callbacks/after/eventos — por
        default van a stderr. Las logueamos para verlas en app.log."""
        logger.error("OCRReviewDialog callback error", exc_info=(exc, val, tb))

    # ── UI ────────────────────────────────────────────────────────
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Panel izquierdo: la foto original
        left = ctk.CTkScrollableFrame(self, fg_color=theme.BG_TERTIARY, corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        self._photo_label = ctk.CTkLabel(left, text="(cargando foto…)", text_color=theme.TEXT_MUTED)
        self._photo_label.pack(expand=True, pady=20)
        self._show_photo()

        # Panel derecho: el texto transcrito, editable
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self._status = ctk.CTkLabel(
            right, text="Transcribiendo con TrOCR… (la primera vez baja el modelo)",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        )
        self._status.grid(row=0, column=0, sticky="w", pady=(0, 6))

        self._text = ctk.CTkTextbox(
            right, font=theme.FONT_BODY, fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY, border_color=theme.BORDER, border_width=1,
        )
        self._text.grid(row=1, column=0, sticky="nsew")
        # Tag para resaltar líneas dudosas (vía el Text de tkinter por debajo).
        with contextlib.suppress(Exception):
            self._text._textbox.tag_config("low", foreground=theme.ACCENT_YELLOW)

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ctk.CTkButton(
            btns, text="✓ Aceptar y pasar a render", command=self._accept,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.get_font("bold", 11), height=34,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="↻ Re-procesar con más contraste", command=self._reprocess,
            height=34,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="✕ Descartar", command=self.destroy, height=34,
            fg_color=theme.BG_TERTIARY,
        ).pack(side="left")

    def _show_photo(self):
        if not _PIL_OK:
            return
        try:
            with Image.open(self._image_path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((520, 900))
            self._photo_label.configure(
                image=ctk.CTkImage(light_image=im, size=im.size), text="",
            )
        except Exception as exc:
            logger.warning("OCRReview: no se pudo mostrar la foto: %s", exc)

    # ── OCR ───────────────────────────────────────────────────────
    def _run_ocr(self):
        def _ui(fn):
            # El usuario puede cerrar el diálogo ("✕ Descartar") mientras el OCR
            # corre: agendar/tocar widgets ya destruidos lanzaría TclError y
            # mataría el worker en silencio. suppress protege el agendado; el
            # callback vuelve a chequear winfo_exists ya en el hilo de UI.
            with contextlib.suppress(Exception):
                self.after(0, fn)

        def worker():
            try:
                from core.ocr.engine import OCREngine
                eng = OCREngine()
                with contextlib.suppress(Exception):
                    eng.switch_backend(self._backend_name)
                path = self._image_path
                if self._extra_contrast:
                    path = self._make_contrast_copy(path)
                lines = eng.extract_text_with_boxes(path)
                _ui(lambda: self._fill_text(lines))
            except Exception as exc:
                logger.error("OCRReview OCR falló: %s", exc, exc_info=True)
                _ui(lambda exc=exc: self.winfo_exists()
                    and self._status.configure(text=f"Error de OCR: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _make_contrast_copy(path: str) -> str:
        """Copia con más contraste (autocontrast) para reintentar el OCR."""
        if not _PIL_OK:
            return path
        import os
        import tempfile
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("L")
                im = ImageOps.autocontrast(im, cutoff=2)
            out = os.path.join(tempfile.gettempdir(), "ocr_contrast.png")
            im.save(out)
            return out
        except Exception:
            return path

    def _fill_text(self, lines: list):
        if not self.winfo_exists():   # diálogo cerrado mientras corría el OCR
            return
        self._text.delete("0.0", "end")
        if not lines:
            self._status.configure(text="El OCR no devolvió texto. Probá 'más contraste' o corregí a mano.")
            return
        n_low = 0
        for i, d in enumerate(lines):
            txt = d.get("text", "")
            conf = float(d.get("conf", 0.0) or 0.0)
            self._text.insert("end", txt + "\n")
            if conf < _LOW_CONF:
                n_low += 1
                with contextlib.suppress(Exception):  # resaltar la línea dudosa
                    self._text._textbox.tag_add("low", f"{i+1}.0", f"{i+1}.end")
        self._status.configure(
            text=f"{len(lines)} líneas · {n_low} dudosas (en naranja). Corregí y aceptá.",
        )

    # ── acciones ──────────────────────────────────────────────────
    def _reprocess(self):
        self._extra_contrast = True
        self._status.configure(text="Re-procesando con más contraste…")
        self._run_ocr()

    def _accept(self):
        text = self._text.get("0.0", "end").strip()
        try:
            self._on_accept(text)
        finally:
            self.destroy()

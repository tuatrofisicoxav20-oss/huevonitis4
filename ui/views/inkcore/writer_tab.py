"""WriterTabMixin — tab ✍️ Escritor de InkCoreView."""
import contextlib
import logging
import threading
from dataclasses import replace
from tkinter import filedialog

import customtkinter as ctk

from core.inkcore.renderer import RenderOptions
from ui import theme

logger = logging.getLogger(__name__)

# Fase 7 — RENDER_PARAMS "naturales" por defecto del escritor (reset/persistencia).
_WRITER_DEFAULTS = {"font_size": 40, "jitter": 3, "style": "Limpio", "bg": "", "dpi": "150"}

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class WriterTabMixin:
    """Tab del escritor de letra manuscrita; mezclado en InkCoreView."""

    # ── Build ──────────────────────────────────────────────────────

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

        mode_frame = ctk.CTkFrame(left, fg_color="transparent")
        mode_frame.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(
            mode_frame, text="Modo:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")
        # "apuntes" = render lineal (texto/bloques); "mapa" = mapa conceptual
        # (árbol desde texto indentado). Es un modo APARTE: no comparte layout
        # con el render lineal.
        self._writer_mode_var = ctk.StringVar(value="apuntes")
        for mode_val, mode_label in [
            ("apuntes", "📝 Apuntes"),
            ("mapa", "🗺️ Mapa conceptual"),
        ]:
            ctk.CTkRadioButton(
                mode_frame, text=mode_label, variable=self._writer_mode_var, value=mode_val,
                font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
                fg_color=theme.ACCENT_GREEN,
                hover_color=theme.ACCENT_GREEN_HOVER,
                border_color=theme.BORDER,
            ).pack(side="left", padx=6)

        # Fase 7 — DPI de exportación + reset de parámetros a valores naturales.
        ctrl_frame = ctk.CTkFrame(left, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=12, pady=(2, 2))
        ctk.CTkLabel(
            ctrl_frame, text="DPI PDF:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")
        self._dpi_var = ctk.StringVar(value="150")
        ctk.CTkOptionMenu(
            ctrl_frame, values=["150", "300"], variable=self._dpi_var, width=80,
            fg_color=theme.BG_TERTIARY, button_color=theme.ACCENT_GREEN,
            button_hover_color=theme.ACCENT_GREEN_HOVER, text_color=theme.TEXT_PRIMARY,
        ).pack(side="left", padx=8)
        self.secondary_button(
            ctrl_frame, "↺ Valores naturales", self._reset_render_params, 170,
        ).pack(side="left")

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

        self.secondary_button(btn_row, "💾 Exportar PNG", self._export_png, 130).pack(side="left", padx=(0, 6))
        self.primary_button(btn_row, "📄 Exportar PDF con mi letra", self._export_writer_pdf, 220).pack(side="left")

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

        # Fase 7 — restaurar los RENDER_PARAMS persistidos de la sesión anterior.
        self._load_writer_params()

    # ── Logic ──────────────────────────────────────────────────────

    def _writer_params_path(self):
        import config
        return config.DATA_DIR / "writer_params.json"

    def _reset_render_params(self):
        """Fase 7 — volver a los 'valores naturales' por defecto."""
        d = _WRITER_DEFAULTS
        self._size_slider.set(d["font_size"])
        self._jitter_slider.set(d["jitter"])
        with contextlib.suppress(Exception):
            self._style_menu.set(d["style"])
        with contextlib.suppress(Exception):
            self._bg_style_var.set(d["bg"])
        with contextlib.suppress(Exception):
            self._dpi_var.set(d["dpi"])
        self._save_writer_params()
        self.toast("Parámetros restaurados a valores naturales", "info")

    def _save_writer_params(self):
        """Persiste los RENDER_PARAMS del escritor entre sesiones (JSON propio)."""
        import json
        data = {
            "font_size": int(self._size_slider.get()),
            "jitter": int(self._jitter_slider.get()),
            "style": self._style_menu.get(),
            "bg": self._bg_style_var.get(),
            "dpi": self._dpi_var.get(),
        }
        with contextlib.suppress(Exception):
            self._writer_params_path().write_text(json.dumps(data), encoding="utf-8")

    def _load_writer_params(self):
        import json
        p = self._writer_params_path()
        if not p.exists():
            return
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return
        with contextlib.suppress(Exception):
            self._size_slider.set(int(d["font_size"]))
        with contextlib.suppress(Exception):
            self._jitter_slider.set(int(d["jitter"]))
        with contextlib.suppress(Exception):
            self._style_menu.set(d["style"])
        with contextlib.suppress(Exception):
            self._bg_style_var.set(d["bg"])
        with contextlib.suppress(Exception):
            self._dpi_var.set(str(d["dpi"]))

    # NOTA (decisión de diseño v4.2): el OCR de manuscrito se ELIMINÓ del flujo
    # del Escritor — el OCR local da puro ruido. El usuario pega/teclea texto YA
    # limpio (de un digital, o Google Lens/Keep). Huevonitis hace una cosa:
    # convertir texto a la letra del banco. El backend TrOCR y el diálogo de
    # revisión quedan en el repo pero desconectados del flujo principal.

    def _get_render_options(self) -> "RenderOptions":
        return RenderOptions(
            font_size=int(self._size_slider.get()),
            jitter_px=int(self._jitter_slider.get()),
            style=self._style_menu.get(),
            background_style=self._bg_style_var.get(),
        )

    def _render_pages(self, renderer, text: str, options: "RenderOptions") -> list:
        """Renderiza el texto actual a páginas.

        Modo "mapa": el texto se interpreta como jerarquía indentada y se dibuja
        como mapa conceptual a mano (módulo aparte; no comparte layout con el
        render lineal). Modo "apuntes": si llegó un Document estructurado desde
        Estudio y el texto del editor no fue modificado, usa render_document
        (respeta encabezados/listas/párrafos); en cuanto el usuario edita el
        texto, cae a render_pages sobre texto plano.
        """
        if getattr(self, "_writer_mode_var", None) is not None and self._writer_mode_var.get() == "mapa":
            from core.inkcore.concept_map import ConceptMapRenderer
            return ConceptMapRenderer(renderer).render(text, options)

        doc = getattr(self, "_pending_document", None)
        if doc is not None and text == getattr(self, "_pending_document_text", None):
            try:
                return renderer.render_document(doc, options)
            except Exception as exc:
                logger.warning("render_document falló (%s); uso texto plano", exc)
        return renderer.render_pages(text, options)

    def _iter_pages_for_export(self, renderer, text: str, options: "RenderOptions", page_height: int = 1122):
        """Páginas para exportar a PDF. Texto plano → iterador perezoso (RAM
        constante); mapa/documento → lista (casos acotados). El exportador
        streaming consume cualquiera de los dos."""
        if getattr(self, "_writer_mode_var", None) is not None and self._writer_mode_var.get() == "mapa":
            from core.inkcore.concept_map import ConceptMapRenderer
            return ConceptMapRenderer(renderer).render(text, options, page_height)
        doc = getattr(self, "_pending_document", None)
        if doc is not None and text == getattr(self, "_pending_document_text", None):
            try:
                return renderer.render_document(doc, options, page_height)
            except Exception as exc:
                logger.warning("render_document falló (%s); uso texto plano", exc)
        return renderer.iter_pages(text, options, page_height)

    def _export_writer_pdf(self):
        text = self._writer_text.get("0.0", "end").strip()
        if not text:
            self.toast("Escribe algo primero", "warning")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar PDF con mi letra",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        self._save_writer_params()  # Fase 7 — persistir entre sesiones
        options = self._get_render_options()
        # Fase 5/7 — DPI: 150 (default) o 300 (alta calidad). Escala TODO el render
        # proporcionalmente (font, ancho y alto de página, margen) → el bitmap sale
        # al doble de resolución sin cambiar el layout. Sube RAM y tamaño del PDF.
        dpi = int(self._dpi_var.get()) if getattr(self, "_dpi_var", None) else 150
        scale = dpi / 150.0
        page_height = int(1122 * scale)
        if scale != 1.0:
            options = replace(
                options,
                font_size=int(options.font_size * scale),
                page_width=int(options.page_width * scale),
                page_margin=int(options.page_margin * scale),
            )

        def worker():
            try:
                renderer = self._pipeline.renderer
                if renderer is None:
                    self.after(0, lambda: self.toast("El banco está vacío — extrae glifos primero", "warning"))
                    return
                # Streaming: para texto plano usa iter_pages (genera y libera página
                # por página → RAM constante en 36+ hojas). Mapa/Documento siguen
                # devolviendo lista, que el exportador también consume.
                pages = self._iter_pages_for_export(renderer, text, options, page_height)
                from core.export.pdf_exporter import export_pages_streaming

                def _progress(n, total):
                    # Barra de progreso real: el render de 36+ hojas tarda y el
                    # usuario debe ver que avanza. Actualiza desde el hilo de UI.
                    self.after(0, lambda n=n: self._page_count_label.configure(text=f"Exportando… pág {n}"))

                ok = export_pages_streaming(pages, path, page_size="letter", progress_cb=_progress)
                self.after(0, lambda: self._page_count_label.configure(text=""))
                msg = "PDF exportado" if ok else "Error al exportar PDF (¿reportlab instalado?)"
                kind = "success" if ok else "error"
                self.after(0, lambda: self.toast(msg, kind))
            except Exception as exc:
                logger.error("export_writer_pdf: %s", exc, exc_info=True)
                self.after(0, lambda exc=exc: self.toast(f"Error: {exc}", "error"))

        threading.Thread(target=worker, daemon=True).start()
        self.toast("Generando PDF...", "info")

    def _preview_handwriting(self):
        text = self._writer_text.get("0.0", "end").strip()
        if not text:
            self.toast("Escribe algo primero", "warning")
            return
        opts = self._get_render_options()

        def worker():
            try:
                renderer = self._pipeline.renderer
                if renderer is None:
                    self.after(0, lambda: self._show_preview_pages([]))
                    return
                pages = self._render_pages(renderer, text, opts)
            except Exception as exc:
                logger.error("render_pages error: %s", exc, exc_info=True)
                pages = []
            # Fase 6.5 — avisar qué caracteres faltan en el banco (los que salieron
            # marcados en rojo en la preview), para que el usuario sepa qué capturar.
            missing = sorted(getattr(renderer, "last_missing_chars", lambda: set())()) if renderer else []
            self.after(0, lambda: self._show_preview_pages(pages))
            if missing:
                faltan = " ".join(missing)
                self.after(0, lambda f=faltan: self.toast(f"Faltan en el banco (en rojo): {f}", "warning"))

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

        if _PIL_OK:
            max_w = 500
            self._preview_photo = None
            self._writer_page_photos = []
            for i, img in enumerate(pages):
                if img.width > max_w:
                    img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._writer_page_photos.append(photo)
                lbl = ctk.CTkLabel(self._writer_preview_scroll, image=photo, text="")
                lbl.pack(pady=(8 if i == 0 else 4))
                lbl._photo_ref = photo
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
                pages = self._render_pages(renderer, text, opts)
            except Exception as exc:
                logger.error("render_pages export error: %s", exc, exc_info=True)
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
                    logger.warning("PDF export failed: %s; falling back to numbered PNGs", exc)
                    base = str(_Path(path).with_suffix(""))
                    for i, pg in enumerate(pages, 1):
                        pg.save(f"{base}_p{i:02d}.png")
                    self.toast(f"{len(pages)} PNGs exportados", "success")
            else:
                base = str(_Path(path).with_suffix(""))
                for i, pg in enumerate(pages, 1):
                    pg.save(f"{base}_p{i:02d}.png")
                self.toast(f"{len(pages)} PNGs exportados", "success")

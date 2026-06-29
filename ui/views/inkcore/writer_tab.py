"""WriterTabMixin — tab ✍️ Escritor de InkCoreView."""
import contextlib
import logging
import threading
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

from core.inkcore.renderer import RenderOptions
from ui import icons, theme
from ui.views.inkcore.writer_preview import WriterPreviewMixin

logger = logging.getLogger(__name__)

# Fase 7 — RENDER_PARAMS "naturales" por defecto del escritor (reset/persistencia).
# line_mm = separación REAL entre renglones de la hoja de carpeta (calibrable
# en 6-9 mm: no todas las marcas son iguales). El tamaño de letra se deriva de
# este valor — anclado al papel físico, ya no hay slider de "Tamaño" suelto.
_WRITER_DEFAULTS = {"line_mm": 7.5, "jitter": 3, "style": "Limpio", "bg": "", "dpi": "150"}



class WriterTabMixin(WriterPreviewMixin):
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

        # "Renglón (mm)" = separación física entre renglones de la hoja de
        # carpeta del usuario (pasos de 0.1 mm para calibrar la marca exacta).
        # El tamaño de letra se deriva de este valor en el renderer.
        for row, (label, attr, lo, hi, steps, default) in enumerate([
            ("Renglón (mm):", "_line_mm_slider", 6.0, 9.0, 30, 7.5),
            ("Jitter:",  "_jitter_slider", 0, 12, 12, 3),
        ]):
            ctk.CTkLabel(
                opts, text=label,
                font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
            ).grid(row=row, column=0, sticky="w")
            s = ctk.CTkSlider(
                opts, from_=lo, to=hi, number_of_steps=steps,
                progress_color=theme.ACCENT_GREEN,
                button_color=theme.ACCENT_GREEN,
                button_hover_color=theme.ACCENT_GREEN_HOVER,
            )
            s.set(default)
            s.grid(row=row, column=1, padx=8, sticky="ew")
            setattr(self, attr, s)

        # Valor numérico del renglón visible junto al slider, para calibrar
        # midiendo la hoja real con regla.
        self._line_mm_value = ctk.CTkLabel(
            opts, text="7.5", width=34,
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        )
        self._line_mm_value.grid(row=0, column=2, sticky="e")
        self._line_mm_slider.configure(
            command=lambda v: self._line_mm_value.configure(text=f"{float(v):.1f}")
        )

        ctk.CTkLabel(
            opts, text="Estilo:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).grid(row=2, column=0, sticky="w")
        self._style_menu = ctk.CTkOptionMenu(
            opts,
            values=["Limpio", "Bolígrafo", "Escolar", "Universitario", "Relajado"],
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
        # "apuntes" = render lineal (texto/bloques); "mapa" = mapa conceptual a
        # mano; "diagrama" = primitivas desde el DSL de texto. Es un DESPLEGABLE
        # (no radios en fila) para que el 3er modo nunca se corte si la ventana es
        # angosta. _writer_mode_var guarda el valor interno (lo lee el resto).
        self._writer_mode_var = ctk.StringVar(value="apuntes")
        self._mode_labels = {"📝 Apuntes": "apuntes", "🗺️ Mapa": "mapa", "🔷 Diagrama": "diagrama"}

        def _on_mode_menu(label):
            self._writer_mode_var.set(self._mode_labels.get(label, "apuntes"))
            self._on_writer_mode_change()

        self._mode_menu = ctk.CTkOptionMenu(
            mode_frame, values=list(self._mode_labels.keys()), command=_on_mode_menu,
            width=180, fg_color=theme.BG_TERTIARY, button_color=theme.ACCENT_GREEN,
            button_hover_color=theme.ACCENT_GREEN_HOVER, text_color=theme.TEXT_PRIMARY,
        )
        self._mode_menu.set("📝 Apuntes")
        self._mode_menu.pack(side="left", padx=8)

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
        btn_reset = self.secondary_button(
            ctrl_frame, "Valores naturales", self._reset_render_params, 170,
        )
        btn_reset.configure(image=icons.get_icon("undo", 13), compound="left")
        btn_reset.pack(side="left")

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=6)

        ctk.CTkButton(
            btn_row, text="Preview",
            image=icons.get_icon("eye", 15, theme.ACCENT_TEXT_ON), compound="left",
            command=self._preview_handwriting,
            height=34,
            fg_color=theme.ACCENT_PRIMARY,
            hover_color=theme.ACCENT_PRIMARY_HOVER,
            text_color=theme.ACCENT_TEXT_ON,
            font=theme.get_font("bold", 11),
            corner_radius=theme.RADIUS["m"],
        ).pack(side="left", padx=(0, 6))

        btn_png = self.secondary_button(btn_row, "Exportar PNG", self._export_png, 130)
        btn_png.configure(image=icons.get_icon("image", 14), compound="left")
        btn_png.pack(side="left", padx=(0, 6))
        btn_photo = self.secondary_button(btn_row, "Foto de tarea", self._export_photo, 140)
        btn_photo.configure(image=icons.get_icon("camera", 14), compound="left")
        btn_photo.pack(side="left", padx=(0, 6))
        btn_pdf = self.primary_button(btn_row, "Exportar PDF con mi letra", self._export_writer_pdf, 220)
        btn_pdf.configure(image=icons.get_icon("export", 14, theme.ACCENT_TEXT_ON), compound="left")
        btn_pdf.pack(side="left")

        # Fila propia para "PDF → mi letra" (importar un PDF y re-renderizarlo
        # con la letra del usuario). En su propio row para que NUNCA se corte.
        pdf2hw_row = ctk.CTkFrame(left, fg_color="transparent")
        pdf2hw_row.pack(fill="x", padx=12, pady=(0, 6))
        btn_pdf2hw = self.primary_button(
            pdf2hw_row, "📄 Convertir un PDF a mi letra", self._export_pdf_from_pdf, 280)
        btn_pdf2hw.configure(image=icons.get_icon("export", 14, theme.ACCENT_TEXT_ON),
                             compound="left")
        btn_pdf2hw.pack(side="left")

        right = self.card_frame(main)
        right.grid(row=0, column=1, sticky="nsew")
        # U5: panel de preview paginado con zoom/en vivo (WriterPreviewMixin)
        self._build_writer_preview(right)

        # Fase 7 — restaurar los RENDER_PARAMS persistidos de la sesión anterior.
        self._load_writer_params()
        logger.info("Escritor construido: modos Apuntes/Mapa/Diagrama, DPI %s",
                    getattr(self, "_dpi_var", None) and self._dpi_var.get())

    # ── Logic ──────────────────────────────────────────────────────

    def _writer_params_path(self):
        import config
        return config.DATA_DIR / "writer_params.json"

    def _reset_render_params(self):
        """Fase 7 — volver a los 'valores naturales' por defecto."""
        d = _WRITER_DEFAULTS
        self._line_mm_slider.set(d["line_mm"])
        with contextlib.suppress(Exception):
            self._line_mm_value.configure(text=f"{d['line_mm']:.1f}")
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
            "line_mm": round(float(self._line_mm_slider.get()), 1),
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
        # JSONs viejos traen "font_size" en vez de "line_mm": se ignoran en
        # silencio y el slider queda en el default físico (7.5 mm).
        with contextlib.suppress(Exception):
            self._line_mm_slider.set(float(d["line_mm"]))
            self._line_mm_value.configure(text=f"{float(d['line_mm']):.1f}")
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

    _DIAGRAM_EXAMPLE = (
        "# Modo Diagrama: una primitiva por línea. Coordenadas en píxeles.\n"
        "box 120,120 380,210 entrada\n"
        "arrow 380,165 520,165\n"
        "box 520,120 820,210 proceso\n"
        "arrow 670,210 670,330\n"
        "circle 670,400 70 fin\n"
        "text 150,300 una nota a mano"
    )

    def _on_writer_mode_change(self):
        """Al pasar a modo Diagrama, si el editor está vacío, deja un ejemplo del
        DSL para que el usuario sepa la sintaxis (Fase 6 — primitivas en la UI)."""
        with contextlib.suppress(Exception):
            if self._writer_mode_var.get() == "diagrama" and not self._writer_text.get("0.0", "end").strip():
                self._writer_text.insert("0.0", self._DIAGRAM_EXAMPLE)

    def _get_render_options(self, dpi: "int | None" = None) -> "RenderOptions":
        """Opciones ancladas al papel físico (carta). El tamaño de letra se
        deriva de line_spacing_mm en el renderer; con dpi != 150 TODO el render
        escala consistente porque las medidas base están en mm.

        R4: si el perfil tiene calibration.json (tools/calibrate_profile.py
        sobre una página real del usuario), las varianzas calibradas entran
        por default — los sliders de la UI siguen mandando encima.
        """
        from core.inkcore.renderer import RENDER_DPI
        dpi = int(dpi or RENDER_DPI)
        scale = dpi / RENDER_DPI
        kwargs = dict(
            render_dpi=dpi,
            line_spacing_mm=round(float(self._line_mm_slider.get()), 1),
            jitter_px=round(self._jitter_slider.get() * scale),
            style=self._style_menu.get(),
            background_style=self._bg_style_var.get(),
        )
        profile_dir = self._calibration_profile_dir()
        if profile_dir is not None:
            opts = RenderOptions.from_calibration(profile_dir, **kwargs)
            if not getattr(self, "_calib_toast_shown", False):
                self._calib_toast_shown = True
                self.toast("🎯 calibrado con tu letra", "success")
            return opts
        return RenderOptions(**kwargs)

    def _calibration_profile_dir(self):
        """Carpeta del perfil activo SI tiene calibration.json; si no, None."""
        try:
            renderer = self._pipeline.renderer
            bank_dir = renderer.bank.bank_dir if renderer else None
            if bank_dir is not None and (bank_dir / "calibration.json").exists():
                return bank_dir
        except Exception:
            pass
        return None

    def _render_pages(self, renderer, text: str, options: "RenderOptions") -> list:
        """Renderiza el texto actual a páginas.

        Modo "mapa": el texto se interpreta como jerarquía indentada y se dibuja
        como mapa conceptual a mano (módulo aparte; no comparte layout con el
        render lineal). Modo "apuntes": si llegó un Document estructurado desde
        Estudio y el texto del editor no fue modificado, usa render_document
        (respeta encabezados/listas/párrafos); en cuanto el usuario edita el
        texto, cae a render_pages sobre texto plano.
        """
        mode = self._writer_mode_var.get() if getattr(self, "_writer_mode_var", None) is not None else "apuntes"
        if mode == "mapa":
            from core.inkcore.concept_map import ConceptMapRenderer
            return ConceptMapRenderer(renderer).render(text, options)
        if mode == "diagrama":
            from core.inkcore.diagram_dsl import DiagramRenderer
            return DiagramRenderer(renderer).render(text, options)

        doc = getattr(self, "_pending_document", None)
        if doc is not None and text == getattr(self, "_pending_document_text", None):
            try:
                return renderer.render_document(doc, options)
            except Exception as exc:
                logger.warning("render_document falló (%s); uso texto plano", exc)
        # Capa de layout estructurado (apuntes): SÓLO si el texto trae marcas
        # (#, viñeta, N:). Prosa sin marcas → render_pages plano IDÉNTICO a hoy.
        from core.inkcore.writer_structure import (
            WriterStructureRenderer,
            detect_structure,
        )
        if detect_structure(text):
            try:
                return WriterStructureRenderer(renderer).render(text, options)
            except Exception as exc:
                logger.warning("render estructurado falló (%s); uso texto plano", exc)
        return renderer.render_pages(text, options)

    def _iter_pages_for_export(self, renderer, text: str, options: "RenderOptions", page_height: "int | None" = None):
        """Páginas para exportar a PDF. Texto plano → iterador perezoso (RAM
        constante); mapa/documento → lista (casos acotados). El exportador
        streaming consume cualquiera de los dos."""
        mode = self._writer_mode_var.get() if getattr(self, "_writer_mode_var", None) is not None else "apuntes"
        if mode == "mapa":
            from core.inkcore.concept_map import ConceptMapRenderer
            return ConceptMapRenderer(renderer).render(text, options, page_height)
        if mode == "diagrama":
            from core.inkcore.diagram_dsl import DiagramRenderer
            return DiagramRenderer(renderer).render(text, options, page_height)
        doc = getattr(self, "_pending_document", None)
        if doc is not None and text == getattr(self, "_pending_document_text", None):
            try:
                return renderer.render_document(doc, options, page_height)
            except Exception as exc:
                logger.warning("render_document falló (%s); uso texto plano", exc)
        # Apuntes estructurados → lista (sin streaming, como render_document);
        # texto plano conserva iter_pages perezoso. SÓLO con marcas presentes.
        from core.inkcore.writer_structure import (
            WriterStructureRenderer,
            detect_structure,
        )
        if detect_structure(text):
            try:
                return WriterStructureRenderer(renderer).render(text, options, page_height)
            except Exception as exc:
                logger.warning("render estructurado falló (%s); uso texto plano", exc)
        return renderer.iter_pages(text, options, page_height)

    def _warn_missing_chars(self, text: str) -> None:
        """R3/H8 — advertencia visible ANTES de exportar: los caracteres sin
        glifo ya NO caen a fuente de sistema (delación instantánea), se omiten
        del render. Acá el usuario se entera de qué capturar antes de entregar
        un PDF con huecos."""
        try:
            renderer = self._pipeline.renderer
            if renderer is None:
                return
            # Apuntes estructurados: chequear cobertura sobre el texto que SÍ se
            # pinta (sin las marcas #/* que el parser descarta), para no avisar
            # de glifos "faltantes" que en realidad nunca se renderizan.
            from core.inkcore.writer_structure import render_text_for_coverage
            rep = renderer.coverage_report(render_text_for_coverage(text))
        except Exception:
            return
        if rep.get("missing"):
            self.toast("⚠ Sin glifo (se OMITEN): " + " ".join(rep["missing"]),
                       "warning")
        if rep.get("case_downgraded"):
            self.toast("Mayúsculas usando su minúscula: "
                       + " ".join(rep["case_downgraded"]), "info")

    def _export_dir(self) -> Path:
        """Carpeta fija de exportación (Wayland-safe: sin diálogo de guardado).

        En Hyprland/Wayland los filedialog de tkinter no se renderizan, así
        que guardamos directo a ~/Documentos/huevonitis_exports/. Si la
        carpeta "Documentos" no existe (sistema en otro idioma o layout
        distinto), caemos a ~/huevonitis_exports/ para no tronar el export.
        """
        docs = Path.home() / "Documentos"
        base = docs if docs.is_dir() else Path.home()
        out = base / "huevonitis_exports"
        out.mkdir(parents=True, exist_ok=True)
        return out

    def _export_path(self, ext: str) -> str:
        """Ruta destino directa con timestamp: apunte_YYYYMMDD_HHMMSS.<ext>."""
        ext = ext.lstrip(".")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(self._export_dir() / f"apunte_{stamp}.{ext}")

    def _announce_saved(self, path):
        """Mostrar al usuario la ruta exacta donde quedó el archivo (UI).

        Llamar SIEMPRE desde el hilo de UI (los exports en worker thread
        deben envolver esta llamada en self.after()).
        """
        p = Path(path)

        def _open_folder():
            import subprocess
            with contextlib.suppress(Exception):
                subprocess.Popen(["xdg-open", str(p.parent)])

        with contextlib.suppress(Exception):
            self._page_count_label.configure(text=f"Guardado: {p}")
        self.toast(f"✓ Guardado en: {p}", "success",
                   action=("Abrir carpeta", _open_folder))

    def _import_dir(self) -> Path:
        """Carpeta fija de entrada para 'PDF → mi letra' (Wayland-safe: sin
        diálogo de selección). El usuario deja su PDF acá."""
        docs = Path.home() / "Documentos"
        base = docs if docs.is_dir() else Path.home()
        out = base / "huevonitis_import"
        out.mkdir(parents=True, exist_ok=True)
        return out

    def _export_pdf_from_pdf(self):
        """Toma el PDF más reciente de ~/Documentos/huevonitis_import/, le
        extrae el texto y lo re-renderiza con la letra del usuario a un PDF
        nuevo. Sin diálogos (Wayland) y con errores visibles en la UI."""
        try:
            import_dir = self._import_dir()
            pdfs = sorted(import_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
        except Exception as exc:
            logger.error("pdf2hw import_dir: %s", exc, exc_info=True)
            self.toast(f"No se pudo abrir la carpeta de entrada: {exc}", "error")
            return
        if not pdfs:
            self.toast(f"Dejá tu PDF en: {import_dir}", "warning",
                       action=("Abrir carpeta", lambda d=import_dir: self._open_dir(d)))
            return
        src = pdfs[-1]
        renderer = self._pipeline.renderer
        if renderer is None:
            self.toast("El banco está vacío — capturá tu letra primero", "warning")
            return
        try:
            options = self._get_render_options()
            options.style = "Bolígrafo"  # convertir PDF → letra de bolígrafo
        except Exception as exc:
            logger.error("pdf2hw options: %s", exc, exc_info=True)
            self.toast(f"No se pudo preparar la exportación: {exc}", "error")
            return
        out_path = self._export_path("pdf")

        def worker():
            try:
                from core.export.pdf_to_handwriting import convert_pdf_to_handwriting

                def _progress(frac, msg):
                    self.after(0, lambda m=msg: self._page_count_label.configure(text=m))

                res = convert_pdf_to_handwriting(
                    src, renderer, options, out_path, progress_cb=_progress)
                self.after(0, lambda: self._page_count_label.configure(text=""))
                self.after(0, lambda: self._announce_saved(res["out_path"]))
                missing = res.get("missing") or []
                if missing:
                    self.after(0, lambda f=" ".join(missing): self.toast(
                        f"⚠ Sin glifo (se OMITEN): {f}", "warning"))
            except Exception as exc:
                logger.error("pdf2hw worker: %s", exc, exc_info=True)
                self.after(0, lambda: self._page_count_label.configure(text=""))
                self.after(0, lambda exc=exc: self.toast(f"Error: {exc}", "error"))

        threading.Thread(target=worker, daemon=True).start()
        self.toast(f"Convirtiendo {src.name} a tu letra…", "info")

    def _open_dir(self, d):
        import subprocess
        with contextlib.suppress(Exception):
            subprocess.Popen(["xdg-open", str(d)])

    def _export_writer_pdf(self):
        text = self._writer_text.get("0.0", "end").strip()
        if not text:
            self.toast("Escribe algo primero", "warning")
            return
        # Prelude síncrono: corre en el callback del botón. Sin este try/except
        # cualquier excepción aquí (ruta, params, opciones de render) se va al
        # report_callback_exception default de Tk → stderr, que con
        # Terminal=false es INVISIBLE y no llega a app.log: el usuario ve "nada
        # en absoluto" al hacer click. Lo atrapamos y avisamos en la UI (req #5).
        try:
            self._warn_missing_chars(text)
            path = self._export_path("pdf")
            self._save_writer_params()  # Fase 7 — persistir entre sesiones
            # Fase 5/7 — DPI: 150 (default) o 300 (alta calidad). Como el layout
            # está en mm, basta construir las opciones con el DPI elegido: el
            # bitmap sale a más resolución con EXACTAMENTE el mismo layout físico.
            dpi = int(self._dpi_var.get()) if getattr(self, "_dpi_var", None) else 150
            options = self._get_render_options(dpi)
            page_height = options.page_height_px
        except Exception as exc:
            logger.error("export_writer_pdf prelude: %s", exc, exc_info=True)
            self.toast(f"No se pudo preparar la exportación: {exc}", "error")
            return

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
                if ok:
                    # worker thread → marshalear al hilo de UI con after()
                    self.after(0, lambda: self._announce_saved(path))
                else:
                    self.after(0, lambda: self.toast("Error al exportar PDF (revisá el log)", "error"))
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
        # R3: en la PREVIEW el placeholder rojo sí ayuda (muestra dónde falta);
        # en export queda apagado y el carácter se omite.
        opts.allow_font_fallback = True

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

    def _export_png(self):
        text = self._writer_text.get("0.0", "end").strip()
        if not text:
            self.toast("Escribe algo primero", "warning")
            return
        try:
            self._warn_missing_chars(text)
            opts = self._get_render_options()
        except Exception as exc:
            logger.error("export_png prelude: %s", exc, exc_info=True)
            self.toast(f"No se pudo preparar la exportación: {exc}", "error")
            return
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
        # Corre en el hilo de UI (lo invoca _export_png vía after), así que
        # toast/_announce_saved se llaman directo. Guardado directo Wayland-safe.
        if not pages:
            self.toast("Error al renderizar", "error")
            return
        try:
            if len(pages) == 1:
                # 1 página → PNG
                path = self._export_path("png")
                pages[0].save(path)
                self._announce_saved(path)
            else:
                # N páginas → un solo PDF (confirmado por el usuario);
                # si el guardado PDF falla, fallback a PNGs numerados.
                path = self._export_path("pdf")
                try:
                    pages[0].save(
                        path, save_all=True, append_images=pages[1:],
                        resolution=150,
                    )
                    self._announce_saved(path)
                except Exception as exc:
                    logger.warning("PDF export failed: %s; falling back to numbered PNGs", exc)
                    base = str(Path(path).with_suffix(""))
                    for i, pg in enumerate(pages, 1):
                        pg.save(f"{base}_p{i:02d}.png")
                    self._announce_saved(f"{base}_p01.png")
        except Exception as exc:
            logger.error("export_png_finish: %s", exc, exc_info=True)
            self.toast(f"Error al guardar: {exc}", "error")

    def _export_photo(self):
        """R7 (F4/F2/I4) — export '📷 Foto de tarea': la página se renderiza
        con skew de escaneo y se guarda como JPEG estilo foto de celular
        (iluminación direccional + viñeta + grano + q85 ~3000px)."""
        text = self._writer_text.get("0.0", "end").strip()
        if not text:
            self.toast("Escribe algo primero", "warning")
            return
        try:
            self._warn_missing_chars(text)
            opts = self._get_render_options()
            opts.scan_skew = True  # la hoja fotografiada nunca está alineada
        except Exception as exc:
            logger.error("export_photo prelude: %s", exc, exc_info=True)
            self.toast(f"No se pudo preparar la exportación: {exc}", "error")
            return
        renderer = self._pipeline.renderer
        if renderer is None:
            self.toast("El banco no está listo", "error")
            return
        self.toast("Renderizando foto…", "info")

        def _render():
            try:
                pages = self._render_pages(renderer, text, opts)
            except Exception as exc:
                logger.error("render foto error: %s", exc, exc_info=True)
                self.after(0, lambda: self.toast("Error al renderizar", "error"))
                return
            self.after(0, lambda: self._export_photo_finish(pages))

        threading.Thread(target=_render, daemon=True).start()

    def _export_photo_finish(self, pages):
        if not pages:
            self.toast("Error al renderizar", "error")
            return
        try:
            path = self._export_path("jpg")
            import random as _random

            from core.export.photo_export import export_photo_pages
            seed = getattr(self._get_render_options(), "seed", None)
            rng = _random.Random(seed)
            outs = export_photo_pages(pages, path, rng)
            self._announce_saved(outs[0] if outs else path)
        except Exception as exc:
            logger.error("export foto error: %s", exc, exc_info=True)
            self.toast(f"Error al exportar foto: {exc}", "error")

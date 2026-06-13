"""TemplateTabMixin — tab 🧩 Plantilla (captura por grilla, una letra por casilla).

Soluciona de raíz el problema del extractor de renglón (recortes y etiquetas
corridas con letra ligada): el usuario imprime una plantilla con una casilla
rotulada por letra, la rellena, le saca foto y la app recorta cada casilla
CONOCIDA. Sin segmentación ni clasificación por posición.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ui import icons as _icons
from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class TemplateTabMixin:
    """Tab: generar plantilla → cargar foto rellena → extraer → guardar al banco."""

    def _build_template(self, parent):
        self._tpl_photo_path: str | None = None
        self._tpl_results: list = []
        self._tpl_thumb_photos: list = []
        # Charset/repeats efectivamente usados al GENERAR la última plantilla.
        # Se congelan acá para que "cargar foto" extraiga con la MISMA geometría
        # aunque el usuario cambie los checkboxes después de generar.
        self._tpl_charset: str | None = None
        self._tpl_repeats: int | None = None
        # E5 — reporte por página y reasignación manual de páginas dudosas.
        # `_tpl_page_report`: un dict por página {label, page_path, preset,
        # rotation, n, suspect, reason}. `_tpl_raster_dirs`: temporales de
        # rasterización CONSERVADOS (no se borran al terminar) para poder
        # re-extraer una página suspect con otro preset; se limpian al cargar
        # otra foto o al cerrar la app.
        self._tpl_page_report: list[dict] = []
        self._tpl_raster_dirs: list[str] = []

        main = ctk.CTkFrame(parent, fg_color="transparent")
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=32)
        main.columnconfigure(1, weight=68)
        main.rowconfigure(0, weight=1)

        left = self.card_frame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._build_tpl_left(left)

        right = self.card_frame(main)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._build_tpl_right(right)

    def _build_tpl_left(self, parent):
        ctk.CTkLabel(
            parent, text="🧩  Plantilla de letra",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(padx=14, pady=(14, 4), anchor="w")

        ctk.CTkLabel(
            parent,
            text="1) Elegí cuántas muestras por letra y generá la plantilla.\n"
                 "2) Escribí cada letra en su casilla, centrada, sin tocar los bordes.\n"
                 "3) Sacale una foto derecha y cargala acá.\n"
                 "Cada casilla se recorta sola: sin recortes a la mitad ni letras "
                 "confundidas.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            wraplength=250, justify="left",
        ).pack(padx=14, pady=(0, 8), anchor="w")

        # Conjuntos de caracteres a incluir. El charset combinado se usa TANTO
        # para generar la hoja como para extraer la foto (la geometría depende de
        # cuántas casillas haya), así que ambos pasos comparten la misma elección.
        from core.inkcore.template_sheet import (
            DIGITOS,
            MAYUSCULAS,
            MINUSCULAS,
            PARES_FRECUENTES,
            PUNTUACION,
            VOCALES_ACENTUADAS,
        )
        ctk.CTkLabel(
            parent, text="Conjuntos a incluir:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(padx=14, pady=(2, 2), anchor="w")
        sets_frame = ctk.CTkFrame(parent, fg_color="transparent")
        sets_frame.pack(padx=14, pady=(0, 6), anchor="w", fill="x")
        # (etiqueta, caracteres, marcado por defecto). El orden define el orden
        # canónico del charset combinado.
        self._tpl_set_specs = []
        for label, chars, default in (
            ("minúsculas", MINUSCULAS, True),
            ("MAYÚSCULAS", MAYUSCULAS, False),
            ("dígitos", DIGITOS, False),
            ("puntuación", PUNTUACION, False),
            ("vocales acentuadas", VOCALES_ACENTUADAS, False),
            # R10: pares frecuentes como ligaduras (se escriben JUNTOS en la
            # casilla; el escritor los usa como semi-cursiva).
            ("pares ligados (qu, ll…)", PARES_FRECUENTES, False),
        ):
            var = ctk.BooleanVar(value=default)
            ctk.CTkCheckBox(
                sets_frame, text=label, variable=var, font=theme.FONT_SMALL,
                checkbox_width=18, checkbox_height=18,
            ).pack(anchor="w", pady=1)
            self._tpl_set_specs.append((label, chars, var))

        # Selector de muestras por letra: el MISMO valor sirve para generar la
        # hoja y para extraer la foto (la geometría depende de él). Más muestras
        # = más variación natural en el banco → letra renderizada más creíble.
        self._tpl_repeats_var = ctk.StringVar(value="1")
        ctk.CTkLabel(
            parent, text="Muestras por letra:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(padx=14, pady=(2, 2), anchor="w")
        ctk.CTkSegmentedButton(
            parent, values=["1", "2", "3"], variable=self._tpl_repeats_var,
            font=theme.FONT_SMALL,
        ).pack(padx=14, pady=(0, 8), anchor="w")

        ctk.CTkButton(
            parent, text="Generar plantilla…", height=38,
            image=_icons.get_icon("doc", 15, theme.ACCENT_TEXT_ON), compound="left",
            fg_color=theme.ACCENT_ORANGE, hover_color=theme.ACCENT_ORANGE_HOVER,
            font=theme.get_font("bold", 12), corner_radius=8,
            command=self._tpl_generate,
        ).pack(padx=14, pady=(6, 4), fill="x")

        ctk.CTkButton(
            parent, text="Cargar foto de plantilla", height=38,
            image=_icons.get_icon("camera", 15), compound="left",
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.get_font("bold", 12), corner_radius=8,
            command=self._tpl_load_photo,
        ).pack(padx=14, pady=4, fill="x")

        self._tpl_photo_name = ctk.CTkLabel(
            parent, text="Sin foto cargada",
            font=theme.FONT_SMALL, text_color=theme.ACCENT_RED,
        )
        self._tpl_photo_name.pack(padx=14, pady=(2, 6), anchor="w")

        ctk.CTkButton(
            parent, text="Guardar en banco", height=38,
            image=_icons.get_icon("save", 15), compound="left",
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.get_font("bold", 12), corner_radius=8,
            command=self._tpl_save_to_bank,
        ).pack(padx=14, pady=(6, 4), fill="x")

        self._tpl_status = ctk.CTkLabel(
            parent, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            wraplength=250, justify="left",
        )
        self._tpl_status.pack(padx=14, pady=(4, 10), anchor="w")

    def _build_tpl_right(self, parent):
        ctk.CTkLabel(
            parent, text="🔤 Letras extraídas",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(padx=14, pady=(14, 4), anchor="w")
        # E5 — reporte por página (oculto hasta que haya un PDF multipágina).
        self._tpl_report_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._tpl_report_frame.pack(fill="x", padx=8, pady=(0, 2))
        self._tpl_grid = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._tpl_grid.pack(fill="both", expand=True, padx=8, pady=4)
        self._tpl_empty_lbl = ctk.CTkLabel(
            self._tpl_grid,
            text="Cargá la foto de una plantilla rellena para ver las letras.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._tpl_empty_lbl.pack(pady=20)

    # ── Lógica ───────────────────────────────────────────────────

    def _tpl_charset_from_ui(self) -> str | list[str]:
        """Charset combinado según los checkboxes marcados (en orden canónico).

        R10: si los PARES están marcados, el charset pasa a ser LISTA de
        tokens (cada par ocupa UNA casilla); sin pares sigue siendo str.
        """
        parts = [chars for _label, chars, var in self._tpl_set_specs if var.get()]
        if any(not isinstance(p, str) for p in parts):
            tokens: list[str] = []
            for p in parts:
                tokens.extend(list(p))
            return tokens
        return "".join(parts)

    def _tpl_layout(self, *, use_snapshot: bool = False):
        """Layout actual: charset + muestras por letra.

        Con `use_snapshot=True` usa el charset/repeats congelados al generar la
        última plantilla (si existen), para que la extracción coincida con la
        hoja impresa aunque cambien los checkboxes. Si no hay snapshot, cae a la
        selección viva de la UI.
        """
        from core.inkcore.template_sheet import MINUSCULAS, TemplateLayout
        if use_snapshot and self._tpl_charset:
            charset = self._tpl_charset
            reps = self._tpl_repeats or 1
        else:
            charset = self._tpl_charset_from_ui() or MINUSCULAS
            try:
                reps = int(self._tpl_repeats_var.get())
            except (ValueError, AttributeError):
                reps = 1
        return TemplateLayout(charset=charset, repeats=max(1, reps))

    def _tpl_generate(self):
        layout = self._tpl_layout()
        reps = layout.repeats
        # Congelar lo usado para que "cargar foto" extraiga con la misma grilla.
        self._tpl_charset = layout.charset
        self._tpl_repeats = layout.repeats
        path = filedialog.asksaveasfilename(
            title="Guardar plantilla",
            defaultextension=".pdf",
            initialfile=f"plantilla_letra_x{reps}.pdf" if reps > 1 else "plantilla_letra.pdf",
            filetypes=[("PDF", "*.pdf"), ("PNG", "*.png")],
        )
        if not path:
            return
        try:
            from core.inkcore.template_sheet import save_template_sheet
            out = save_template_sheet(path, layout)
            extra = (f" ({reps} casillas por letra)" if reps > 1 else "")
            self._tpl_status.configure(
                text=f"✓ Plantilla guardada: {Path(out).name}{extra}. "
                     "Imprimila y rellenala.",
                text_color=theme.ACCENT_GREEN,
            )
            self.toast(f"Plantilla guardada: {Path(out).name}", "success")
            # U6: avanza el paso 1 del stepper
            self._template_generated = True
            self._update_profile_count()
        except Exception as exc:
            logger.error("tpl_generate: %s", exc, exc_info=True)
            self.toast(f"No se pudo generar: {exc}", "error")

    def _tpl_load_photo(self):
        path = filedialog.askopenfilename(
            title="Foto o PDF de la plantilla rellena",
            filetypes=[
                ("Plantilla (imágenes o PDF)", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp *.pdf"),
                ("PDF", "*.pdf"),
                ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
            ],
        )
        if not path:
            return
        self._tpl_cleanup_raster_dirs()   # E5: soltar los temporales de la carga previa
        self._tpl_photo_path = path
        self._tpl_photo_name.configure(
            text=f"✓ {Path(path).name}", text_color=theme.ACCENT_GREEN,
        )
        is_pdf = Path(path).suffix.lower() == ".pdf"
        self._tpl_status.configure(
            text="🔎 Rasterizando PDF…" if is_pdf else "🔎 Extrayendo casillas…",
            text_color=theme.ACCENT_ORANGE,
        )
        # Capturar el layout en el hilo de UI (no leer la var Tk desde el worker).
        # Usa el charset/repeats con que se generó la última plantilla.
        layout = self._tpl_layout(use_snapshot=True)

        def _set_status(text, color=theme.ACCENT_ORANGE):
            if self.winfo_exists():
                self.after(0, lambda: self._tpl_status.configure(text=text, text_color=color))

        def worker():
            from core.inkcore.template_extract import (
                _load_template_cnn,
                extract_pdf_pages,
            )
            # Reutiliza el rasterizador de bulk_capture (poppler + cleanup de
            # temporales). Cada página se extrae por casilla con el flujo de
            # plantilla; el orquestador multi-layout (extract_pdf_pages) elige el
            # preset correcto POR PÁGINA — un PDF puede mezclar minúsculas,
            # acentos y dígitos, y aplicar un solo layout envenenaría el banco.
            tmp_tracker: list[str] = []
            no_poppler = False
            page_report: list[dict] = []
            try:
                if is_pdf:
                    from core.inkcore.bulk_capture import _rasterize_pdf
                    pages = _rasterize_pdf(path, dpi=300, tracker=tmp_tracker)
                    if not pages:
                        no_poppler = True
                        page_items = []
                    else:
                        page_items = [(p, f"pág {pnum}") for p, pnum in pages]
                else:
                    page_items = [(path, Path(path).name)]

                # Cargar el CNN una vez (gate + orientación + identificación de
                # layout); reinyectarlo por página evita recargar el modelo 29 veces.
                clf, char_to_label = _load_template_cnn()
                results: list = []
                total = len(page_items)
                for i, (page_path, label) in enumerate(page_items, start=1):
                    if total > 1:
                        _set_status(f"🔎 Procesando {label} ({i}/{total})…")
                    try:
                        meta = extract_pdf_pages(
                            [page_path], layout_hint=layout,
                            clf=clf, char_to_label=char_to_label)[0]
                    except Exception as exc:
                        logger.error("tpl_load página %s: %s", label, exc, exc_info=True)
                        page_report.append({"label": label, "page_path": page_path,
                                            "preset": None, "rotation": -1, "n": 0,
                                            "suspect": True, "reason": f"error: {exc}"})
                        continue
                    # Reporte por página (E5): guarda el veredicto y la ruta para
                    # poder reasignar el preset a mano si la página es dudosa.
                    page_report.append({
                        "label": label, "page_path": page_path,
                        "preset": meta.get("preset"), "rotation": meta.get("rotation", -1),
                        "n": len(meta["results"]), "suspect": meta["suspect"],
                        "reason": meta.get("reason", ""),
                        "results": meta["results"],
                    })
                    # Gate anti-corrupción: una página con mapeo letra↔casilla
                    # dudoso (números/acentos, o layout no identificado) NO entra
                    # al banco hasta que el usuario la reasigne (E5).
                    if meta["suspect"]:
                        logger.warning("tpl_load: %s DUDOSA — %s", label, meta["reason"])
                    else:
                        results.extend(meta["results"])
            except Exception as exc:
                logger.error("tpl_load worker: %s", exc, exc_info=True)
                results = None
            # NO se borran los temporales acá: se conservan en
            # self._tpl_raster_dirs para permitir la reasignación manual de
            # páginas dudosas. Se limpian al cargar otra foto o al cerrar.
            self._tpl_raster_dirs.extend(tmp_tracker)

            def _done():
                if no_poppler:
                    self._tpl_status.configure(
                        text="⚠ No se pudo leer el PDF. Instalá poppler para leer PDFs "
                             "(o cargá las páginas como imágenes).",
                        text_color=theme.ACCENT_RED,
                    )
                    self.toast("Instalá poppler para leer PDFs", "error")
                    return
                self._tpl_page_report = page_report
                suspect = [p for p in page_report if p["suspect"]]
                if not results and not suspect:
                    self._tpl_status.configure(
                        text="⚠ No se detectaron letras (¿foto nítida? ¿buena luz?)",
                        text_color=theme.ACCENT_RED,
                    )
                    self.toast("No se extrajo ninguna letra", "error")
                    return
                self._tpl_results = results
                self._render_tpl_grid(results)
                from core.inkcore.alphabet_coverage import coverage_message
                cov = coverage_message(
                    [c for c, _g, _q in results],
                    alphabet=layout.charset, scope="Plantilla",
                ) if results else ""
                susp = ""
                if suspect:
                    susp = (f"\n⚠ {len(suspect)} pág dudosa(s) — NO se guardarán "
                            "hasta que reasignes el layout abajo.")
                self._tpl_status.configure(
                    text=f"✓ {len(results)} casillas de "
                         f"{len(page_report) - len(suspect)} pág. {cov}{susp}",
                    text_color=theme.ACCENT_GREEN if not suspect else theme.ACCENT_ORANGE,
                )
                self._render_tpl_report(page_report)
                toast_msg = f"{len(results)} letras extraídas"
                if suspect:
                    toast_msg += f" · {len(suspect)} pág dudosa(s)"
                self.toast(toast_msg, "success" if not suspect else "warning")

            if self.winfo_exists():
                self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

    def _render_tpl_grid(self, results):
        for w in self._tpl_grid.winfo_children():
            w.destroy()
        self._tpl_thumb_photos.clear()
        if not _PIL_OK:
            return
        cols = 6
        for i, (ch, glyph, score) in enumerate(results):
            r, c = divmod(i, cols)
            cell = ctk.CTkFrame(self._tpl_grid, fg_color=theme.BG_TERTIARY, corner_radius=6)
            cell.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
            # Glifo blanco sobre tile oscuro para que la tinta se vea.
            tile = Image.new("RGBA", (84, 84), (20, 20, 30, 255))
            g = glyph.copy()
            g.thumbnail((74, 74), Image.LANCZOS)
            tile.paste(g, ((84 - g.width) // 2, (84 - g.height) // 2), g)
            photo = ImageTk.PhotoImage(tile)
            self._tpl_thumb_photos.append(photo)
            ctk.CTkLabel(cell, image=photo, text="").pack(padx=4, pady=(4, 0))
            ctk.CTkLabel(
                cell, text=f"{ch}  ·  {score:.0%}",
                font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
            ).pack(pady=(0, 4))

    # ── E5: reporte por página + reasignación manual ─────────────

    def _tpl_cleanup_raster_dirs(self):
        """Borra los temporales de rasterización conservados (entre cargas)."""
        import shutil
        for d in self._tpl_raster_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self._tpl_raster_dirs = []
        self._tpl_page_report = []

    def _render_tpl_report(self, page_report: list[dict]):
        """Tabla página | layout | rot | extraídas | estado. Las dudosas en
        naranja con un selector para reasignar el preset y re-extraer esa página.

        Sólo se muestra para PDFs multipágina (una sola imagen no necesita
        desglose). El hint de captura aparece siempre que haya extracción, porque
        estas fotos suelen no traer los 4 marcadores en encuadre.
        """
        for w in self._tpl_report_frame.winfo_children():
            w.destroy()
        if not page_report:
            return
        suspect = [p for p in page_report if p["suspect"]]
        # Hint de captura (mejora los lotes futuros: el camino sin fiduciales es
        # el que se usa cuando la foto cortó los cuadros negros de las esquinas).
        ctk.CTkLabel(
            self._tpl_report_frame,
            text="💡 Tip: para más precisión, fotografiá la hoja completa con "
                 "margen y los 4 cuadros negros de las esquinas visibles.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            wraplength=560, justify="left",
        ).pack(anchor="w", padx=6, pady=(2, 4))
        if len(page_report) <= 1 and not suspect:
            return  # una sola imagen sin problemas: sin tabla

        from core.inkcore.template_sheet import TEMPLATE_PRESETS
        preset_options = ["(omitir)", *TEMPLATE_PRESETS.keys()]
        header = ctk.CTkFrame(self._tpl_report_frame, fg_color="transparent")
        header.pack(fill="x", padx=6)
        ctk.CTkLabel(header, text=f"Detalle por página ({len(page_report)}):",
                     font=theme.get_font("bold", 11),
                     text_color=theme.TEXT_SECONDARY).pack(anchor="w")
        # Sólo listamos las páginas dudosas (las OK ya están en la grilla); evita
        # una tabla de 29 filas. Cada dudosa trae su selector de preset.
        for p in suspect:
            row = ctk.CTkFrame(self._tpl_report_frame, fg_color=theme.BG_TERTIARY,
                               corner_radius=6)
            row.pack(fill="x", padx=6, pady=2)
            tentativo = p.get("preset") or "?"
            ctk.CTkLabel(
                row, text=f"⚠ {p['label']} — dudosa (tentativo: {tentativo})",
                font=theme.FONT_SMALL, text_color=theme.ACCENT_ORANGE,
                wraplength=360, justify="left",
            ).pack(side="left", padx=8, pady=4)
            var = ctk.StringVar(value=tentativo if tentativo in preset_options else "(omitir)")
            ctk.CTkOptionMenu(
                row, values=preset_options, variable=var, width=160,
                font=theme.FONT_SMALL,
                command=lambda choice, pg=p: self._tpl_reassign_page(pg, choice),
            ).pack(side="right", padx=8, pady=4)

    def _tpl_reassign_page(self, page: dict, preset_name: str):
        """Re-extrae una página dudosa con el preset elegido a mano y, si pasa el
        gate (o el preset no tiene a-z que validar), suma sus letras al lote.

        El usuario asume la responsabilidad del mapeo al elegir el preset, así
        que para hojas de acentos/dígitos (que el CNN no valida) se aceptan sus
        letras directamente — por eso la elección manual es la red de seguridad
        del gate automático.
        """
        if preset_name == "(omitir)":
            self.toast(f"{page['label']} omitida", "info")
            return
        page_path = page.get("page_path")
        if not page_path or not Path(page_path).exists():
            self.toast("La imagen de esa página ya no está disponible; recargá el PDF",
                       "error")
            return
        self._tpl_status.configure(text=f"🔎 Re-extrayendo {page['label']} como "
                                        f"{preset_name}…", text_color=theme.ACCENT_ORANGE)

        def worker():
            # Extracción FORZADA con el preset elegido: el usuario asume el mapeo,
            # así que se usa extract_from_template_auto (autorrota y extrae con ese
            # layout) en vez del orquestador, que rechazaría acentos/dígitos por
            # no poder validarlos con el CNN.
            from core.inkcore.template_extract import extract_from_template_auto
            from core.inkcore.template_sheet import TEMPLATE_PRESETS
            lay = TEMPLATE_PRESETS.get(preset_name)
            try:
                new = extract_from_template_auto(page_path, lay)
            except Exception as exc:
                logger.error("reassign %s: %s", page["label"], exc, exc_info=True)
                new = None

            def _done():
                if not new:
                    self._tpl_status.configure(
                        text=f"⚠ {page['label']}: {preset_name} no extrajo letras.",
                        text_color=theme.ACCENT_RED)
                    self.toast("Re-extracción sin resultados", "warning")
                    return
                self._tpl_results = list(self._tpl_results) + list(new)
                page["suspect"] = False
                page["preset"] = preset_name
                page["n"] = len(new)
                page["results"] = new
                self._render_tpl_grid(self._tpl_results)
                self._render_tpl_report(self._tpl_page_report)
                self._tpl_status.configure(
                    text=f"✓ {page['label']} → {len(new)} letras como {preset_name}. "
                         f"Total {len(self._tpl_results)}.",
                    text_color=theme.ACCENT_GREEN)
                self.toast(f"{len(new)} letras de {page['label']}", "success")

            if self.winfo_exists():
                self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

    def _tpl_save_to_bank(self):
        if not self._tpl_results:
            self.toast("Primero cargá una foto de plantilla", "warning")
            return
        results = self._tpl_results

        def worker():
            try:
                from core.inkcore.template_extract import save_template_glyphs_to_bank
                stats = save_template_glyphs_to_bank(results, self._pipeline.bank)
            except Exception as exc:
                logger.error("tpl_save worker: %s", exc, exc_info=True)
                stats = None

            def _done():
                if stats is None:
                    self._tpl_status.configure(
                        text="⚠ Guardado falló — revisá el log",
                        text_color=theme.ACCENT_RED,
                    )
                    self.toast("Guardado falló", "error")
                    return
                bank_cov = ""
                try:
                    from core.inkcore.alphabet_coverage import coverage_message
                    bank_chars = [e.char for e in self._pipeline.bank.get_all()]
                    bank_cov = "\n" + coverage_message(bank_chars, scope="Banco")
                except Exception as exc:
                    logger.warning("tpl_save: cobertura no disponible: %s", exc)
                # Desglose completo: guardadas / duplicadas / rechazadas por el
                # gate de captura / páginas dudosas omitidas (no reasignadas).
                omitidas = sum(1 for p in self._tpl_page_report if p.get("suspect"))
                partes = [f"✓ {stats['saved']} guardadas"]
                if stats.get("dupes"):
                    partes.append(f"{stats['dupes']} ya estaban")
                if stats.get("rejected"):
                    partes.append(f"{stats['rejected']} rechazadas por calidad")
                if omitidas:
                    partes.append(f"{omitidas} pág dudosa(s) sin reasignar")
                self._tpl_status.configure(
                    text=" · ".join(partes) + bank_cov,
                    text_color=theme.ACCENT_GREEN,
                )
                self.toast(f"{stats['saved']} letras al banco", "success")
                # Refrescar banco/revisión si la vista lo soporta
                if hasattr(self, "_tabs_dirty"):
                    self._tabs_dirty.update({self._BANK_TAB, self._REVIEW_TAB})

            if self.winfo_exists():
                self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

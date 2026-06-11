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
            parent, text="📄  Generar plantilla…", height=38,
            fg_color=theme.ACCENT_ORANGE, hover_color=theme.ACCENT_ORANGE_HOVER,
            font=theme.get_font("bold", 12), corner_radius=8,
            command=self._tpl_generate,
        ).pack(padx=14, pady=(6, 4), fill="x")

        ctk.CTkButton(
            parent, text="📷  Cargar foto de plantilla", height=38,
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
            parent, text="💾  Guardar en banco", height=38,
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
            from core.inkcore.template_extract import extract_from_template_auto
            # Reutiliza el rasterizador de bulk_capture (poppler + cleanup de
            # temporales). No procesamos con el extractor de renglón: cada página
            # se extrae SIEMPRE por casilla con el flujo de plantilla, autorrotando.
            tmp_tracker: list[str] = []
            no_poppler = False
            try:
                if is_pdf:
                    from core.inkcore.bulk_capture import _rasterize_pdf
                    pages = _rasterize_pdf(path, dpi=300, tracker=tmp_tracker)
                    if not pages:
                        no_poppler = True
                        page_items = []
                    else:
                        page_items = [(p, f"página {pnum}") for p, pnum in pages]
                else:
                    page_items = [(path, Path(path).name)]

                results: list = []
                total = len(page_items)
                for i, (page_path, label) in enumerate(page_items, start=1):
                    if total > 1:
                        _set_status(f"🔎 Procesando {label} ({i}/{total})…")
                    try:
                        page_res = extract_from_template_auto(page_path, layout)
                    except Exception as exc:
                        logger.error("tpl_load página %s: %s", label, exc, exc_info=True)
                        page_res = []
                    results.extend(page_res)
            except Exception as exc:
                logger.error("tpl_load worker: %s", exc, exc_info=True)
                results = None
            finally:
                # Limpiar temporales de rasterización (igual que bulk_capture).
                import shutil
                for d in tmp_tracker:
                    shutil.rmtree(d, ignore_errors=True)

            def _done():
                if no_poppler:
                    self._tpl_status.configure(
                        text="⚠ No se pudo leer el PDF. Instalá poppler para leer PDFs "
                             "(o cargá las páginas como imágenes).",
                        text_color=theme.ACCENT_RED,
                    )
                    self.toast("Instalá poppler para leer PDFs", "error")
                    return
                if not results:
                    self._tpl_status.configure(
                        text="⚠ No se detectaron letras (¿foto nítida? ¿marcadores visibles?)",
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
                )
                self._tpl_status.configure(
                    text=f"✓ {len(results)} casillas. {cov}\nRevisá y guardá en el banco.",
                    text_color=theme.ACCENT_GREEN,
                )
                self.toast(f"{len(results)} letras extraídas", "success")

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
                self._tpl_status.configure(
                    text=f"✓ Guardadas {stats['saved']} en el banco "
                         f"({stats['dupes']} ya estaban).{bank_cov}",
                    text_color=theme.ACCENT_GREEN,
                )
                self.toast(f"{stats['saved']} letras al banco", "success")
                # Refrescar banco/revisión si la vista lo soporta
                if hasattr(self, "_tabs_dirty"):
                    self._tabs_dirty.update({self._BANK_TAB, self._REVIEW_TAB})

            if self.winfo_exists():
                self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

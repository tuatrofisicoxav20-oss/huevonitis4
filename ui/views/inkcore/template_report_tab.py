"""TemplateReportTabMixin — reporte por página (E5) + reasignación manual.

Sub-mixin de TemplateTabMixin (separado para acotar template_tab.py). Aporta la
tabla "detalle por página" que aparece tras cargar un PDF multipágina y el
selector que permite reasignar a mano el preset de una página dudosa y
re-extraerla. Se compone por herencia: ``class TemplateTabMixin(
TemplateReportTabMixin)``, el mismo patrón que ``WriterTabMixin(
WriterPreviewMixin)``. Los métodos se llaman entre sí (y con los de la clase
derivada) vía ``self``, lo cual es válido porque la instancia real es InkCoreView,
que reúne ambos mixins. El estado (_tpl_raster_dirs, _tpl_page_report,
_tpl_results, widgets) lo inicializa _build_template en la clase derivada antes de
que cualquiera de estos métodos sea alcanzable.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)


class TemplateReportTabMixin:
    """Reporte E5 por página + reasignación manual de páginas dudosas."""

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

        from core.inkcore.template_registry import augmented_presets
        preset_options = ["(omitir)", *augmented_presets().keys()]
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
            from core.inkcore.template_registry import augmented_presets
            lay = augmented_presets().get(preset_name)
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

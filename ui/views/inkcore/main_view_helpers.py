"""InkCoreViewHelpersMixin — helpers propios de InkCoreView.

Separado de main_view.py para mantener cada archivo manejable. Agrupa los
helpers que NO pertenecen a ningún tab concreto:
  • cache de thumbnails (_get_thumb)
  • ciclo de vida de la vista (on_show)
  • refresco diferido por tab (_on_tab_change)
  • carga de texto pendiente desde Estudio (_maybe_load_pending_text)

Depende de atributos definidos en InkCoreView.__init__ / _build:
  self._thumb_cache, self._pipeline, self._tabs, self._tabs_dirty,
  self._writer_text, self.app
y de métodos de otros mixins:
  self._reload_and_refresh_all, self._do_refresh_bank_ui,
  self._do_refresh_review_ui, self.toast
"""
import contextlib
import logging
from pathlib import Path

from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False


class InkCoreViewHelpersMixin:
    """Helpers propios de la vista (thumbnails, on_show, tabs, texto pendiente)."""

    # Nombres exactos de los tabs que cuelgan del banco (con emoji).
    _BANK_TAB = "🗂 Banco"
    _REVIEW_TAB = "3 · ✅ Revisión"

    def _get_thumb(self, path: str, w: int, h: int) -> "ImageTk.PhotoImage | None":
        """Carga y cachea thumbnail de un glifo PNG."""
        key = (path, w, h)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        if not PIL_OK or not Path(path).exists():
            return None
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            bg = Image.new("RGBA", img.size, (22, 32, 50, 255))
            bg.paste(img, mask=img.split()[3])
            thumb = bg.convert("RGB")
            thumb.thumbnail((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            self._thumb_cache[key] = photo
            if len(self._thumb_cache) > 300:
                oldest = next(iter(self._thumb_cache))
                del self._thumb_cache[oldest]
            return photo
        except Exception:
            return None

    def on_show(self):
        # Al ENTRAR a la vista sí releemos el banco del disco (pudo cambiar
        # fuera de aquí). Las micro-acciones posteriores ya NO releen disco.
        try:
            self._pipeline.reload_bank()
        except Exception as exc:
            logger.error("on_show: reload_bank falló: %s", exc, exc_info=True)
        self._reload_and_refresh_all()
        self._maybe_load_pending_text()

    # ── Colores por tier (Gold/Silver/Bronze) ───────────────────────
    # Reubicados desde extractor_tab_grid (eliminado en la limpieza v4.2); los
    # usa el Banco (bank_tab_render) para colorear celdas según calidad.

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

    def _on_tab_change(self) -> None:
        """Refresca de forma diferida un tab que quedó marcado como sucio.

        El refresco de banco/revisión es caro (reconstruye cientos de widgets);
        en vez de rehacer el tab no visible en cada acción, lo marcamos sucio y
        lo reconstruimos solo cuando el usuario lo abre.
        """
        try:
            name = self._tabs.get()
        except Exception:
            return
        if name not in self._tabs_dirty:
            return
        self._tabs_dirty.discard(name)
        try:
            if name == self._BANK_TAB:
                self._do_refresh_bank_ui()
            elif name == self._REVIEW_TAB:
                self._do_refresh_review_ui()
        except Exception as exc:
            logger.error("_on_tab_change(%s) falló: %s", name, exc, exc_info=True)

    def _maybe_load_pending_text(self) -> None:
        """Carga texto pendiente de Study si el escritor está vacío."""
        try:
            st = self.app.app_state
        except AttributeError:
            return
        pending = getattr(st, "study_text", None)
        pending_doc = getattr(st, "study_document", None)
        if not pending:
            return
        current = self._writer_text.get("0.0", "end").strip()
        if not current:
            self._writer_text.delete("0.0", "end")
            self._writer_text.insert("0.0", pending)
            # Guarda el Document para renderizar con estructura (encabezados,
            # listas, párrafos). _render_pages lo usa mientras el texto no se
            # edite; si el usuario lo cambia, cae a texto plano automáticamente.
            self._pending_document = pending_doc
            self._pending_document_text = pending.strip()
            with contextlib.suppress(Exception):
                self._tabs.set("✍️ Escritor")
            self.toast("Texto importado desde Estudio", "success")
        st.study_text = ""
        st.study_document = None

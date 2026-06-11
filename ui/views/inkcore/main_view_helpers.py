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
import time
from pathlib import Path
from typing import ClassVar

import customtkinter as ctk

from ui import perf, theme

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
    _WRITER_TAB = "✍️ Escritor"

    # ── Lazy tabs (U1/UI-02) ─────────────────────────────────────────

    def _ensure_tab_built(self, name: str, defer: bool = True) -> bool:
        """Construye el contenido del tab si aún no existe.

        defer=True (cambio de tab por click): muestra un skeleton
        "Cargando…" y construye en un after(30) para que el placeholder
        alcance a pintarse — devuelve False y _after_tab_built remata el
        refresh pendiente. defer=False (tab default al entrar / necesidad
        programática): construye síncrono y devuelve True.
        """
        builders = getattr(self, "_tab_builders", None)
        if not builders or name not in builders or name in self._tabs_built:
            return True
        self._tabs_built.add(name)
        parent = self._tabs.tab(name)
        builder = builders[name]
        if not defer:
            with perf.measure(f"build_tab({name})"):
                builder(parent)
            return True
        placeholder = ctk.CTkLabel(
            parent, text="Cargando…",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        placeholder.pack(expand=True, pady=60)

        def _do_build():
            with contextlib.suppress(Exception):
                placeholder.destroy()
            with perf.measure(f"build_tab({name})"):
                builder(parent)
            self._after_tab_built(name)

        self.after(30, _do_build)
        return False

    def _after_tab_built(self, name: str) -> None:
        """Tras un build diferido: si el tab sigue visible y quedó sucio,
        puebla su contenido (el builder solo crea la estructura)."""
        try:
            if self._tabs.get() != name:
                return
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
            logger.error("_after_tab_built(%s) falló: %s", name, exc, exc_info=True)

    def _show_tab(self, name: str) -> None:
        """Cambia de tab programáticamente. CTkTabview.set() NO dispara el
        command, así que el build lazy / refresh diferido se invoca a mano."""
        with contextlib.suppress(Exception):
            self._tabs.set(name)
        self._on_tab_change()

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

    # ── Render por lotes (anti-freeze) ──────────────────────────────
    # Los grids de Banco/Revisión/Captura construyen cientos de widgets CTk
    # (659 glifos en un banco real ≈ miles de canvases). Hacerlo síncrono
    # congela el mainloop por 10-30s ("la app se queda plasmada"). Estos
    # helpers ejecutan las operaciones de construcción en LOTES con after(),
    # con presupuesto de tiempo por tick, para que la UI siga respondiendo.

    def _cancel_chunked(self, key: str) -> None:
        """Cancela un render por lotes pendiente (y su estado de reanudación).
        LLAMAR ANTES de destruir los widgets del render anterior — un tick ya
        encolado que corra después del destroy pintaría sobre parents muertos
        (TclError)."""
        state = getattr(self, "_chunk_state", None)
        if state:
            state.pop(key, None)
        jobs = getattr(self, "_chunk_jobs", None)
        if not jobs:
            return
        prev = jobs.pop(key, None)
        if prev is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(prev)

    def _render_chunked(self, key: str, ops: list, on_done=None,
                        budget_ms: int = 25) -> None:
        """Ejecuta `ops` (closures sin args que construyen widgets) por lotes.

        Cada tick consume ops hasta agotar `budget_ms` y se re-agenda con
        after(12), dejando respirar al event loop entre lotes. Un nuevo render
        con la misma `key` cancela al anterior. Si una op truena, se loggea y
        se sigue con la siguiente (una celda rota no congela el resto).

        El estado vive en self._chunk_state[key] para poder PAUSAR el render de
        una pestaña que dejó de ser visible y reanudarlo al volver (un solo
        render compite por el mainloop a la vez — ver _on_tab_change).
        """
        if not hasattr(self, "_chunk_jobs"):
            self._chunk_jobs = {}
        if not hasattr(self, "_chunk_state"):
            self._chunk_state = {}
        self._cancel_chunked(key)
        self._chunk_state[key] = {"ops": ops, "i": 0, "on_done": on_done,
                                  "budget": max(5, budget_ms) / 1000.0}
        self._chunk_tick(key)

    def _chunk_tick(self, key: str) -> None:
        self._chunk_jobs.pop(key, None)
        st = self._chunk_state.get(key)
        if st is None:
            return
        ops, budget = st["ops"], st["budget"]
        t0 = time.perf_counter()
        i, n = st["i"], len(ops)
        while i < n and (time.perf_counter() - t0) < budget:
            try:
                ops[i]()
            except Exception:
                logger.exception("_render_chunked(%s): op %d falló", key, i)
            i += 1
        st["i"] = i
        if i < n:
            if self.winfo_exists():
                self._chunk_jobs[key] = self.after(12, lambda: self._chunk_tick(key))
        else:
            on_done = st.get("on_done")
            self._chunk_state.pop(key, None)
            if on_done is not None:
                with contextlib.suppress(Exception):
                    on_done()

    def _pause_chunked(self, key: str) -> None:
        """Detiene los ticks de un render sin perder su posición (se reanuda
        con _resume_chunked). Pausar lo no visible deja todo el presupuesto del
        mainloop al render de la pestaña activa."""
        jobs = getattr(self, "_chunk_jobs", None)
        if not jobs:
            return
        prev = jobs.pop(key, None)
        if prev is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(prev)

    def _resume_chunked(self, key: str) -> None:
        """Reanuda un render pausado (no-op si terminó o no existe)."""
        state = getattr(self, "_chunk_state", None)
        jobs = getattr(self, "_chunk_jobs", None)
        if not state or key not in state:
            return
        if jobs and key in jobs:  # ya corriendo
            return
        self._chunk_tick(key)

    # ── Colores por tier (Gold/Silver/Bronze) ───────────────────────
    # Reubicados desde extractor_tab_grid (eliminado en la limpieza v4.2); los
    # usa el Banco (bank_tab_render) para colorear celdas según calidad.

    @staticmethod
    def _tier_text_color(tier: str) -> str:
        return {
            "Gold":   theme.ACCENT_YELLOW,
            "Silver": theme.TIER_COLORS["Silver"],
            "Bronze": theme.TIER_COLORS["Bronze"],
        }.get(tier, theme.TEXT_MUTED)

    @staticmethod
    def _tier_border(tier: str) -> str:
        return {
            "Gold":   theme.ACCENT_GREEN,
            "Silver": theme.ACCENT_ORANGE,
            "Bronze": theme.BORDER,
        }.get(tier, theme.BORDER)

    # Render-job (clave de _render_chunked) que pertenece a cada pestaña.
    _TAB_RENDER_KEYS: ClassVar[dict[str, str]] = {
        "2 · 📦 Captura masiva": "bulk_grid",
        "3 · ✅ Revisión": "review_rows",
        "🗂 Banco": "bank_cells",
    }

    def _on_tab_change(self) -> None:
        """Refresca de forma diferida un tab que quedó marcado como sucio.

        El refresco de banco/revisión es caro (reconstruye cientos de widgets);
        en vez de rehacer el tab no visible en cada acción, lo marcamos sucio y
        lo reconstruimos solo cuando el usuario lo abre.

        También pausa los render por lotes de las pestañas NO visibles y
        reanuda el de la visible: si los tres grids construyen a la vez se
        reparten el mainloop y todo aparece a cuentagotas.
        """
        try:
            name = self._tabs.get()
        except Exception:
            return
        if not self._ensure_tab_built(name):
            # Build diferido en curso: pausar los renders de otros tabs y
            # dejar que _after_tab_built haga el refresh al terminar.
            for tab, key in self._TAB_RENDER_KEYS.items():
                if tab != name:
                    self._pause_chunked(key)
            return
        for tab, key in self._TAB_RENDER_KEYS.items():
            if tab == name:
                self._resume_chunked(key)
            else:
                self._pause_chunked(key)
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
        # Lazy tabs: el Escritor puede no estar construido aún.
        self._ensure_tab_built(self._WRITER_TAB, defer=False)
        current = self._writer_text.get("0.0", "end").strip()
        if not current:
            self._writer_text.delete("0.0", "end")
            self._writer_text.insert("0.0", pending)
            # Guarda el Document para renderizar con estructura (encabezados,
            # listas, párrafos). _render_pages lo usa mientras el texto no se
            # edite; si el usuario lo cambia, cae a texto plano automáticamente.
            self._pending_document = pending_doc
            self._pending_document_text = pending.strip()
            self._show_tab(self._WRITER_TAB)
            self.toast("Texto importado desde Estudio", "success")
        st.study_text = ""
        st.study_document = None

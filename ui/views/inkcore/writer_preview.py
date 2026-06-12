"""WriterPreviewMixin — panel de preview del Escritor (U5).

Mata UI-03/12: el preview muestra UNA página con navegador ◀ n/N ▶ y zoom
(50/100/150%), nada de apilar todas las páginas como PhotoImages. Los
resize PIL ocurren en un worker thread (al main solo llegan imágenes
listas) y un contador de generación descarta renders/resizes viejos.

Preview en vivo (F3): al teclear, debounce de 600 ms → re-render del
documento con seed FIJA (layout estable mientras editas) mostrando la
página visible; el toggle "En vivo" lo apaga para documentos largos.

Banner de cobertura (F6): antes de cada render consulta
renderer.coverage_report(text); si hay chars sin glifo aparece una franja
ámbar con CTA a Plantilla.
"""
import contextlib
import logging
import threading

import customtkinter as ctk

from ui import icons, perf, theme

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

_ZOOMS = {"50%": 0.5, "100%": 1.0, "150%": 1.5}
_BASE_W = 520          # ancho de página al 100%
_LIVE_SEED = 1234      # seed fija del preview en vivo (layout estable)


class WriterPreviewMixin:
    """Preview paginado del Escritor; mezclado en InkCoreView vía WriterTabMixin."""

    # ── Build ──────────────────────────────────────────────────────

    def _build_writer_preview(self, right) -> None:
        self._wp_pages: list = []          # páginas PIL a resolución completa
        self._wp_idx = 0
        self._wp_zoom = 1.0
        self._wp_photo_cache: dict = {}    # (idx, zoom) → CTkImage
        self._wp_generation = 0            # invalida renders/resizes en vuelo
        self._wp_live_job = None

        header = ctk.CTkFrame(right, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(header, text="Preview", font=theme.FONT_SUBHEADING,
                     text_color=theme.TEXT_PRIMARY).pack(side="left")
        self._page_count_label = ctk.CTkLabel(header, text="", font=theme.FONT_SMALL,
                                              text_color=theme.TEXT_MUTED)
        self._page_count_label.pack(side="right")

        bar = ctk.CTkFrame(right, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(0, 4))
        self._wp_prev_btn = ctk.CTkButton(
            bar, text="", image=icons.get_icon("chevron-l", 13), width=30, height=24,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            corner_radius=theme.RADIUS["s"], command=lambda: self._wp_go(-1))
        self._wp_prev_btn.pack(side="left")
        self._wp_page_lbl = ctk.CTkLabel(bar, text="– / –", width=60,
                                         font=theme.FONT_SMALL,
                                         text_color=theme.TEXT_SECONDARY)
        self._wp_page_lbl.pack(side="left", padx=2)
        self._wp_next_btn = ctk.CTkButton(
            bar, text="", image=icons.get_icon("chevron-r", 13), width=30, height=24,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            corner_radius=theme.RADIUS["s"], command=lambda: self._wp_go(1))
        self._wp_next_btn.pack(side="left")

        self._wp_zoom_seg = ctk.CTkSegmentedButton(
            bar, values=list(_ZOOMS), height=24,
            font=theme.FONT_SMALL,
            selected_color=theme.ACCENT_PRIMARY,
            selected_hover_color=theme.ACCENT_PRIMARY_HOVER,
            unselected_color=theme.BG_TERTIARY,
            unselected_hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            command=self._wp_set_zoom)
        self._wp_zoom_seg.set("100%")
        self._wp_zoom_seg.pack(side="left", padx=theme.SPACE["m"])

        self._wp_live_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(bar, text="En vivo", variable=self._wp_live_var,
                      font=theme.FONT_SMALL, progress_color=theme.ACCENT_CYAN,
                      width=40).pack(side="right")

        # Banner de cobertura (F6) — se crea una vez, pack/forget según haga falta
        self._wp_banner = ctk.CTkFrame(right, fg_color=theme.BADGE_BG_ORANGE,
                                       corner_radius=theme.RADIUS["s"],
                                       border_width=1, border_color=theme.ACCENT_PRIMARY)
        self._wp_banner_lbl = ctk.CTkLabel(self._wp_banner, text="",
                                           font=theme.FONT_SMALL,
                                           text_color=theme.ACCENT_PRIMARY_SOFT)
        self._wp_banner_lbl.pack(side="left", padx=theme.SPACE["s"], pady=4)
        ctk.CTkButton(self._wp_banner, text="Ir a Plantilla", height=20, width=100,
                      font=theme.FONT_SMALL, fg_color="transparent",
                      hover_color=theme.BG_TERTIARY, text_color=theme.ACCENT_CYAN,
                      command=lambda: self._show_tab("1 · 🧩 Plantilla"),
                      ).pack(side="right", padx=theme.SPACE["xs"])

        body = ctk.CTkFrame(right, fg_color=theme.BG_TERTIARY,
                            corner_radius=theme.RADIUS["m"])
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._wp_img_label = ctk.CTkLabel(
            body, text="El resultado aparecerá aquí",
            text_color=theme.TEXT_MUTED, font=theme.FONT_BODY)
        self._wp_img_label.pack(expand=True)

        # Compat: algunos flujos viejos referencian este label
        self._writer_preview_label = self._wp_img_label

        # Preview en vivo: teclear re-renderiza la página visible (debounce)
        with contextlib.suppress(Exception):
            self._writer_text.bind("<KeyRelease>", self._wp_on_typing, add="+")

        self._wp_update_nav()

    # ── API pública (compat con _preview_handwriting) ──────────────

    def _show_preview_pages(self, pages: list) -> None:
        """Recibe la lista de páginas PIL renderizadas y muestra la visible."""
        if not self.winfo_exists():
            return
        self._wp_generation += 1
        self._wp_pages = list(pages or [])
        self._wp_photo_cache.clear()
        n = len(self._wp_pages)
        if not n:
            self._wp_img_label.configure(
                image=None, text="Error al renderizar. ¿El banco tiene glifos?",
                text_color=theme.ACCENT_RED)
            self._page_count_label.configure(text="")
            self._wp_update_nav()
            return
        self._wp_idx = min(self._wp_idx, n - 1)
        self._page_count_label.configure(
            text=f"{n} {'página' if n == 1 else 'páginas'}")
        self._wp_update_nav()
        self._wp_show_page()

    # ── Navegación / zoom ──────────────────────────────────────────

    def _wp_go(self, delta: int) -> None:
        if not self._wp_pages:
            return
        self._wp_idx = max(0, min(len(self._wp_pages) - 1, self._wp_idx + delta))
        self._wp_update_nav()
        self._wp_show_page()

    def _wp_set_zoom(self, label: str) -> None:
        self._wp_zoom = _ZOOMS.get(label, 1.0)
        if self._wp_pages:
            self._wp_show_page()

    def _wp_update_nav(self) -> None:
        n = len(self._wp_pages)
        self._wp_page_lbl.configure(text=f"{self._wp_idx + 1} / {n}" if n else "– / –")
        self._wp_prev_btn.configure(state="normal" if self._wp_idx > 0 else "disabled")
        self._wp_next_btn.configure(
            state="normal" if self._wp_idx < n - 1 else "disabled")

    # ── Mostrar página (resize en worker, P7) ──────────────────────

    def _wp_show_page(self) -> None:
        if not (_PIL_OK and self._wp_pages):
            return
        idx, zoom = self._wp_idx, self._wp_zoom
        cached = self._wp_photo_cache.get((idx, zoom))
        if cached is not None:
            self._wp_img_label.configure(image=cached, text="")
            return
        gen = self._wp_generation
        page = self._wp_pages[idx]

        def worker():
            target_w = int(_BASE_W * zoom)
            with perf.measure(f"wp_resize(p{idx}@{zoom})"):
                img = page
                if img.width != target_w:
                    img = img.resize(
                        (target_w, int(img.height * target_w / img.width)),
                        Image.LANCZOS)
            if gen != self._wp_generation:
                return  # llegó tarde: ya hay un render/estado más nuevo
            self.after(0, lambda: self._wp_apply_photo(gen, idx, zoom, img))

        threading.Thread(target=worker, daemon=True, name="wp-resize").start()

    def _wp_apply_photo(self, gen: int, idx: int, zoom: float, img) -> None:
        if gen != self._wp_generation or not self.winfo_exists():
            return
        photo = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
        self._wp_photo_cache[(idx, zoom)] = photo
        if len(self._wp_photo_cache) > 24:
            self._wp_photo_cache.pop(next(iter(self._wp_photo_cache)))
        if (idx, zoom) == (self._wp_idx, self._wp_zoom):
            self._wp_img_label.configure(image=photo, text="")

    # ── Preview en vivo (F3) ───────────────────────────────────────

    def _wp_on_typing(self, _event=None) -> None:
        if not self._wp_live_var.get():
            return
        if self._wp_live_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._wp_live_job)
        self._wp_live_job = self.after(600, self._wp_render_live)

    def _wp_render_live(self) -> None:
        self._wp_live_job = None
        text = self._writer_text.get("0.0", "end").strip()
        if not text:
            return
        renderer = self._pipeline.renderer
        if renderer is None:
            return
        self._wp_update_coverage_banner(renderer, text)
        opts = self._get_render_options()
        opts.allow_font_fallback = True
        opts.seed = _LIVE_SEED  # layout estable mientras se edita
        self._wp_generation += 1
        gen = self._wp_generation

        def worker():
            try:
                with perf.measure("wp_live_render"):
                    pages = self._render_pages(renderer, text, opts)
            except Exception as exc:
                logger.warning("preview en vivo falló: %s", exc)
                return
            if gen != self._wp_generation:
                return  # el usuario siguió tecleando: este render ya caducó
            self.after(0, lambda: gen == self._wp_generation
                       and self._show_preview_pages(pages))

        threading.Thread(target=worker, daemon=True, name="wp-live").start()

    # ── Banner de cobertura (F6) ───────────────────────────────────

    def _wp_update_coverage_banner(self, renderer, text: str) -> None:
        missing: list = []
        try:
            rep = renderer.coverage_report(text)
            missing = sorted(rep.get("missing") or [])
        except Exception:
            # Fallback simple si el renderer no trae coverage_report
            with contextlib.suppress(Exception):
                have = {g.char for g in self._pipeline.bank.get_all()}
                missing = sorted({c for c in text if c.strip()} -
                                 have - {c.upper() for c in have})
        if missing:
            chars = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            self._wp_banner_lbl.configure(
                text=f"⚠ Sin glifo: {chars} — el render los omitirá")
            if not self._wp_banner.winfo_ismapped():
                self._wp_banner.pack(fill="x", padx=12, pady=(0, 4),
                                     before=self._wp_img_label.master)
        elif self._wp_banner.winfo_ismapped():
            self._wp_banner.pack_forget()

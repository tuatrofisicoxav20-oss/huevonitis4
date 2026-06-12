"""ReviewTabMixin — tab ✅ Revisión de InkCoreView."""
import logging
import time
from tkinter import filedialog
from typing import ClassVar

import customtkinter as ctk

from core.diagnostics import diagnostics
from ui import theme

logger = logging.getLogger(__name__)


class ReviewTabMixin:
    """Tab de revisión y aprobación de glifos; mezclado en InkCoreView."""

    # ── Build ──────────────────────────────────────────────────────

    def _build_review(self, parent):
        self._review_stats_bar = ctk.CTkFrame(parent, fg_color="transparent")
        self._review_stats_bar.pack(fill="x", padx=12, pady=(10, 4))

        self._review_pending_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🔴  …  pendientes",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_RED,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_pending_lbl.pack(side="left", padx=4)

        self._review_silver_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🟡  …  Silver",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_YELLOW,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_silver_lbl.pack(side="left", padx=4)

        self._review_gold_lbl = ctk.CTkLabel(
            self._review_stats_bar, text="🟢  …  Gold",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT_GREEN,
            fg_color=theme.BG_TERTIARY,
            corner_radius=12,
            padx=10, pady=4,
        )
        self._review_gold_lbl.pack(side="left", padx=4)

        ctk.CTkButton(
            self._review_stats_bar,
            text="📄 Exportar informe PDF",
            height=28, width=180,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
            command=self._export_report_pdf,
        ).pack(side="right", padx=4)

        self._review_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._review_scroll.pack(fill="both", expand=True, padx=8, pady=4)

        batch_bar = ctk.CTkFrame(
            parent,
            fg_color=theme.BG_SECONDARY,
            corner_radius=8,
            border_width=1,
            border_color=theme.BORDER,
        )
        batch_bar.pack(fill="x", padx=12, pady=(4, 10))

        ctk.CTkButton(
            batch_bar, text="☑ Seleccionar todos",
            width=160, height=30,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.BORDER,
            font=theme.FONT_SMALL,
            command=self._review_select_all,
        ).pack(side="left", padx=8, pady=6)

        ctk.CTkButton(
            batch_bar, text="✅ Aprobar seleccionados",
            width=180, height=30,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.FONT_SMALL,
            command=lambda: self._review_batch_action("approve"),
        ).pack(side="left", padx=4, pady=6)

        ctk.CTkButton(
            batch_bar, text="❌ Rechazar seleccionados",
            width=180, height=30,
            fg_color=theme.ACCENT_RED,
            hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_SMALL,
            command=lambda: self._review_batch_action("reject"),
        ).pack(side="left", padx=4, pady=6)

    # ── Logic ──────────────────────────────────────────────────────

    def _refresh_review(self):
        self._pipeline.reload_bank()
        self._do_refresh_review_ui()

    def _do_refresh_review_ui(self):
        t0 = time.perf_counter()
        # Anti-freeze: cancelar un render por lotes en curso ANTES de destruir
        # (un tick encolado pintaría sobre widgets muertos).
        self._cancel_chunked("review_rows")
        for w in self._review_scroll.winfo_children():
            w.destroy()
        self._review_photos.clear()
        self._review_checkboxes.clear()
        self._review_check_vars.clear()

        # El review muestra TODO el banco para reclasificar/limpiar muestras,
        # ordenado de peor a mejor (Bronze y baja calidad arriba) para que lo
        # que necesita atención salte primero a la vista.
        all_entries = self._pipeline.bank.get_all()
        silver_count = sum(1 for e in all_entries if e.tier == "Silver")
        gold_count = sum(1 for e in all_entries if e.tier == "Gold")
        attention = sum(
            1 for e in all_entries if e.tier == "Bronze" or e.quality_score < 0.50
        )

        if attention == 0 and all_entries:
            # U6: estado "todo revisado" — check ámbar en vez de contador rojo
            self._review_pending_lbl.configure(text="✓  Todo revisado")
        else:
            self._review_pending_lbl.configure(text=f"🔴  {attention}  por revisar")
        self._review_silver_lbl.configure(text=f"🟡  {silver_count}  Silver")
        self._review_gold_lbl.configure(text=f"🟢  {gold_count}  Gold")

        if not all_entries:
            ctk.CTkLabel(
                self._review_scroll,
                text="Banco vacío.\nGenera una plantilla (paso 1) y cárgala en"
                     " Captura masiva (paso 2) para llenar el banco.",
                font=theme.FONT_BODY,
                text_color=theme.TEXT_MUTED,
            ).pack(pady=40)
            return

        _TIER_RANK = {"Bronze": 0, "Silver": 1, "Gold": 2}
        ordered = sorted(
            all_entries,
            key=lambda e: (_TIER_RANK.get(e.tier, 0), e.quality_score, e.char),
        )

        header = ctk.CTkFrame(self._review_scroll, fg_color=theme.BG_SECONDARY, corner_radius=6)
        header.pack(fill="x", padx=2, pady=(2, 4))
        for text, w in [("☑", 30), ("Img", 70), ("Letra", 80), ("Calidad", 140),
                         ("Score/Tier", 100), ("Flags", 180), ("Acciones", 200)]:
            ctk.CTkLabel(
                header, text=text, width=w,
                font=theme.get_font("bold", 9),
                text_color=theme.TEXT_SECONDARY,
            ).pack(side="left", padx=4, pady=4)

        # Anti-freeze: con un banco real (~650 glifos) construir todas las filas
        # de golpe congelaba el mainloop 10-30s (layout O(n²) del scrollable).
        # Se renderiza por páginas + lotes; "Mostrar más" agrega la siguiente
        # tanda sin reconstruir lo visible.
        self._review_page_state = {"ordered": ordered, "next": 0,
                                   "more_btn": None, "t0": t0}
        self._review_render_next_page()

    _REVIEW_PAGE = 40  # ~240ms/fila en CTk: página chica = aparece rápido

    def _review_render_next_page(self):
        st = getattr(self, "_review_page_state", None)
        if not st:
            return
        if st["more_btn"] is not None:
            st["more_btn"].destroy()
            st["more_btn"] = None
        ordered = st["ordered"]
        start = st["next"]
        end = min(start + self._REVIEW_PAGE, len(ordered))
        st["next"] = end
        ops = [lambda g=ordered[i]: self._build_review_row(g)
               for i in range(start, end)]

        def _done():
            remaining = len(ordered) - st["next"]
            if remaining > 0:
                st["more_btn"] = ctk.CTkButton(
                    self._review_scroll,
                    text=f"▼ Mostrar {min(self._REVIEW_PAGE, remaining)} más "
                         f"({remaining} restantes)",
                    command=self._review_render_next_page,
                    fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
                    font=theme.FONT_SMALL, height=30,
                )
                st["more_btn"].pack(pady=8)
            elapsed_ms = (time.perf_counter() - st["t0"]) * 1000
            diagnostics.log_timing("refresh_review_ui", elapsed_ms)
            diagnostics.log_event("ui", "refresh_review",
                                  f"{st['next']}/{len(ordered)} glifos")

        self._render_chunked("review_rows", ops, on_done=_done)

    _PROMOTE_NEXT: ClassVar[dict] = {"Bronze": "Silver", "Silver": "Gold", "Gold": "Gold"}

    def _review_promote(self, glyph):
        """Sube el glifo un nivel de tier (Bronze→Silver→Gold) sin degradarlo.

        Como el review ahora lista TODO el banco, el botón ✅ no puede fijar
        Silver a ciegas (degradaría un Gold). Promueve al siguiente tier; un
        Gold ya está en el tope.
        """
        new_tier = self._PROMOTE_NEXT.get(glyph.tier, "Silver")
        if new_tier == glyph.tier:
            self.toast(f"'{glyph.char}' ya es Gold", "info")
            return
        logger.info("_review_promote: %r %s → %s", glyph.char, glyph.tier, new_tier)
        try:
            ok = self._pipeline.bank.approve_glyph(glyph, new_tier=new_tier)
        except Exception as exc:
            logger.error("_review_promote: approve_glyph lanzó: %s", exc, exc_info=True)
            self.toast(f"Error al promover: {exc}", "error")
            return
        if not ok:
            self.toast(f"'{glyph.char}' no se encontró en el banco", "warning")
            return
        self.toast(f"'{glyph.char}': {glyph.tier} → {new_tier}", "success")
        try:
            self._reload_and_refresh_all()
        except Exception as exc:
            logger.error("_review_promote: refresh lanzó: %s", exc, exc_info=True)

    def _review_reject(self, glyph):
        logger.info("_review_reject: char=%r path=%s", glyph.char, glyph.image_path)
        try:
            ok = self._pipeline.bank.reject_glyph(glyph)
        except Exception as exc:
            logger.error("_review_reject: bank.reject_glyph lanzó: %s", exc, exc_info=True)
            self.toast(f"Error al rechazar: {exc}", "error")
            return
        if not ok:
            logger.warning("_review_reject: %r no encontrado en banco", glyph.char)
            self.toast(f"'{glyph.char}' no se encontró en el banco", "warning")
            return
        self.toast(f"'{glyph.char}' eliminado del banco", "warning")
        logger.info("_review_reject: %r eliminado", glyph.char)
        try:
            self._reload_and_refresh_all()
        except Exception as exc:
            logger.error("_review_reject: refresh lanzó: %s", exc, exc_info=True)

    def _review_select_all(self):
        all_checked = all(v.get() for v in self._review_check_vars)
        for v in self._review_check_vars:
            v.set(not all_checked)

    def _review_batch_action(self, action: str):
        selected = [
            glyph for (cb, glyph), var
            in zip(self._review_checkboxes, self._review_check_vars, strict=False)
            if var.get()
        ]
        if not selected:
            self.toast("Selecciona al menos un glifo", "warning")
            return
        if action == "approve":
            # No degradar: solo sube a Silver los Bronze; deja Silver/Gold intactos.
            promoted = 0
            for g in selected:
                if g.tier == "Bronze":
                    self._pipeline.bank.approve_glyph(g, new_tier="Silver")
                    promoted += 1
            if promoted:
                self.toast(f"{promoted} glifos promovidos → Silver", "success")
            else:
                self.toast("Los seleccionados ya eran Silver o Gold", "info")
        elif action == "reject":
            for g in selected:
                self._pipeline.bank.reject_glyph(g)
            self.toast(f"{len(selected)} glifos eliminados", "warning")
        self._reload_and_refresh_all()

    def _show_report(self):
        report_data = self._reporter.generate_report(self._pipeline.bank)
        self._reporter.show_modal(self, report_data)

    def _export_report_pdf(self):
        report_data = self._reporter.generate_report(self._pipeline.bank)
        from datetime import datetime as _dt
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            title="Exportar informe PDF",
            initialfile=f"informe_glifos_{_dt.now().strftime('%Y%m%d')}.pdf",
        )
        if not path:
            return
        ok = self._reporter.export_pdf(report_data, path)
        if ok:
            self.toast("Informe PDF exportado", "success")
        else:
            self.toast("Error al exportar PDF (¿reportlab instalado?)", "error")

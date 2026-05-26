"""BulkCaptureFiltersMixin — filtros y acciones masivas (approve/commit) del bulk capture tab.

Separado de bulk_capture_tab.py. Depende de:
  • self._bulk_session, self._bulk_filter_*_val
  • self._bulk_render_grid (en grid mixin)
  • self._bulk_stats_lbl, self._bulk_filter_char_combo
  • self._pipeline.bank
"""
import logging
from tkinter import messagebox

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)


class BulkCaptureFiltersMixin:
    """Filtros (conf, status, char) + acciones (approve-all, commit)."""

    def _bulk_update_char_filter(self):
        if not self._bulk_session:
            return
        chars = sorted({c.display_char for c in self._bulk_session.candidates})
        self._bulk_filter_char_combo.configure(values=["(todos)"] + chars)
        self._bulk_filter_char_combo.set(self._bulk_filter_char_val)

    def _bulk_filtered_candidates(self) -> list:
        if not self._bulk_session:
            return []
        result = self._bulk_session.candidates
        sv = self._bulk_filter_status_val
        if sv == "Pendientes":
            result = [c for c in result if c.decision == "pending"]
        elif sv == "Aprobados":
            result = [c for c in result if c.decision == "approved"]
        elif sv == "Rechazados":
            result = [c for c in result if c.decision == "rejected"]
        cv = self._bulk_filter_conf_val
        if cv == "Necesita revisión":
            result = [c for c in result if c.needs_review]
        elif cv == "Alta confianza":
            result = [c for c in result if not c.needs_review]
        fchar = self._bulk_filter_char_val
        if fchar and fchar != "(todos)":
            result = [c for c in result if c.display_char == fchar]
        return result

    def _bulk_on_filter_conf(self, val):
        self._bulk_filter_conf_val = val
        self._bulk_render_grid()
        self._bulk_update_stats()

    def _bulk_on_filter_status(self, val):
        self._bulk_filter_status_val = val
        self._bulk_render_grid()
        self._bulk_update_stats()

    def _bulk_on_filter_char(self, val):
        self._bulk_filter_char_val = val
        self._bulk_render_grid()
        self._bulk_update_stats()

    def _bulk_approve_high_conf(self):
        if not self._bulk_session:
            return
        count = 0
        for cand in self._bulk_session.candidates:
            if cand.decision == "pending" and cand.glyph.tier in ("Gold", "Silver"):
                cand.decision = "approved"
                count += 1
        self._bulk_render_grid()
        self._bulk_update_stats()
        self.toast(f"{count} candidatos Gold/Silver aprobados", "success")

    def _bulk_update_stats(self):
        if not self._bulk_session:
            self._bulk_stats_lbl.configure(text="")
            return
        s = self._bulk_session.stats()
        self._bulk_stats_lbl.configure(
            text=(f"Total: {s['total']}  ⏳{s['pending']}  ✅{s['approved']}"
                  f"  ❌{s['rejected']}  ⚠️{s['needs_review']}")
        )

    def _bulk_commit_to_bank(self):
        if not self._bulk_session:
            return
        approved = [c for c in self._bulk_session.candidates if c.decision == "approved"]
        if not approved:
            self.toast("No hay candidatos aprobados para guardar", "warning")
            return
        if not messagebox.askyesno(
            "Confirmar",
            f"¿Guardar {len(approved)} glifos al banco?\n"
            "Esto modifica permanentemente tu banco de tipografía.",
        ):
            return
        saved = 0
        failed = 0
        for c in approved:
            try:
                result = self._pipeline.bank.add_glyph(
                    c.display_char, c.glyph.image_path,
                    predicted_char=c.glyph.predicted_char,
                    label_confidence=c.glyph.label_confidence,
                    detector_sources=c.glyph.detector_sources,
                    quality_override={
                        "score": c.glyph.quality_score,
                        "tier": c.glyph.tier,
                        "ink_coverage": c.glyph.ink_coverage,
                    },
                )
                if result is not None:
                    saved += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error("bulk_commit: no se pudo guardar glifo: %s", exc)
                failed += 1

        msg = f"Guardados {saved} glifos al banco"
        if failed:
            msg += f" ({failed} fallaron o duplicados)"
        self.toast(msg, "success" if not failed else "warning")

        # Limpiar directorio temporal del bulk capture (análogo a _cleanup_temp_dir
        # del flujo de extractor individual). Sin esto los PNGs de cada sesión
        # se acumulan en temp_bulk_capture/ indefinidamente.
        try:
            import config as _cfg
            temp_bulk = _cfg.DATA_DIR / "temp_bulk_capture"
            if temp_bulk.exists():
                removed = 0
                for png in temp_bulk.glob("*.png"):
                    try:
                        png.unlink()
                        removed += 1
                    except OSError as _e:
                        logger.warning("bulk_commit: no se pudo borrar %s: %s", png, _e)
                if removed:
                    logger.debug("bulk_commit: eliminados %d PNGs temporales de %s",
                                 removed, temp_bulk)
        except Exception as _e:
            logger.warning("bulk_commit: limpieza de temporales falló: %s", _e)

        self._bulk_session = None
        self._bulk_card_widgets = []
        self._bulk_selected_idx = None
        self._bulk_filters_frame.pack_forget()
        for w in self._bulk_grid_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._bulk_grid_scroll,
            text="✓ Sesión completada y guardada al banco.\n\n"
                 "Carga un nuevo PDF para continuar capturando glifos.",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            justify="center",
        ).pack(pady=80)
        self._bulk_stats_lbl.configure(text="")
        self._bulk_approve_all_btn.configure(state="disabled")
        self._bulk_commit_btn.configure(state="disabled")
        self._bulk_status.configure(
            text="Sin sesión activa. Carga un PDF o imágenes para empezar.",
            text_color=theme.TEXT_MUTED,
        )
        self._reload_and_refresh_all()

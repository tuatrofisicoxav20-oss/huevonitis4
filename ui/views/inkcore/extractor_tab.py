"""ExtractorTabMixin — tab 📷 Extractor de InkCoreView.

Flujo de extracción (extract → on_extracted → debug overlay) + chips del
pipeline. La construcción de UI vive en extractor_tab_build.py, la grilla en
extractor_tab_grid.py, la entrada/preview en extractor_tab_input.py y el
guardado al banco en extractor_tab_save.py. ExtractorTabMixin hereda de esos
sub-mixins para que InkCoreView siga viendo una sola clase con toda la API.
"""
import logging
import threading
from pathlib import Path

import customtkinter as ctk

import config
from core.inkcore.extractor import ExtractionOptions
from ui import theme
from ui.views.inkcore.extractor_tab_input import ExtractorTabInputMixin
from ui.views.inkcore.extractor_tab_save import ExtractorTabSaveMixin

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class ExtractorTabMixin(ExtractorTabInputMixin, ExtractorTabSaveMixin):
    """Tab de extracción individual de glifos; mezclado en InkCoreView."""

    # ── Extraction ─────────────────────────────────────────────────

    def _extract(self):
        logger.info("_extract() llamado")
        if not self._image_path:
            logger.warning("_extract: sin imagen")
            self._extract_error.configure(
                text="⚠ Primero debes cargar una imagen con el botón '📷 Cargar imagen'"
            )
            self.toast("Carga una imagen primero", "warning")
            return

        auto_mode = bool(getattr(self, "_auto_mode_var", None) and self._auto_mode_var.get())
        ref = self._ref_text.get("1.0", "end").strip()
        logger.info("_extract: auto=%s, texto de referencia = %r", auto_mode, ref[:80])
        if not auto_mode and not ref:
            logger.warning("_extract: texto de referencia vacío y modo manual")
            self._extract_error.configure(
                text="⚠ Activa 'Modo automático' o escribe el texto de referencia"
            )
            self.toast("Activa modo automático o escribe el texto", "warning")
            return

        self._extract_error.configure(text="")

        # MODO AUTOMÁTICO MEJORADO: OCR-first.
        # 1) Predecimos el texto sobre la imagen COMPLETA con TrOCR (o Tesseract
        #    PSM 6 como fallback). Esto es muchísimo más preciso que clasificar
        #    cada glifo aislado con tesseract single-char.
        # 2) Usamos ese texto como reference_text para el flujo legacy, que ya
        #    está optimizado para alinear bboxes a chars conocidos.
        if auto_mode:
            from core.inkcore.auto_text import predict_text_from_image
            self._extract_status.configure(
                text="🔎 Detectando texto en la imagen…",
                text_color=theme.ACCENT_BLUE,
            )
            self.update_idletasks()
            try:
                predicted, source, conf = predict_text_from_image(self._image_path)
            except Exception as exc:
                logger.error("predict_text_from_image error: %s", exc, exc_info=True)
                predicted, source, conf = "", "", 0.0
            logger.info("auto-mode OCR (%s) conf=%.2f → %r",
                        source, conf, predicted[:80])

            # Si la confidence es baja o el resultado parece raro,
            # abrimos un diálogo editable con plantillas rápidas.
            # TrOCR falla en letras aisladas (alfabeto manuscrito en grid):
            # devuelve "a p.a.d gr. Fig. humanization" en lugar de "a b c d…".
            need_confirm = (
                conf < 0.75
                or not predicted
                or self._looks_suspect(predicted)
            )
            if need_confirm:
                self._extract_status.configure(text="", text_color=theme.TEXT_MUTED)
                ref = self._ask_user_ref_text(predicted, conf)
                if not ref:
                    self._extract_error.configure(
                        text="⚠ Extracción cancelada — sin texto de referencia"
                    )
                    self.toast("Cancelado", "info")
                    return
            else:
                ref = predicted
                self.toast(f"OCR ({source}) detectó: {ref[:40]}…", "info")

        # Pipeline ensemble es opcional incluso en modo auto (el OCR-first ya
        # garantiza el texto). Lo respetamos si el usuario lo activó manualmente.
        use_p = bool(self._use_pipeline_var.get())
        cfg = self._get_pipeline_config() if use_p else None
        opts = ExtractionOptions(
            remove_lines=self._remove_lines_var.get(),
            brightness=float(self._brightness_slider.get()),
            contrast=float(self._contrast_slider.get()),
            rotation_deg=float(self._rotation_slider.get()),
            use_pipeline=use_p,
            pipeline_config=cfg,
            min_quality=float(self._min_quality_slider.get()) if use_p else config.MIN_GLYPH_QUALITY,
        )
        logger.info("_extract: opts=%s, iniciando hilo", opts)

        # Refresca el chip para que refleje exactamente la corrida en curso
        try:
            self._refresh_pipeline_chip()
        except Exception:
            pass

        self._extract_progress.pack(fill="x", padx=12, pady=2)
        self._extract_progress.start()
        self._extract_btn.configure(state="disabled")
        self._extract_status.configure(
            text="Procesando imagen...", text_color=theme.ACCENT_ORANGE,
        )
        self.toast("Extrayendo glifos...", "info")

        image_path = self._image_path

        def worker():
            logger.info("worker: iniciando extracción")
            try:
                glyphs = self._pipeline.extract(image_path, ref, opts)
                logger.info("worker: extracción completada — %d glifos", len(glyphs))
            except Exception as exc:
                logger.error("worker: error en extracción: %s", exc, exc_info=True)
                glyphs = []
            try:
                self.after(0, lambda: self._on_extracted(glyphs))
            except Exception as e:
                logger.error("worker: error al programar callback: %s", e)

        threading.Thread(target=worker, daemon=True).start()
        logger.info("_extract: hilo iniciado")

    def _on_extracted(self, glyphs: list):
        if not self.winfo_exists():
            return
        self._extract_progress.stop()
        self._extract_progress.pack_forget()
        self._extract_btn.configure(state="normal")
        self._extracted = glyphs
        self._show_extracted_grid()
        if glyphs:
            gold   = sum(1 for g in glyphs if g.tier == "Gold")
            silver = sum(1 for g in glyphs if g.tier == "Silver")
            bronze = sum(1 for g in glyphs if g.tier == "Bronze")
            line1 = (f"✓ {len(glyphs)} glifos  —  "
                     f"🥇 Gold: {gold}  🥈 Silver: {silver}  🥉 Bronze: {bronze}")

            ensemble = getattr(self._pipeline.extractor, "_last_ensemble_result", None)
            extra = ""
            if ensemble is not None:
                stats = getattr(ensemble, "stats", {}) or {}
                timings = getattr(ensemble, "timings_ms", {}) or {}
                det_counts = stats.get("detector_counts", {})
                det_str = ", ".join(f"{k}:{v}" for k, v in det_counts.items()) or "—"
                discarded = stats.get("glyphs_discarded", 0)
                total_ms = timings.get("total_ms", 0)
                extra = (f"\nEnsemble · detectores [{det_str}] · "
                         f"fusionados {stats.get('fused_count', 0)} · "
                         f"descartados {discarded} · {total_ms} ms")
            self._extract_status.configure(
                text=line1 + extra,
                text_color=theme.ACCENT_GREEN,
            )
            self.toast(f"{len(glyphs)} glifos extraídos", "success")

            # Auto-abrir debug overlay si el pipeline lo generó
            if ensemble is not None and getattr(ensemble, "debug_image_path", None):
                try:
                    self._open_debug_overlay(ensemble.debug_image_path)
                except Exception as _e:
                    logger.warning("No se pudo abrir debug overlay: %s", _e)
        else:
            self._extract_status.configure(
                text="Sin glifos — sube brillo/contraste, o prueba sin 'Quitar líneas'",
                text_color=theme.ACCENT_RED,
            )
            self.toast("Sin glifos. Revisa el log: ~/.local/share/huevonitis4/app.log", "warning")

    def _open_debug_overlay(self, path: str):
        if not _PIL_OK or not Path(path).exists():
            return
        win = ctk.CTkToplevel(self)
        win.title("Debug overlay — pipeline ensemble")
        win.configure(fg_color=theme.BG_PRIMARY)
        ctk.CTkLabel(
            win, text="Verde: todos los detectores · Amarillo: parcial · Rojo: descartado",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(pady=(10, 4))
        img = Image.open(path)
        max_w = 1000
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        lbl = ctk.CTkLabel(win, image=photo, text="")
        lbl.pack(padx=12, pady=8)
        lbl._photo_ref = photo
        ctk.CTkButton(
            win, text="Cerrar", command=win.destroy,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY, width=100,
        ).pack(pady=(0, 12))
        win.geometry(f"{img.width + 32}x{img.height + 100}")

    def _refresh_detector_chip(self) -> None:
        """Alias retrocompatible — delega al nuevo _refresh_pipeline_chip."""
        self._refresh_pipeline_chip()

    def _refresh_pipeline_chip(self) -> None:
        """Muestra qué detectores + labelers están activos en el ensemble."""
        chip = getattr(self, "_detector_chip", None)
        if chip is None:
            return
        try:
            det_vars = getattr(self, "_detector_vars", {}) or {}
            lab_vars = getattr(self, "_labeler_vars", {}) or {}
            dets = [name for name, var in det_vars.items() if var.get()]
            labs = [name for name, var in lab_vars.items() if var.get()]
            if not dets and not labs:
                # Fallback al detector configurado (compat flow legacy)
                det_name = getattr(config, "GLYPH_DETECTOR", "classic_cv")
                chip.configure(text=f"  ⚙ {det_name}  ")
                return
            parts = []
            if dets:
                parts.append("D:" + "+".join(d.replace("_labeler", "").replace("_det", "") for d in dets))
            if labs:
                parts.append("L:" + "+".join(l.replace("_labeler", "") for l in labs))
            chip.configure(text="  ⚙ " + "  ".join(parts) + "  ")
        except Exception:
            pass

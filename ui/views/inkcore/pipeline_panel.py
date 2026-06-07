"""PipelinePanelMixin — panel colapsable del pipeline ensemble para ExtractorTab."""
import contextlib
import logging

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)


class PipelinePanelMixin:
    """Panel avanzado de pipeline; mezclado en InkCoreView."""

    def _build_pipeline_panel(self, parent) -> None:
        from core.inkcore import glyph_detectors, glyph_labelers

        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(
            header, text="Pipeline avanzada",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left")
        self._pipeline_toggle_btn = ctk.CTkButton(
            header, text="▶", width=28, height=22,
            fg_color="transparent", hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_MUTED, font=("Segoe UI", 10),
            command=self._toggle_pipeline_panel,
        )
        self._pipeline_toggle_btn.pack(side="right")

        self._pipeline_frame = ctk.CTkFrame(
            parent, fg_color=theme.BG_TERTIARY, corner_radius=8,
            border_width=1, border_color=theme.BORDER,
        )
        self._pipeline_collapsed = True
        self._pipeline_frame.pack_forget()

        inner = self._pipeline_frame

        use_row = ctk.CTkFrame(inner, fg_color="transparent")
        use_row.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(use_row, text="Usar pipeline ensemble",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(side="left")
        self._use_pipeline_var = ctk.BooleanVar(value=True)  # F6: ensemble por defecto
        ctk.CTkSwitch(use_row, text="", variable=self._use_pipeline_var,
                      onvalue=True, offvalue=False,
                      progress_color=theme.ACCENT_ORANGE,
                      button_color=theme.ACCENT_ORANGE_HOVER, width=40).pack(side="right")

        ctk.CTkLabel(inner, text="Detectores:",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(anchor="w", padx=10)
        det_row = ctk.CTkFrame(inner, fg_color="transparent")
        det_row.pack(fill="x", padx=10, pady=(0, 4))
        self._detector_vars: dict[str, ctk.BooleanVar] = {}
        avail_dets = glyph_detectors.get_available()
        # Default: TODOS los detectores disponibles. Fusión union → más cobertura.
        for det_name, is_avail in sorted(avail_dets.items()):
            var = ctk.BooleanVar(value=is_avail)
            self._detector_vars[det_name] = var
            color = theme.TEXT_PRIMARY if is_avail else theme.TEXT_MUTED
            chip = ctk.CTkCheckBox(
                det_row, text=det_name, variable=var,
                font=theme.FONT_SMALL, text_color=color,
                checkbox_width=16, checkbox_height=16,
                checkmark_color=theme.ACCENT_ORANGE,
                fg_color=theme.ACCENT_ORANGE,
                state="normal" if is_avail else "disabled",
            )
            chip.pack(side="left", padx=4)
            if not is_avail:
                chip.configure(text=f"{det_name} (no instalado)")

        fusion_row = ctk.CTkFrame(inner, fg_color="transparent")
        fusion_row.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(fusion_row, text="Fusión:",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                     width=60).pack(side="left")
        self._fusion_var = ctk.StringVar(value="union")
        ctk.CTkOptionMenu(
            fusion_row, values=["union", "intersection", "cascade"],
            variable=self._fusion_var,
            fg_color=theme.BG_TERTIARY, button_color=theme.ACCENT_ORANGE,
            text_color=theme.TEXT_PRIMARY, width=120,
        ).pack(side="left", padx=4)

        ctk.CTkLabel(inner, text="Labelers:",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(anchor="w", padx=10)
        lab_row = ctk.CTkFrame(inner, fg_color="transparent")
        lab_row.pack(fill="x", padx=10, pady=(0, 4))
        self._labeler_vars: dict[str, ctk.BooleanVar] = {}
        avail_labs = glyph_labelers.get_available()
        # Default: TODOS los labelers disponibles. El voting elige el ganador.
        for lab_name, is_avail in sorted(avail_labs.items()):
            var = ctk.BooleanVar(value=is_avail)
            self._labeler_vars[lab_name] = var
            color = theme.TEXT_PRIMARY if is_avail else theme.TEXT_MUTED
            chip = ctk.CTkCheckBox(
                lab_row, text=lab_name, variable=var,
                font=theme.FONT_SMALL, text_color=color,
                checkbox_width=16, checkbox_height=16,
                checkmark_color=theme.ACCENT_BLUE,
                fg_color=theme.ACCENT_BLUE,
                state="normal" if is_avail else "disabled",
            )
            chip.pack(side="left", padx=4)

        vote_row = ctk.CTkFrame(inner, fg_color="transparent")
        vote_row.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(vote_row, text="Voto:",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                     width=60).pack(side="left")
        self._vote_var = ctk.StringVar(value="consensus")  # F6: verificación cruzada
        ctk.CTkOptionMenu(
            vote_row, values=["highest_conf", "majority", "consensus"],
            variable=self._vote_var,
            fg_color=theme.BG_TERTIARY, button_color=theme.ACCENT_BLUE,
            text_color=theme.TEXT_PRIMARY, width=140,
        ).pack(side="left", padx=4)

        sliders_f = ctk.CTkFrame(inner, fg_color="transparent")
        sliders_f.pack(fill="x", padx=10, pady=4)
        sliders_f.columnconfigure(1, weight=1)

        def _make_mini_slider(row, label, lo, hi, default, nsteps):
            ctk.CTkLabel(sliders_f, text=label, font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED, width=110,
                         anchor="w").grid(row=row, column=0, sticky="w")
            lbl = ctk.CTkLabel(sliders_f, text=f"{default:.2f}",
                               font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, width=38)
            lbl.grid(row=row, column=2, padx=(4, 0))
            sl = ctk.CTkSlider(sliders_f, from_=lo, to=hi, number_of_steps=nsteps,
                               progress_color=theme.ACCENT_ORANGE,
                               button_color=theme.ACCENT_ORANGE,
                               button_hover_color=theme.ACCENT_ORANGE_HOVER)
            sl.set(default)
            sl.grid(row=row, column=1, sticky="ew", padx=4)
            sl.configure(command=lambda v, l=lbl: l.configure(text=f"{float(v):.2f}"))
            return sl

        self._min_quality_slider = _make_mini_slider(0, "Min quality:", 0.0, 1.0, 0.18, 100)
        self._min_label_conf_slider = _make_mini_slider(1, "Min label conf:", 0.0, 1.0, 0.0, 100)

        dbg_row = ctk.CTkFrame(inner, fg_color="transparent")
        dbg_row.pack(fill="x", padx=10, pady=(2, 4))
        ctk.CTkLabel(dbg_row, text="Debug overlay PNG",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(side="left")
        self._debug_overlay_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(dbg_row, text="", variable=self._debug_overlay_var,
                      onvalue=True, offvalue=False,
                      progress_color=theme.ACCENT_BLUE,
                      button_color=theme.ACCENT_BLUE_HOVER, width=40).pack(side="right")

        ctk.CTkButton(
            inner, text="✨ Auto-config (activar todo lo disponible)",
            command=self._on_auto_config,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            text_color="white", font=theme.FONT_SMALL, height=28,
            corner_radius=6,
        ).pack(fill="x", padx=10, pady=(0, 4))

        self._compare_btn = ctk.CTkButton(
            inner, text="🔬 Comparar estrategias de segmentación",
            command=self._on_compare_strategies,
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            text_color="white", font=theme.FONT_SMALL, height=28,
            corner_radius=6,
        )
        self._compare_btn.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkButton(
            inner, text="🧹 Liberar modelos de memoria",
            command=self._on_clear_models,
            fg_color=theme.BG_SECONDARY, hover_color=theme.BORDER,
            text_color=theme.TEXT_SECONDARY, font=theme.FONT_SMALL, height=28,
            corner_radius=6,
        ).pack(fill="x", padx=10, pady=(0, 8))

    def _toggle_pipeline_panel(self) -> None:
        self._pipeline_collapsed = not self._pipeline_collapsed
        if self._pipeline_collapsed:
            self._pipeline_frame.pack_forget()
            self._pipeline_toggle_btn.configure(text="▶")
        else:
            self._pipeline_frame.pack(fill="x", padx=12, pady=(0, 6))
            self._pipeline_toggle_btn.configure(text="▼")

    def _on_auto_config(self) -> None:
        """Activa pipeline + todos los detectores y labelers disponibles, fusion=union."""
        from core.inkcore import glyph_detectors, glyph_labelers
        avail_dets = glyph_detectors.get_available()
        avail_labs = glyph_labelers.get_available()
        with contextlib.suppress(Exception):
            self._use_pipeline_var.set(True)
        for name, is_avail in avail_dets.items():
            var = self._detector_vars.get(name)
            if var is not None and is_avail:
                var.set(True)
        for name, is_avail in avail_labs.items():
            var = self._labeler_vars.get(name)
            if var is not None and is_avail:
                var.set(True)
        try:
            self._fusion_var.set("union")
            self._vote_var.set("highest_conf")
        except Exception:
            pass
        with contextlib.suppress(Exception):
            self._refresh_pipeline_chip()
        n_d = sum(1 for v in avail_dets.values() if v)
        n_l = sum(1 for v in avail_labs.values() if v)
        self.toast(f"Auto-config: {n_d} detector(es) + {n_l} labeler(s) activos", "success")

    def _on_compare_strategies(self) -> None:
        import threading

        from core.inkcore.extractor import ExtractionOptions

        if not getattr(self, "_image_path", None):
            self.toast("Carga una imagen primero", "warning")
            return
        ref = self._ref_text.get("1.0", "end").strip()
        if not ref:
            self.toast("Escribe el texto de referencia", "warning")
            return

        opts = ExtractionOptions(
            remove_lines=self._remove_lines_var.get(),
            brightness=float(self._brightness_slider.get()),
            contrast=float(self._contrast_slider.get()),
            rotation_deg=float(self._rotation_slider.get()),
        )
        # Deshabilitar el botón mientras corre el thread (mismo motivo que
        # _show_preprocess_preview: clicks repetidos lanzan threads paralelos
        # que sobrescriben results y compiten por la misma ventana modal).
        with contextlib.suppress(AttributeError, Exception):
            self._compare_btn.configure(state="disabled", text="Comparando…")
        self.toast("Comparando estrategias…", "info")
        image_path = self._image_path

        def _restore():
            with contextlib.suppress(AttributeError, Exception):
                self._compare_btn.configure(
                    state="normal",
                    text="🔬 Comparar estrategias de segmentación",
                )

        def worker():
            try:
                results = self._pipeline.extractor.compare_strategies(
                    image_path, ref, opts,
                )
            except Exception as exc:
                logger.error("compare_strategies error: %s", exc, exc_info=True)
                results = {"_meta": {"error": str(exc)}}
            def _done():
                _restore()
                self._show_strategy_results(results)
            with contextlib.suppress(Exception):
                self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

    def _show_strategy_results(self, results: dict) -> None:
        if not self.winfo_exists():
            return
        meta = results.pop("_meta", {}) if isinstance(results, dict) else {}
        if "error" in meta:
            self.toast(f"Comparación falló: {meta['error']}", "error")
            return

        win = ctk.CTkToplevel(self)
        win.title("Comparación de estrategias de segmentación")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("720x460")

        header = (f"Línea {meta.get('line_index', 0) + 1}/{meta.get('line_count', '?')} "
                  f"({meta.get('line_w', 0)}×{meta.get('line_h', 0)}px · "
                  f"{meta.get('n_chars', 0)} chars)  ref: \"{meta.get('ref_line', '')[:60]}\"")
        ctk.CTkLabel(
            win, text=header, font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY, justify="left",
        ).pack(anchor="w", padx=14, pady=(10, 6))

        table = ctk.CTkScrollableFrame(win, fg_color=theme.BG_SECONDARY)
        table.pack(fill="both", expand=True, padx=12, pady=4)

        # Cabecera de tabla
        hdr = ctk.CTkFrame(table, fg_color=theme.BG_TERTIARY)
        hdr.pack(fill="x", padx=2, pady=(2, 4))
        for col, w in [("Estrategia", 200), ("Avg", 70), ("Min", 70),
                       ("Max", 70), ("# glifos", 70), ("Nota", 200)]:
            ctk.CTkLabel(
                hdr, text=col, font=theme.FONT_SMALL,
                text_color=theme.TEXT_PRIMARY, width=w, anchor="w",
            ).pack(side="left", padx=4, pady=4)

        # Ordenar por avg_quality desc
        rows = sorted(
            results.items(),
            key=lambda kv: kv[1].get("avg_quality", 0.0),
            reverse=True,
        )
        best_name = rows[0][0] if rows else None
        for name, data in rows:
            row = ctk.CTkFrame(
                table,
                fg_color=theme.ACCENT_GREEN if name == best_name else "transparent",
            )
            row.pack(fill="x", padx=2, pady=1)
            avg = data.get("avg_quality", 0.0)
            mn = data.get("min_quality", 0.0)
            mx = data.get("max_quality", 0.0)
            cnt = data.get("glyph_count", 0)
            note = data.get("note", "") or data.get("error", "")
            txt_color = "white" if name == best_name else theme.TEXT_PRIMARY
            for val, w in [(name, 200), (f"{avg:.3f}", 70), (f"{mn:.3f}", 70),
                           (f"{mx:.3f}", 70), (str(cnt), 70), (note[:30], 200)]:
                ctk.CTkLabel(
                    row, text=val, font=theme.FONT_SMALL,
                    text_color=txt_color, width=w, anchor="w",
                ).pack(side="left", padx=4, pady=3)

        ctk.CTkLabel(
            win,
            text="La fila resaltada es la estrategia con mejor calidad promedio.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(pady=(4, 2))
        ctk.CTkButton(
            win, text="Cerrar", command=win.destroy,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY, width=100,
        ).pack(pady=(0, 12))

    def _on_clear_models(self) -> None:
        from core.inkcore.model_cache import ModelCache
        keys = ModelCache.loaded_keys()
        ModelCache.clear()
        try:
            import psutil
            proc = psutil.Process()
            rss_mb = proc.memory_info().rss / 1024 / 1024
            self.toast(f"Modelos liberados ({len(keys)}) — RAM: {rss_mb:.0f} MB", "info")
        except ImportError:
            self.toast(f"{len(keys)} modelo(s) eliminados de memoria", "info")

    def _get_pipeline_config(self):
        from core.inkcore.extraction_pipeline import PipelineConfig
        dets = [name for name, var in self._detector_vars.items() if var.get()]
        labs = [name for name, var in self._labeler_vars.items() if var.get()]
        return PipelineConfig(
            detectors=dets or ["classic_cv"],
            detector_fusion=self._fusion_var.get(),
            labelers=labs,
            labeler_voting=self._vote_var.get(),
            min_quality=float(self._min_quality_slider.get()),
            min_label_confidence=float(self._min_label_conf_slider.get()),
            debug_overlay=bool(self._debug_overlay_var.get()),
        )

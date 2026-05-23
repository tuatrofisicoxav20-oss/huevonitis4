"""PipelinePanelMixin — panel colapsable del pipeline ensemble para ExtractorTab."""
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
        self._use_pipeline_var = ctk.BooleanVar(value=False)
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
        for det_name, is_avail in sorted(avail_dets.items()):
            var = ctk.BooleanVar(value=(det_name == "classic_cv"))
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
        for lab_name, is_avail in sorted(avail_labs.items()):
            var = ctk.BooleanVar(value=False)
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
        self._vote_var = ctk.StringVar(value="highest_conf")
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

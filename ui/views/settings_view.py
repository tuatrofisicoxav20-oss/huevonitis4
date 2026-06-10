import contextlib
import json
import logging
import os
import tempfile

import customtkinter as ctk

import config
from ui import theme
from ui.views.base_view import BaseView

logger = logging.getLogger(__name__)


from ui.views.settings_view_cache import SettingsCacheMixin  # noqa: E402
from ui.views.settings_view_diagnostics import SettingsDiagnosticsMixin  # noqa: E402


class SettingsView(SettingsDiagnosticsMixin, SettingsCacheMixin, BaseView):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._settings: dict = self._load_settings()
        self._field_widgets: dict = {}
        self._build()

    def on_show(self):
        """Refresca los valores de los dropdowns con el estado live de config."""
        self._settings = self._load_settings()
        for key, (ftype, w) in self._field_widgets.items():
            if ftype == "menu":
                live_val = self._settings.get(key, "")
                try:
                    vals = w.cget("values")
                    if live_val and live_val in vals:
                        w.set(live_val)
                except Exception:
                    pass

    def _load_settings(self) -> dict:
        # Base con los valores live de config (para que los dropdowns muestren el backend activo)
        _extra = list(getattr(config, "GLYPH_DETECTORS_EXTRA", []) or [])
        base: dict = {
            "ocr_backend": config.OCR_BACKEND,
            "glyph_detector": config.GLYPH_DETECTOR,
            # Fase 2 — fusión multi-detector. El _ui es un single-select (un solo
            # detector neuronal extra); se convierte a la lista persistida al guardar.
            "glyph_detector_fusion": getattr(config, "GLYPH_DETECTOR_FUSION", "cascade"),
            "glyph_detectors_extra_ui": _extra[0] if _extra else "(ninguno)",
            "trocr_model": getattr(config, "TROCR_MODEL", "microsoft/trocr-base-handwritten"),
        }
        if config.SETTINGS_FILE.exists():
            try:
                with open(config.SETTINGS_FILE, encoding="utf-8") as f:
                    base.update(json.load(f))
            except Exception:
                pass
        return base

    def _save_settings(self):
        config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=config.SETTINGS_FILE.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, config.SETTINGS_FILE)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=24, pady=20)

        ctk.CTkLabel(scroll, text="Configuración", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 20))

        self._section(scroll, "🎨 Apariencia", [
            ("Tema", "theme", "menu", ["Oscuro", "Claro", "Sistema"]),
        ])
        # Backends disponibles (solo los que tienen las dependencias instaladas)
        try:
            from core.ocr.engine import OCREngine
            _ocr_avail = {k for k, v in OCREngine.available_backends().items() if v}
        except Exception:
            _ocr_avail = {"tesseract"}
        try:
            from core.inkcore import glyph_detectors as _gd
            _det_avail = {k for k, v in _gd.get_available().items() if v}
        except Exception:
            _det_avail = {"classic_cv"}

        ocr_opts = sorted(_ocr_avail) or ["tesseract"]
        det_opts = sorted(_det_avail) or ["classic_cv"]
        # Fase 2 — detectores neuronales disponibles para fusionar con classic_cv.
        neural_opts = ["(ninguno)", *sorted(_det_avail - {"classic_cv"})]

        self._section(scroll, "✍️ InkCore", [
            ("Ruta de Tesseract", "tesseract_path", "entry", None),
            ("Calidad mínima de glifo (0-1)", "min_glyph_quality", "entry", None),
            ("Backend OCR", "ocr_backend", "menu", ocr_opts),
            ("Detector de glifos", "glyph_detector", "menu", det_opts),
            ("Detector neuronal extra", "glyph_detectors_extra_ui", "menu", neural_opts),
            ("Fusión de detectores", "glyph_detector_fusion", "menu",
             ["cascade", "union", "intersection"]),
            ("Modelo TrOCR (letra manuscrita)", "trocr_model", "menu", [
                "microsoft/trocr-base-handwritten",
                "microsoft/trocr-small-handwritten",
                "microsoft/trocr-large-handwritten",
            ]),
        ])

        # Tooltip para backends opcionales no instalados
        try:
            from core.ocr.engine import OCREngine as _OCREngine
            all_backends = _OCREngine.available_backends()
            missing = [f"{k}" for k, v in all_backends.items() if not v]
            if missing:
                hint_card = self.card_frame(scroll)
                hint_card.pack(fill="x", pady=(0, 8))
                ctk.CTkLabel(
                    hint_card,
                    text="💡 Backends no instalados: " + ", ".join(missing)
                    + "\nVer requirements-optional.txt para instalar más opciones.",
                    font=theme.FONT_BODY,
                    text_color=theme.TEXT_MUTED,
                    justify="left",
                ).pack(anchor="w", padx=16, pady=(8, 12))
        except Exception:
            pass
        self._section(scroll, "💼 Negocio", [
            ("Nombre de tu negocio", "business_name", "entry", None),
            ("Precio base por página (MXN)", "base_price", "entry", None),
        ])
        self._section(scroll, "💾 Datos", [
            ("Intervalo de autosave (segundos)", "autosave_interval", "entry", None),
        ])

        self._build_cache_section(scroll)
        self._build_diagnostics_section(scroll)

        self.primary_button(scroll, "💾 Guardar Configuración", self._apply_save, 200).pack(pady=20, anchor="w")

        about = self.card_frame(scroll)
        about.pack(fill="x", pady=8)
        ctk.CTkLabel(about, text="Acerca de Huevonitis 4",
                     font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(about, text=f"Versión {config.VERSION}",
                     font=theme.FONT_BODY, text_color=theme.TEXT_SECONDARY).pack(anchor="w", padx=16)
        ctk.CTkLabel(about,
                     text="App de escritorio para producir apuntes con tu letra real\ny gestionar trabajos escolares freelance.",
                     font=theme.FONT_BODY, text_color=theme.TEXT_MUTED, justify="left").pack(anchor="w", padx=16, pady=(4, 12))

    def _section(self, parent, title: str, fields: list):
        card = self.card_frame(parent)
        card.pack(fill="x", pady=8)

        ctk.CTkLabel(card, text=title, font=theme.FONT_SUBHEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(12, 8))

        for label, key, ftype, options in fields:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(row, text=label, font=theme.FONT_BODY,
                         text_color=theme.TEXT_SECONDARY, width=220, anchor="w").pack(side="left")
            if ftype == "entry":
                w = ctk.CTkEntry(row, fg_color=theme.BG_TERTIARY,
                                 text_color=theme.TEXT_PRIMARY, width=200)
                w.insert(0, str(self._settings.get(key, "")))
                w.pack(side="left")
            elif ftype == "menu":
                w = ctk.CTkOptionMenu(row, values=options, fg_color=theme.BG_TERTIARY,
                                      button_color=theme.ACCENT_BLUE, text_color=theme.TEXT_PRIMARY,
                                      width=160)
                current = self._settings.get(key, options[0])
                if current not in options:
                    current = options[0]
                w.set(current)
                w.pack(side="left")
            elif ftype == "toggle":
                var = ctk.BooleanVar(value=bool(self._settings.get(key, False)))
                w = ctk.CTkSwitch(row, variable=var, text="",
                                  progress_color=theme.ACCENT_BLUE)
                w.pack(side="left")
                w._var = var
            self._field_widgets[key] = (ftype, w)

        ctk.CTkFrame(card, height=1, fg_color=theme.BORDER).pack(fill="x", padx=12, pady=(4, 12))

    def _notify_backends(self, prev_ocr: str, prev_det: str) -> None:
        """Actualiza instancias vivas de OCREngine y GlyphExtractor sin reiniciar la app."""
        new_ocr = self._settings.get("ocr_backend", prev_ocr)
        new_det = self._settings.get("glyph_detector", prev_det)
        tess_changed = bool(self._settings.get("tesseract_path"))

        # StudyView._ocr: cambiar backend o recargar cmd de Tesseract en caliente
        if new_ocr != prev_ocr or tess_changed:
            try:
                study = self.app._views.get("study")
                if study is not None and hasattr(study, "_ocr"):
                    study._ocr.switch_backend(new_ocr)
            except Exception as exc:
                logger.warning("No se pudo actualizar OCREngine en StudyView: %s", exc)

        # El detector de glifos (config.GLYPH_DETECTOR) lo relee la Captura masiva
        # en cada extracción (construye un GlyphExtractionPipeline fresco), así que
        # el cambio aplica solo; ya no hay extractor que recargar.

    def _apply_save(self):
        # Guardar valores previos ANTES de leer los widgets (para comparar después)
        prev_ocr = self._settings.get("ocr_backend", config.OCR_BACKEND)
        prev_det = self._settings.get("glyph_detector", config.GLYPH_DETECTOR)

        errors = []
        for key, (ftype, w) in self._field_widgets.items():
            if ftype == "entry":
                val = w.get().strip()
                if key in ("base_price",):
                    try:
                        float(val)
                    except ValueError:
                        errors.append(f"'{key}' debe ser un número")
                        continue
                elif key in ("autosave_interval",):
                    try:
                        v = int(val)
                        if v <= 0:
                            raise ValueError
                    except ValueError:
                        errors.append(f"'{key}' debe ser un entero positivo")
                        continue
                elif key == "min_glyph_quality":
                    try:
                        v = float(val)
                        if not 0.0 <= v <= 1.0:
                            raise ValueError
                    except ValueError:
                        errors.append(f"'{key}' debe ser un número entre 0 y 1")
                        continue
                self._settings[key] = val
            elif ftype == "menu":
                self._settings[key] = w.get()
            elif ftype == "toggle":
                self._settings[key] = w._var.get()

        if errors:
            self.toast("Error: " + "; ".join(errors), "error")
            return

        # Fase 2 — convertir el single-select de detector neuronal extra a la
        # lista persistida que lee config.GLYPH_DETECTORS_EXTRA.
        extra_ui = self._settings.get("glyph_detectors_extra_ui", "(ninguno)")
        self._settings["glyph_detectors_extra"] = (
            [] if extra_ui in ("(ninguno)", "") else [extra_ui]
        )

        theme_val = self._settings.get("theme", "Oscuro")
        mode_map = {"Oscuro": "dark", "Claro": "light", "Sistema": "system"}
        ctk_mode = mode_map.get(theme_val, "dark")
        ctk.set_appearance_mode(ctk_mode)

        self._save_settings()
        _apply_settings_to_config(self._settings)
        self._notify_backends(prev_ocr, prev_det)
        self.toast("Configuración guardada — reinicia la app para aplicar el tema", "success")


def _apply_settings_to_config(settings: dict) -> None:
    """Apply saved settings values back to config module globals."""
    val = settings.get("base_price", "")
    with contextlib.suppress(ValueError, TypeError):
        config.BASE_PRICE_PER_PAGE_MXN = float(val)

    val = settings.get("autosave_interval", "")
    with contextlib.suppress(ValueError, TypeError):
        v = int(val)
        if v > 0:
            config.AUTOSAVE_INTERVAL_MS = v * 1000

    val = settings.get("tesseract_path", "")
    if val:
        config.TESSERACT_CMD = val

    val = settings.get("ocr_backend", "")
    if val and isinstance(val, str):
        config.OCR_BACKEND = val

    val = settings.get("glyph_detector", "")
    if val and isinstance(val, str):
        config.GLYPH_DETECTOR = val

    # Fase 2 — fusión multi-detector. Inválido → se ignora (queda el default).
    val = settings.get("glyph_detector_fusion", "")
    if isinstance(val, str) and val in ("union", "intersection", "cascade"):
        config.GLYPH_DETECTOR_FUSION = val
    val = settings.get("glyph_detectors_extra")
    if isinstance(val, list):
        config.GLYPH_DETECTORS_EXTRA = [x for x in val if isinstance(x, str) and x]
    # Fase 3 — modelo de TrOCR (sólo valores válidos conocidos).
    val = settings.get("trocr_model", "")
    if isinstance(val, str) and val in config._VALID_TROCR_MODELS:
        config.TROCR_MODEL = val

    with contextlib.suppress(ValueError, TypeError):
        v = float(settings.get("min_glyph_quality", ""))
        if 0.0 <= v <= 1.0:
            config.MIN_GLYPH_QUALITY = v


def load_and_apply_settings() -> None:
    """Call at startup to override config defaults from SETTINGS_FILE."""
    if not config.SETTINGS_FILE.exists():
        return
    try:
        with open(config.SETTINGS_FILE, encoding="utf-8") as f:
            settings = json.load(f)
        _apply_settings_to_config(settings)
    except Exception:
        pass


def get_backend_install_hints() -> dict[str, str]:
    """Devuelve {nombre: hint_de_instalación} para backends no disponibles."""
    hints = {}
    try:
        from core.ocr import backends as _backends
        for name, cls in _backends.REGISTRY.items():
            if not cls.available:
                hints[name] = cls().install_hint()
    except Exception:
        pass
    return hints

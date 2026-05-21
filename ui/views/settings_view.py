import json
import os
import tempfile

import customtkinter as ctk

import config
from ui import theme
from ui.views.base_view import BaseView


class SettingsView(BaseView):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._settings: dict = self._load_settings()
        self._field_widgets: dict = {}
        self._build()

    def _load_settings(self) -> dict:
        if config.SETTINGS_FILE.exists():
            try:
                with open(config.SETTINGS_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_settings(self):
        config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=config.SETTINGS_FILE.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, config.SETTINGS_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=24, pady=20)

        ctk.CTkLabel(scroll, text="Configuración", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", pady=(0, 20))

        # "Claro" removed — not implemented (see docs/KNOWN_ISSUES.md)
        self._section(scroll, "🎨 Apariencia", [
            ("Tema", "theme", "menu", ["Oscuro", "Sistema"]),
        ])
        self._section(scroll, "✍️ InkCore", [
            ("Ruta de Tesseract", "tesseract_path", "entry", None),
            ("Calidad mínima de glifo (0-1)", "min_glyph_quality", "entry", None),
        ])
        self._section(scroll, "💼 Negocio", [
            ("Nombre de tu negocio", "business_name", "entry", None),
            ("Precio base por página (MXN)", "base_price", "entry", None),
        ])
        self._section(scroll, "💾 Datos", [
            ("Intervalo de autosave (segundos)", "autosave_interval", "entry", None),
        ])

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

    def _apply_save(self):
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

        theme_val = self._settings.get("theme", "Oscuro")
        mode_map = {"Oscuro": "dark", "Sistema": "system"}
        ctk.set_appearance_mode(mode_map.get(theme_val, "dark"))

        self._save_settings()
        _apply_settings_to_config(self._settings)
        self.toast("Configuración guardada", "success")


def _apply_settings_to_config(settings: dict) -> None:
    """Apply saved settings values back to config module globals."""
    val = settings.get("base_price", "")
    try:
        config.BASE_PRICE_PER_PAGE_MXN = float(val)
    except (ValueError, TypeError):
        pass

    val = settings.get("autosave_interval", "")
    try:
        v = int(val)
        if v > 0:
            config.AUTOSAVE_INTERVAL_MS = v * 1000
    except (ValueError, TypeError):
        pass

    val = settings.get("tesseract_path", "")
    if val:
        config.TESSERACT_CMD = val


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

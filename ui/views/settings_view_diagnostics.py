"""SettingsDiagnosticsMixin — sección Diagnóstico + Doctor en Settings.

Separado de settings_view.py para mantener cada archivo manejable.
"""
import logging
import os
import re

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)


class SettingsDiagnosticsMixin:
    """Sección de diagnóstico: reporte de eventos y `tools/doctor.py`."""

    def _build_diagnostics_section(self, parent):
        card = self.card_frame(parent)
        card.pack(fill="x", pady=8)

        ctk.CTkLabel(card, text="🔍 Diagnóstico", font=theme.FONT_SUBHEADING,
                     text_color=theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            card,
            text="Muestra errores recientes, operaciones lentas y eventos frecuentes de la sesión.",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(anchor="w", padx=16, pady=(0, 12), fill="x")

        ctk.CTkButton(
            btn_row, text="📊 Ver reporte de diagnóstico",
            command=self._show_diagnostics_report,
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_BODY, height=32,
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="🩺 Ejecutar Doctor",
            command=self._show_doctor_report,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.FONT_BODY, height=32,
        ).pack(side="left", padx=8)

        ctk.CTkFrame(card, height=1, fg_color=theme.BORDER).pack(fill="x", padx=12, pady=(0, 0))

    def _show_doctor_report(self):
        """Lanza tools/doctor.py en un subproceso y muestra la salida."""
        import subprocess
        import sys
        import threading
        from pathlib import Path

        win = ctk.CTkToplevel(self)
        win.title("🩺 Doctor — Huevonitis 4")
        win.geometry("760x600")
        win.grab_set()

        txt = ctk.CTkTextbox(win, font=theme.FONT_MONO, fg_color=theme.BG_TERTIARY,
                             text_color=theme.TEXT_PRIMARY)
        txt.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        txt.insert("0.0", "Ejecutando doctor…\n")
        txt.configure(state="disabled")

        def _run():
            doctor = Path(__file__).resolve().parent.parent.parent / "tools" / "doctor.py"
            try:
                result = subprocess.run(
                    [sys.executable, str(doctor)],
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ, "NO_COLOR": "1"},
                )
                output = result.stdout
                if result.stderr:
                    output += "\n--- stderr ---\n" + result.stderr
            except subprocess.TimeoutExpired:
                output = "⚠ Timeout — doctor tardó más de 30s en responder."
            except Exception as exc:
                output = f"⚠ No se pudo ejecutar doctor.py: {exc}"

            def _update():
                txt.configure(state="normal")
                txt.delete("0.0", "end")
                clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
                txt.insert("0.0", clean)
                txt.configure(state="disabled")
            self.after(0, _update)

        threading.Thread(target=_run, daemon=True).start()

        ctk.CTkButton(win, text="Cerrar", command=win.destroy,
                      fg_color=theme.BG_SECONDARY, hover_color=theme.BORDER,
                      font=theme.FONT_BODY, width=120).pack(pady=(0, 12))

    def _show_diagnostics_report(self):
        from core.diagnostics import diagnostics as _diag

        win = ctk.CTkToplevel(self)
        win.title("Diagnóstico — Huevonitis 4")
        win.geometry("720x560")
        win.grab_set()

        txt = ctk.CTkTextbox(win, font=theme.FONT_MONO, fg_color=theme.BG_TERTIARY,
                             text_color=theme.TEXT_PRIMARY)
        txt.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        txt.insert("0.0", _diag.get_report())
        txt.configure(state="disabled")

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 12))

        def _copy():
            txt.configure(state="normal")
            report = txt.get("0.0", "end")
            txt.configure(state="disabled")
            self.clipboard_clear()
            self.clipboard_append(report)
            self.toast("Reporte copiado al portapapeles", "info")

        def _clear():
            _diag.clear()
            win.destroy()
            self.toast("Eventos de diagnóstico limpiados", "info")

        ctk.CTkButton(btn_row, text="🗑 Limpiar eventos", command=_clear,
                      fg_color=theme.ACCENT_RED, hover_color="#b03030",
                      font=theme.FONT_BODY, width=160).pack(side="left")
        ctk.CTkButton(btn_row, text="📋 Copiar", command=_copy,
                      fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
                      font=theme.FONT_BODY, width=120).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="Cerrar", command=win.destroy,
                      fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
                      text_color=theme.TEXT_SECONDARY,
                      font=theme.FONT_BODY, width=100).pack(side="right")

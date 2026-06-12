"""Spinner orbital (U8/M3) — dos arcos en contrafase sobre UN tk.Canvas.

Sustituye el spinner de texto braille del statusbar. Respeta el nivel
global de motion: con Reducidas/Off no rota (queda un anillo estático,
que sigue siendo feedback de trabajo en curso). ~30 fps vía after(33),
cancelable, y para en cuanto el widget muere o se llama stop().
"""
import contextlib
import tkinter as tk

from ui import motion, theme


class OrbitalSpinner(tk.Canvas):
    """Canvas chico con anillo ámbar exterior y cian interior contrarrotando."""

    def __init__(self, parent, size: int = 16, **kwargs):
        super().__init__(parent, width=size, height=size,
                         highlightthickness=0, bd=0,
                         bg=theme.BG_PRIMARY, **kwargs)
        self._size = size
        self._angle = 0
        self._job = None
        pad = 2
        self._outer = self.create_arc(
            pad, pad, size - pad, size - pad, start=0, extent=120,
            style="arc", outline=theme.ACCENT_PRIMARY, width=2)
        pad2 = pad + 4
        self._inner = self.create_arc(
            pad2, pad2, size - pad2, size - pad2, start=180, extent=100,
            style="arc", outline=theme.ACCENT_CYAN, width=2)

    def start(self) -> None:
        if self._job is not None:
            return
        if not motion.should_animate("motion"):
            return  # anillo estático: hay indicador sin animación
        self._tick()

    def stop(self) -> None:
        if self._job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._job)
            self._job = None

    def _tick(self) -> None:
        self._job = None
        try:
            if not self.winfo_exists():
                return
            self._angle = (self._angle + 14) % 360
            self.itemconfigure(self._outer, start=self._angle)
            self.itemconfigure(self._inner, start=(180 - self._angle) % 360)
        except Exception:
            return
        self._job = self.after(33, self._tick)

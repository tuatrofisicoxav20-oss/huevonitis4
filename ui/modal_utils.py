"""Utilidades para modales CTkToplevel.

GOTCHA (Wayland/XWayland + Tk): grab_set() truena con "grab failed: window
not viewable" si se llama justo después de crear el Toplevel — el WM mapea la
ventana de forma ASÍNCRONA y en ese punto todavía no es visible. safe_grab
aplica transient+lift y difiere el grab con reintentos hasta que la ventana
exista de verdad (el patrón de OCRReviewDialog, centralizado).
"""
from __future__ import annotations

import contextlib


def safe_grab(win, parent=None, retries: int = 8) -> None:
    """transient + lift + grab_set diferido (reintenta mientras no sea visible)."""
    if parent is not None:
        with contextlib.suppress(Exception):
            win.transient(parent.winfo_toplevel())
    with contextlib.suppress(Exception):
        win.lift()

    def _try(remaining: int) -> None:
        try:
            win.grab_set()
        except Exception:
            if remaining > 0:
                with contextlib.suppress(Exception):
                    win.after(120, _try, remaining - 1)

    with contextlib.suppress(Exception):
        win.after(120, _try, retries)

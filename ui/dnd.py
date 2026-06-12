"""Drag & drop opcional (U9/F7) — tkinterdnd2 con fallback COMPLETO.

tkinterdnd2 es la ÚNICA dependencia nueva permitida del overhaul y es
opcional: si no está instalada (o el paquete Tcl tkdnd no carga), todo
sigue funcionando por botón. enable_file_drop() devuelve False en ese
caso y no toca nada.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_available: bool | None = None


def dnd_available() -> bool:
    global _available
    if _available is None:
        try:
            import tkinterdnd2  # noqa: F401
            _available = True
        except ImportError:
            _available = False
            logger.info("tkinterdnd2 no instalado — drag&drop deshabilitado (opcional)")
    return _available


def enable_file_drop(widget, on_files, highlight=None, unhighlight=None) -> bool:
    """Registra `widget` como zona de drop de archivos.

    on_files(list[str]) recibe las rutas soltadas; highlight/unhighlight
    (opcionales) se llaman al entrar/salir el arrastre (p.ej. borde ámbar).
    Devuelve True si quedó habilitado.
    """
    if not dnd_available():
        return False
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
        # Cargar el paquete Tcl tkdnd en el intérprete de la app (la raíz es
        # ctk.CTk normal, no TkinterDnD.Tk — _require lo inyecta igual).
        TkinterDnD._require(widget)
        widget.drop_target_register(DND_FILES)

        def _drop(event):
            try:
                paths = widget.tk.splitlist(event.data)
            except Exception:
                paths = [event.data]
            if unhighlight is not None:
                unhighlight()
            if paths:
                on_files(list(paths))
            return "copy"

        widget.dnd_bind("<<Drop>>", _drop)
        if highlight is not None:
            widget.dnd_bind("<<DropEnter>>", lambda _e: (highlight(), "copy")[1])
        if unhighlight is not None:
            widget.dnd_bind("<<DropLeave>>", lambda _e: (unhighlight(), "copy")[1])
        return True
    except Exception as exc:
        logger.info("drag&drop no disponible (%s) — fallback por botón", exc)
        return False

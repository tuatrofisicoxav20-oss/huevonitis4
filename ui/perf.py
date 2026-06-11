"""Instrumentación ligera de rendimiento (U0).

Se activa con la env var HUEVONITIS_PERF=1; apagada el costo es un if por
llamada. Loggea al logger "huevonitis4.perf":

  • measure("nombre") — decorador Y context manager: duración de un bloque
    si supera el umbral (50 ms).
  • mark()/elapsed_ms() — timer de arranque: main.py marca el inicio y
    note_navigate() reporta "arranque: X ms" al completarse el primer
    navigate("dashboard").
  • widget_count(root) — conteo recursivo de widgets; note_navigate() lo
    loggea en cada navegación.
"""
from __future__ import annotations

import contextlib
import functools
import logging
import os
import time

logger = logging.getLogger("huevonitis4.perf")

ENABLED = os.environ.get("HUEVONITIS_PERF") == "1"
THRESHOLD_MS = 50.0

_marks: dict[str, float] = {}
_startup_reported = False


def mark(name: str) -> None:
    """Registra el instante actual bajo `name` (no-op si perf está apagado)."""
    if ENABLED:
        _marks[name] = time.perf_counter()


def elapsed_ms(name: str) -> float | None:
    """Milisegundos desde mark(name); None si no existe la marca."""
    t0 = _marks.get(name)
    if t0 is None:
        return None
    return (time.perf_counter() - t0) * 1000.0


class _Measure:
    """Uso dual: `@measure("x")` o `with measure("x"):`."""

    __slots__ = ("_t0", "name")

    def __init__(self, name: str):
        self.name = name
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        dur_ms = (time.perf_counter() - self._t0) * 1000.0
        if dur_ms >= THRESHOLD_MS:
            logger.info("%s: %.0f ms", self.name, dur_ms)
        return False

    def __call__(self, fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not ENABLED:
                return fn(*args, **kwargs)
            with _Measure(self.name):
                return fn(*args, **kwargs)
        return wrapper


def measure(name: str):
    """Decorador/context manager que loggea la duración si supera 50 ms.

    Como context manager SOLO debe usarse si ENABLED (el decorador ya hace
    el guard solo); el patrón típico es:

        @measure("refresh banco")
        def _do_refresh(...): ...
    """
    if not ENABLED:
        # Context manager nulo + decorador transparente.
        class _Noop:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def __call__(self, fn):
                return fn

        return _Noop()
    return _Measure(name)


def widget_count(root) -> int:
    """Cuenta widgets Tk recursivamente bajo `root` (incluyéndolo)."""
    try:
        children = root.winfo_children()
    except Exception:
        return 1
    return 1 + sum(widget_count(c) for c in children)


def note_navigate(app, view_id: str) -> None:
    """Hook de app.navigate(): loggea conteo de widgets y, la primera vez
    que se completa el dashboard, el tiempo total de arranque."""
    global _startup_reported
    if not ENABLED:
        return
    if not _startup_reported and view_id == "dashboard":
        _startup_reported = True
        ms = elapsed_ms("startup")
        if ms is not None:
            logger.info("arranque: %.0f ms", ms)
    with measure(f"widget_count({view_id})"):
        n = widget_count(app)
    logger.info("widgets tras navigate(%s): %d", view_id, n)


def debounce(widget, ms: int, fn):
    """Devuelve un callable que difiere `fn` hasta que pasen `ms` sin nuevas
    llamadas (cancela el after anterior). Acepta y descarta args (sirve como
    callback de eventos/traces). El job se agenda en `widget`."""
    state = {"job": None}

    def _call(*_args, **_kwargs):
        if state["job"] is not None:
            with contextlib.suppress(Exception):
                widget.after_cancel(state["job"])

        def _fire():
            state["job"] = None
            fn()

        try:
            state["job"] = widget.after(ms, _fire)
        except Exception:
            fn()

    return _call

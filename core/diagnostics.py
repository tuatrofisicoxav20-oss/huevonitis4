"""
DiagnosticsCollector — sistema de diagnóstico para Huevonitis 4.

Registra eventos con timestamp en memoria y en archivo de log.
Proporciona resumen de errores, operaciones lentas y eventos frecuentes.
"""
import contextlib
import functools
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LOG_DIR = Path.home() / ".local" / "share" / "huevonitis4"
_LOG_FILE = _LOG_DIR / "diagnostics.log"


def _ensure_log_dir():
    with contextlib.suppress(Exception):
        _LOG_DIR.mkdir(parents=True, exist_ok=True)


class _Event:
    __slots__ = ("category", "data", "name", "ts")

    def __init__(self, category: str, name: str, data: Any = None):
        self.ts = datetime.now()
        self.category = category
        self.name = name
        self.data = data

    def __repr__(self):
        return f"[{self.ts.strftime('%H:%M:%S.%f')[:-3]}] {self.category}/{self.name}"


class DiagnosticsCollector:
    """Singleton que registra eventos de diagnóstico en memoria y en disco."""

    _instance: Optional["DiagnosticsCollector"] = None

    def __new__(cls) -> "DiagnosticsCollector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._events: list[_Event] = []
            cls._instance._max_events = 1000
            _ensure_log_dir()
        return cls._instance

    # ── Métodos de registro ────────────────────────────────────────

    def log_event(self, category: str, name: str, data: Any = None) -> None:
        """Registra un evento genérico."""
        ev = _Event(category, name, data)
        self._events.append(ev)
        if len(self._events) > self._max_events:
            self._events.pop(0)
        self._write_log(f"EVENT  {ev.category}/{ev.name}"
                        + (f" | {data}" if data is not None else ""))

    def log_error(self, context: str, exc: Exception) -> None:
        """Registra una excepción con contexto."""
        msg = f"{type(exc).__name__}: {exc}"
        ev = _Event("error", context, msg)
        self._events.append(ev)
        if len(self._events) > self._max_events:
            self._events.pop(0)
        self._write_log(f"ERROR  {context} | {msg}")
        logger.debug(f"[Diagnostics] ERROR {context}: {msg}")

    def log_timing(self, operation: str, elapsed_ms: float) -> None:
        """Registra el tiempo de una operación en ms."""
        ev = _Event("timing", operation, elapsed_ms)
        self._events.append(ev)
        if len(self._events) > self._max_events:
            self._events.pop(0)
        flag = " [LENTO]" if elapsed_ms > 500 else ""
        self._write_log(f"TIMING {operation} | {elapsed_ms:.1f}ms{flag}")

    # ── Informe ────────────────────────────────────────────────────

    def get_report(self) -> str:
        """Retorna un resumen formateado con errores, ops lentas y eventos frecuentes."""
        lines = ["=== Huevonitis 4 — Diagnóstico ===",
                 f"Total eventos registrados: {len(self._events)}",
                 ""]

        # Últimos errores
        errors = [e for e in self._events if e.category == "error"]
        lines.append(f"--- Errores recientes ({len(errors)}) ---")
        for e in errors[-10:]:
            lines.append(f"  {e.ts.strftime('%H:%M:%S')}  {e.name}: {e.data}")
        if not errors:
            lines.append("  (sin errores)")
        lines.append("")

        # Operaciones lentas (> 500 ms)
        timings = [e for e in self._events if e.category == "timing"]
        slow = [e for e in timings if isinstance(e.data, (int, float)) and e.data > 500]
        lines.append(f"--- Operaciones lentas >500ms ({len(slow)}) ---")
        for e in slow[-10:]:
            lines.append(f"  {e.ts.strftime('%H:%M:%S')}  {e.name}: {e.data:.1f}ms")
        if not slow:
            lines.append("  (ninguna)")
        lines.append("")

        # Eventos frecuentes
        from collections import Counter
        freq = Counter(f"{e.category}/{e.name}" for e in self._events)
        lines.append("--- Eventos más frecuentes ---")
        for name, count in freq.most_common(10):
            lines.append(f"  {count:4d}x  {name}")
        lines.append("")

        # Tiempos de operación promedio
        timing_by_op: dict[str, list[float]] = {}
        for e in timings:
            if isinstance(e.data, (int, float)):
                timing_by_op.setdefault(e.name, []).append(e.data)
        if timing_by_op:
            lines.append("--- Tiempos promedio por operación ---")
            for op, vals in sorted(timing_by_op.items()):
                avg = sum(vals) / len(vals)
                lines.append(f"  {op}: avg={avg:.1f}ms n={len(vals)}")
            lines.append("")

        return "\n".join(lines)

    def clear(self) -> None:
        """Limpia todos los eventos en memoria."""
        self._events.clear()

    # ── IO de log ─────────────────────────────────────────────────

    def _write_log(self, message: str) -> None:
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{ts}  {message}\n")
        except Exception:
            pass


# Instancia global (singleton)
diagnostics = DiagnosticsCollector()


# ── Decorador @timed ───────────────────────────────────────────────

def timed(name: str):
    """Decorador que mide el tiempo de ejecución y lo registra en diagnostics."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                diagnostics.log_timing(name, elapsed_ms)
        return wrapper
    return decorator

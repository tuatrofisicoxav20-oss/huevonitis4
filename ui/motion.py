"""Puerta de entrada única al motion de la UI (U0).

Toda animación (nueva o existente) pasa por animate(), que respeta el nivel
global del usuario persistido en config.SETTINGS_FILE (clave "animations"):

  • "full"    (Completas) — todo anima.
  • "reduced" (Reducidas) — SOLO lerps de color (kind="color"); el resto de
    animaciones (geometría, posición, conteos) salta al estado final.
  • "off"     (Off)       — nada anima: se aplica el estado final y listo.

Las easings y helpers de color viven aquí (animations.py los re-exporta para
no romper firmas existentes). animate() registra el job por (widget, key):
re-lanzar la misma animación cancela la anterior, y un widget destruido a
mitad de animación simplemente corta el loop (winfo_exists).
"""
from __future__ import annotations

import contextlib
import json
import logging

import config

logger = logging.getLogger(__name__)

LEVELS = ("full", "reduced", "off")
LEVEL_LABELS = {"Completas": "full", "Reducidas": "reduced", "Off": "off"}
LABEL_BY_LEVEL = {v: k for k, v in LEVEL_LABELS.items()}

_level: str | None = None  # cache; None = aún no leído de settings


# ── Easing ───────────────────────────────────────────────────────────────────

def ease_in_out(t: float) -> float:
    return t * t * (3 - 2 * t)


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in(t: float) -> float:
    return t * t * t


_EASINGS = {
    "ease_in_out": ease_in_out,
    "ease_out": ease_out,
    "ease_in": ease_in,
    "linear": lambda t: t,
}


# ── Color helpers ────────────────────────────────────────────────────────────

def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp_color(from_hex: str, to_hex: str, t: float) -> str:
    fc = hex_to_rgb(from_hex)
    tc = hex_to_rgb(to_hex)
    return rgb_to_hex(
        int(fc[0] + (tc[0] - fc[0]) * t),
        int(fc[1] + (tc[1] - fc[1]) * t),
        int(fc[2] + (tc[2] - fc[2]) * t),
    )


# ── Nivel global ─────────────────────────────────────────────────────────────

def get_motion_level() -> str:
    """Nivel actual: "full" | "reduced" | "off" (lee settings una sola vez)."""
    global _level
    if _level is None:
        _level = _read_level_from_settings()
    return _level


def set_motion_level(level: str) -> None:
    """Aplica el nivel EN CALIENTE (acepta nivel interno o etiqueta de UI).

    No persiste: la persistencia es de quien edita settings (SettingsView
    guarda la clave "animations" junto al tema).
    """
    global _level
    level = LEVEL_LABELS.get(level, level)
    if level not in LEVELS:
        logger.warning("Nivel de animación desconocido %r; uso 'full'", level)
        level = "full"
    _level = level


def _read_level_from_settings() -> str:
    try:
        if config.SETTINGS_FILE.exists():
            with open(config.SETTINGS_FILE, encoding="utf-8") as f:
                label = json.load(f).get("animations", "Completas")
            return LEVEL_LABELS.get(label, "full")
    except Exception:
        pass
    return "full"


def should_animate(kind: str = "motion") -> bool:
    """True si una animación de este tipo debe correr con el nivel actual."""
    level = get_motion_level()
    if level == "off":
        return False
    if level == "reduced":
        return kind == "color"
    return True


# ── Animador genérico ────────────────────────────────────────────────────────

# (id(widget), key) → after-job id. Re-animar la misma key cancela el job
# anterior (evita dobles animaciones corrompiendo el estado).
_jobs: dict[tuple[int, str], str] = {}


def cancel(widget, key: str = "default") -> None:
    """Cancela la animación (widget, key) si está en vuelo."""
    job = _jobs.pop((id(widget), key), None)
    if job is not None:
        with contextlib.suppress(Exception):
            widget.after_cancel(job)


def hoverable(widget, base: str, hover: str, accent_border: str | None = None,
              steps: int = 7, step_ms: int = 17) -> None:
    """Hover unificado (U8/M5): lerp de fg_color base↔hover en ~120 ms
    (y borde de acento opcional), respetando el nivel global."""
    def _to(target: str, border_target: str | None):
        current = _current_fg(widget, base)

        def _step(t):
            widget.configure(fg_color=lerp_color(current, target, t))
        animate(widget, _step, steps=steps, step_ms=step_ms,
                kind="color", key="hover")
        if accent_border is not None and border_target is not None:
            with contextlib.suppress(Exception):
                widget.configure(border_color=border_target)

    widget.bind("<Enter>", lambda _e: _to(hover, accent_border), add="+")
    widget.bind("<Leave>", lambda _e: _to(base, None), add="+")


def _current_fg(widget, fallback: str) -> str:
    try:
        val = widget.cget("fg_color")
        if isinstance(val, (list, tuple)):
            val = val[0]
        return val if isinstance(val, str) and val.startswith("#") else fallback
    except Exception:
        return fallback


def animate(widget, fn_step, steps: int = 10, step_ms: int = 16,
            on_done=None, kind: str = "motion", easing: str = "ease_out",
            key: str = "default") -> None:
    """Anima llamando fn_step(t) con t easeado en (0, 1].

    Respeta el nivel global: si no toca animar (ver should_animate), aplica
    el estado final (fn_step(1.0)) y corre on_done — el resultado funcional
    es idéntico, solo que instantáneo. El loop corta solo si el widget muere.
    """
    cancel(widget, key)

    def _finish():
        with contextlib.suppress(Exception):
            fn_step(1.0)
        if on_done is not None:
            with contextlib.suppress(Exception):
                on_done()

    if not should_animate(kind) or steps <= 0:
        _finish()
        return

    ease_fn = _EASINGS.get(easing, ease_out)
    jkey = (id(widget), key)

    def step(i: int):
        _jobs.pop(jkey, None)
        try:
            if not widget.winfo_exists():
                return
            fn_step(ease_fn(i / steps))
        except Exception:
            return
        if i < steps:
            try:
                _jobs[jkey] = widget.after(step_ms, lambda: step(i + 1))
            except Exception:
                return
        else:
            if on_done is not None:
                with contextlib.suppress(Exception):
                    on_done()

    step(1)

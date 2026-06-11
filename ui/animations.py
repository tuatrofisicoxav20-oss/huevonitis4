"""Animaciones de la UI — TODAS pasan por ui/motion.py (U0).

Este módulo conserva las firmas públicas históricas (count_up, animate_width,
ease_out, …) pero delega en motion.animate(), que respeta el nivel global
"Animaciones" del usuario (Completas / Reducidas / Off) y cancela jobs de
widgets muertos. Las easings y helpers de color se re-exportan desde motion.
"""
import contextlib

from ui import motion
from ui.motion import (  # noqa: F401 — re-export para firmas históricas
    ease_in,
    ease_in_out,
    ease_out,
)
from ui.motion import (
    lerp_color as _lerp_color,
)

# ── Width animation ─────────────────────────────────────────────────────────

def animate_width(widget, start_w: int, end_w: int, steps: int = 15, step_ms: int = 11, callback=None):
    def _step(t):
        widget.configure(width=int(start_w + (end_w - start_w) * t))

    motion.animate(widget, _step, steps=steps, step_ms=step_ms, on_done=callback,
                   kind="motion", easing="ease_in_out", key="width")


# ── Color / label animation ─────────────────────────────────────────────────

def animate_alpha_label(label, from_color: str, to_color: str, steps: int = 12, step_ms: int = 16):
    def _step(t):
        label.configure(text_color=_lerp_color(from_color, to_color, t))

    motion.animate(label, _step, steps=steps, step_ms=step_ms,
                   kind="color", easing="ease_in_out", key="text_color")


# ── Fade frame in (bg color transition) ────────────────────────────────────

def fade_frame_in(frame, steps: int = 8, step_ms: int = 20, callback=None):
    """Fade-in barato vía lerp de fg_color desde el fondo del tema (UI-21:
    el color inicial sale de theme.BG_PRIMARY — ya no rompe el tema claro)."""
    from ui import theme
    start_col = theme.BG_PRIMARY
    end_col = theme.CARD_BG

    def _step(t):
        frame.configure(fg_color=_lerp_color(start_col, end_col, t))

    motion.animate(frame, _step, steps=steps, step_ms=step_ms, on_done=callback,
                   kind="color", easing="ease_in_out", key="fg_color")


# ── Count-up animation ──────────────────────────────────────────────────────

def count_up(label, end_value: int | float, prefix: str = "", suffix: str = "",
             steps: int = 20, step_ms: int = 30, is_float: bool = False):
    def _fmt(value) -> str:
        if is_float:
            return f"{prefix}{value:,.2f}{suffix}"
        return f"{prefix}{int(value):,}{suffix}"

    def _step(t):
        label.configure(text=_fmt(end_value if t >= 1.0 else end_value * t))

    motion.animate(label, _step, steps=steps, step_ms=step_ms,
                   kind="motion", easing="ease_in_out", key="count_up")


# ── Generic value animator ──────────────────────────────────────────────────

def animate_value(start: float, end: float, duration_ms: int, callback,
                  easing="ease_in_out", widget=None, steps: int = 30):
    """
    Generic value animator. Calls callback(current_value) each step.
    easing: 'ease_in_out' | 'ease_out' | 'ease_in' | 'linear'
    widget: any tkinter widget used for .after() scheduling; if None, applies
    the final value synchronously.
    """
    if widget is None:
        with contextlib.suppress(Exception):
            callback(end)
        return
    step_ms = max(1, duration_ms // steps)

    def _step(t):
        callback(start + (end - start) * t)

    motion.animate(widget, _step, steps=steps, step_ms=step_ms,
                   kind="motion", easing=easing, key="value")


# ── Fade-in widget (fg_color interpolation) ─────────────────────────────────

def fade_in(widget, duration_ms: int = 250, steps: int = 15,
            from_color: str | None = None, to_color: str | None = None):
    """
    Animates widget fg_color from from_color (default: theme.BG_PRIMARY) to
    to_color (or its current fg_color).
    """
    from ui import theme
    if from_color is None:
        from_color = theme.BG_PRIMARY
    if to_color is None:
        try:
            to_color = widget.cget("fg_color")
            if isinstance(to_color, (list, tuple)):
                to_color = to_color[0]
        except Exception:
            return
    step_ms = max(1, duration_ms // steps)

    def _step(t):
        widget.configure(fg_color=_lerp_color(from_color, to_color, t))

    motion.animate(widget, _step, steps=steps, step_ms=step_ms,
                   kind="color", easing="ease_out", key="fg_color")


# ── Slide-in animation ──────────────────────────────────────────────────────

def slide_in(widget, direction: str = "right", distance_px: int = 40,
             duration_ms: int = 300, steps: int = 18):
    """
    Slides widget into position using place offsets.
    direction: 'right' | 'left' | 'up' | 'down'
    Assumes the widget is already placed at its final position via pack/grid/place.
    Uses place override temporarily.
    """
    if not motion.should_animate("motion"):
        return  # ya está en su posición final
    widget.update_idletasks()
    x0 = widget.winfo_x()
    y0 = widget.winfo_y()
    w = widget.winfo_width()
    h = widget.winfo_height()

    if direction == "right":
        sx, sy = x0 + distance_px, y0
    elif direction == "left":
        sx, sy = x0 - distance_px, y0
    elif direction == "down":
        sx, sy = x0, y0 + distance_px
    else:  # up
        sx, sy = x0, y0 - distance_px

    step_ms = max(1, duration_ms // steps)

    def _step(t):
        widget.place(x=int(sx + (x0 - sx) * t), y=int(sy + (y0 - sy) * t),
                     width=w, height=h)

    motion.animate(widget, _step, steps=steps, step_ms=step_ms,
                   kind="motion", easing="ease_out", key="slide")


# ── Pulse animation ─────────────────────────────────────────────────────────

def pulse(widget, color_a: str, color_b: str, cycles: int = 3,
          step_ms: int = 60, steps_per_half: int = 8):
    """
    Pulses widget fg_color between color_a and color_b for `cycles` full cycles.
    """
    if not motion.should_animate("color"):
        with contextlib.suppress(Exception):
            widget.configure(fg_color=color_a)
        return
    total_halves = cycles * 2

    def do_half(half_idx):
        if half_idx >= total_halves:
            with contextlib.suppress(Exception):
                widget.configure(fg_color=color_a)
            return
        from_c = color_a if half_idx % 2 == 0 else color_b
        to_c = color_b if half_idx % 2 == 0 else color_a

        def _step(t):
            widget.configure(fg_color=_lerp_color(from_c, to_c, t))

        motion.animate(widget, _step, steps=steps_per_half, step_ms=step_ms,
                       kind="color", easing="ease_in_out", key="pulse",
                       on_done=lambda: do_half(half_idx + 1))

    do_half(0)


# ── Hover color helpers ─────────────────────────────────────────────────────

def bind_hover_color(widget, normal_color: str, hover_color: str,
                     steps: int = 6, step_ms: int = 20):
    """
    Binds smooth Enter/Leave color transitions to a CTkFrame or similar widget.
    """
    def _animate_to(target: str):
        try:
            current = widget.cget("fg_color")
            if isinstance(current, (list, tuple)):
                current = current[0]
        except Exception:
            return

        def _step(t):
            widget.configure(fg_color=_lerp_color(current, target, t))

        motion.animate(widget, _step, steps=steps, step_ms=step_ms,
                       kind="color", easing="ease_out", key="hover")

    widget.bind("<Enter>", lambda e: _animate_to(hover_color), add="+")
    widget.bind("<Leave>", lambda e: _animate_to(normal_color), add="+")

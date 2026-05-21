import math


# ── Easing functions ────────────────────────────────────────────────────────

def ease_in_out(t: float) -> float:
    return t * t * (3 - 2 * t)


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in(t: float) -> float:
    return t * t * t


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp_color(from_hex: str, to_hex: str, t: float) -> str:
    fc = _hex_to_rgb(from_hex)
    tc = _hex_to_rgb(to_hex)
    r = int(fc[0] + (tc[0] - fc[0]) * t)
    g = int(fc[1] + (tc[1] - fc[1]) * t)
    b = int(fc[2] + (tc[2] - fc[2]) * t)
    return _rgb_to_hex(r, g, b)


# ── Width animation ─────────────────────────────────────────────────────────

def animate_width(widget, start_w: int, end_w: int, steps: int = 15, step_ms: int = 11, callback=None):
    if steps <= 0:
        widget.configure(width=end_w)
        if callback:
            callback()
        return

    def step(i):
        t = ease_in_out(i / steps)
        new_w = int(start_w + (end_w - start_w) * t)
        try:
            widget.configure(width=new_w)
        except Exception:
            return
        if i < steps:
            widget.after(step_ms, lambda: step(i + 1))
        else:
            widget.configure(width=end_w)
            if callback:
                callback()

    step(1)


# ── Color / label animation ─────────────────────────────────────────────────

def animate_alpha_label(label, from_color: str, to_color: str, steps: int = 12, step_ms: int = 16):
    fc = _hex_to_rgb(from_color)
    tc = _hex_to_rgb(to_color)

    def step(i):
        t = ease_in_out(i / steps)
        r = int(fc[0] + (tc[0] - fc[0]) * t)
        g = int(fc[1] + (tc[1] - fc[1]) * t)
        b = int(fc[2] + (tc[2] - fc[2]) * t)
        try:
            label.configure(text_color=_rgb_to_hex(r, g, b))
        except Exception:
            return
        if i < steps:
            label.after(step_ms, lambda: step(i + 1))

    step(1)


# ── Fade frame in (bg color transition) ────────────────────────────────────

def fade_frame_in(frame, steps: int = 8, step_ms: int = 20, callback=None):
    """Lightweight fade-in using bg color shift from near-black to card bg."""
    from ui import theme
    start_col = "#0a0e14"
    end_col = theme.CARD_BG

    def step(i):
        t = ease_in_out(i / steps)
        color = _lerp_color(start_col, end_col, t)
        try:
            frame.configure(fg_color=color)
        except Exception:
            pass
        if i < steps:
            frame.after(step_ms, lambda: step(i + 1))
        else:
            try:
                frame.configure(fg_color=end_col)
            except Exception:
                pass
            if callback:
                callback()

    step(1)


# ── Count-up animation ──────────────────────────────────────────────────────

# Per-widget job registry so a new count_up() cancels any in-flight animation
# on the same label, preventing double-animation value corruption.
_count_up_jobs: dict = {}


def count_up(label, end_value: int | float, prefix: str = "", suffix: str = "",
             steps: int = 20, step_ms: int = 30, is_float: bool = False):
    # Cancel any existing animation running on this label
    existing = _count_up_jobs.pop(id(label), None)
    if existing is not None:
        try:
            label.after_cancel(existing)
        except Exception:
            pass

    def step(i):
        t = ease_in_out(i / steps)
        current = end_value * t
        if is_float:
            text = f"{prefix}{current:,.2f}{suffix}"
        else:
            text = f"{prefix}{int(current):,}{suffix}"
        try:
            label.configure(text=text)
        except Exception:
            _count_up_jobs.pop(id(label), None)
            return
        if i < steps:
            job = label.after(step_ms, lambda: step(i + 1))
            _count_up_jobs[id(label)] = job
        else:
            _count_up_jobs.pop(id(label), None)
            if is_float:
                label.configure(text=f"{prefix}{end_value:,.2f}{suffix}")
            else:
                label.configure(text=f"{prefix}{int(end_value):,}{suffix}")

    job = label.after(step_ms, lambda: step(1))
    _count_up_jobs[id(label)] = job


# ── Generic value animator ──────────────────────────────────────────────────

# Per-widget job registry so a new animate_value() cancels any in-flight
# animation on the same widget, preventing simultaneous double-animations.
_animate_value_jobs: dict = {}


def animate_value(start: float, end: float, duration_ms: int, callback,
                  easing="ease_in_out", widget=None, steps: int = 30):
    """
    Generic value animator. Calls callback(current_value) each step.
    easing: 'ease_in_out' | 'ease_out' | 'ease_in' | 'linear'
    widget: any tkinter widget used for .after() scheduling; if None, tries callback
    """
    easing_fns = {
        "ease_in_out": ease_in_out,
        "ease_out": ease_out,
        "ease_in": ease_in,
        "linear": lambda t: t,
    }
    ease_fn = easing_fns.get(easing, ease_in_out)
    step_ms = max(1, duration_ms // steps)

    # We need a widget for .after(); if none provided, attempt to use the callback
    # return value or just fire immediately
    if widget is None:
        for i in range(1, steps + 1):
            t = ease_fn(i / steps)
            callback(start + (end - start) * t)
        return

    # Cancel any in-flight animation on this widget
    existing = _animate_value_jobs.pop(id(widget), None)
    if existing is not None:
        try:
            widget.after_cancel(existing)
        except Exception:
            pass

    def step(i):
        t = ease_fn(i / steps)
        val = start + (end - start) * t
        try:
            callback(val)
        except Exception:
            _animate_value_jobs.pop(id(widget), None)
            return
        if i < steps:
            job = widget.after(step_ms, lambda: step(i + 1))
            _animate_value_jobs[id(widget)] = job
        else:
            _animate_value_jobs.pop(id(widget), None)

    job = widget.after(step_ms, lambda: step(1))
    _animate_value_jobs[id(widget)] = job


# ── Fade-in widget (fg_color interpolation) ─────────────────────────────────

def fade_in(widget, duration_ms: int = 250, steps: int = 15,
            from_color: str = "#0a0e14", to_color: str | None = None):
    """
    Animates widget fg_color from from_color to to_color (or its current fg_color).
    Works on CTkFrame / CTkLabel etc.
    """
    if to_color is None:
        try:
            to_color = widget.cget("fg_color")
            if isinstance(to_color, (list, tuple)):
                to_color = to_color[0]
        except Exception:
            return
    step_ms = max(1, duration_ms // steps)

    def step(i):
        t = ease_out(i / steps)
        color = _lerp_color(from_color, to_color, t)
        try:
            widget.configure(fg_color=color)
        except Exception:
            return
        if i < steps:
            widget.after(step_ms, lambda: step(i + 1))
        else:
            try:
                widget.configure(fg_color=to_color)
            except Exception:
                pass

    step(1)


# ── Slide-in animation ──────────────────────────────────────────────────────

def slide_in(widget, direction: str = "right", distance_px: int = 40,
             duration_ms: int = 300, steps: int = 18):
    """
    Slides widget into position using place offsets.
    direction: 'right' | 'left' | 'up' | 'down'
    Assumes the widget is already placed at its final position via pack/grid/place.
    Uses place override temporarily.
    """
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

    def step(i):
        t = ease_out(i / steps)
        x = int(sx + (x0 - sx) * t)
        y = int(sy + (y0 - sy) * t)
        try:
            widget.place(x=x, y=y, width=w, height=h)
        except Exception:
            return
        if i < steps:
            widget.after(step_ms, lambda: step(i + 1))
        else:
            try:
                widget.place(x=x0, y=y0, width=w, height=h)
            except Exception:
                pass

    step(1)


# ── Pulse animation ─────────────────────────────────────────────────────────

def pulse(widget, color_a: str, color_b: str, cycles: int = 3,
          step_ms: int = 60, steps_per_half: int = 8):
    """
    Pulses widget fg_color between color_a and color_b for `cycles` full cycles.
    """
    total_halves = cycles * 2
    current_half = [0]

    def do_half(half_idx):
        if half_idx >= total_halves:
            try:
                widget.configure(fg_color=color_a)
            except Exception:
                pass
            return
        from_c = color_a if half_idx % 2 == 0 else color_b
        to_c = color_b if half_idx % 2 == 0 else color_a

        def step(i):
            t = ease_in_out(i / steps_per_half)
            color = _lerp_color(from_c, to_c, t)
            try:
                widget.configure(fg_color=color)
            except Exception:
                return
            if i < steps_per_half:
                widget.after(step_ms, lambda: step(i + 1))
            else:
                current_half[0] += 1
                widget.after(step_ms, lambda: do_half(current_half[0]))

        step(1)

    do_half(0)


# ── Hover color helpers ─────────────────────────────────────────────────────

def bind_hover_color(widget, normal_color: str, hover_color: str,
                     steps: int = 6, step_ms: int = 20):
    """
    Binds smooth Enter/Leave color transitions to a CTkFrame or similar widget.
    """
    _animating = [False]
    _target = [normal_color]

    def _animate_to(target: str):
        _target[0] = target
        try:
            current_hex = widget.cget("fg_color")
            if isinstance(current_hex, (list, tuple)):
                current_hex = current_hex[0]
        except Exception:
            return

        def step(i, from_c=current_hex):
            if _target[0] != target:
                return  # direction changed mid-animation
            t = ease_out(i / steps)
            color = _lerp_color(from_c, target, t)
            try:
                widget.configure(fg_color=color)
            except Exception:
                return
            if i < steps:
                widget.after(step_ms, lambda: step(i + 1))
            else:
                try:
                    widget.configure(fg_color=target)
                except Exception:
                    pass

        step(1)

    widget.bind("<Enter>", lambda e: _animate_to(hover_color), add="+")
    widget.bind("<Leave>", lambda e: _animate_to(normal_color), add="+")

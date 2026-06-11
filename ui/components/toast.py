import contextlib

import customtkinter as ctk

from ui import theme
from ui.animations import ease_out


class ToastManager:
    TOAST_WIDTH = 290
    TOAST_SPACING = 10
    MARGIN_RIGHT = 18
    MARGIN_BOTTOM = 24

    def __init__(self, parent):
        self.parent = parent
        self._toasts: list = []
        self._max = 4
        # Reposition toasts whenever the window is resized
        self.parent.bind("<Configure>", self._on_parent_resize, add="+")

    def show(self, message: str, kind: str = "info", duration: int = 3500):
        colors = {
            "info": theme.ACCENT_BLUE,
            "success": theme.ACCENT_GREEN,
            "warning": theme.ACCENT_ORANGE,
            "error": theme.ACCENT_RED,
        }
        icons = {"info": "\u2139", "success": "✓", "warning": "⚠", "error": "✕"}
        color = colors.get(kind, theme.ACCENT_BLUE)
        icon = icons.get(kind, "\u2139")

        # Evict oldest if at max
        if len(self._toasts) >= self._max:
            try:
                old = self._toasts.pop(0)
                old.destroy()
            except Exception:
                pass

        toast = ctk.CTkFrame(
            self.parent,
            fg_color=theme.BG_SECONDARY,
            corner_radius=10,
            border_width=1,
            border_color=color,
        )

        # Content row
        toast_row = ctk.CTkFrame(toast, fg_color="transparent")
        toast_row.pack(padx=12, pady=(10, 6), fill="x")

        ctk.CTkLabel(
            toast_row, text=icon, text_color=color,
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            toast_row,
            text=message[:90],
            text_color=theme.TEXT_PRIMARY,
            font=theme.FONT_BODY,
            wraplength=210,
            justify="left",
        ).pack(side="left", fill="x", expand=True)

        btn_close = ctk.CTkButton(
            toast_row, text="\u00d7", width=24, height=24,
            fg_color="transparent", hover_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_SECONDARY, font=("Segoe UI", 14),
            command=lambda t=toast: self._dismiss(t),
        )
        btn_close.pack(side="right")

        # Progress bar at bottom
        progress_bar = ctk.CTkFrame(toast, fg_color=color, height=3, corner_radius=0)
        progress_bar.pack(fill="x", side="bottom")
        toast._progress_bar = progress_bar
        toast._progress_color = color
        toast._duration = duration

        self._toasts.append(toast)
        # NO update_idletasks aquí: el flush global procesa el backlog de
        # layout de TODA la app (grids de cientos de widgets incluidos) y
        # congelaba el mainloop al mostrar un toast tras una operación gorda.
        # _restack/_slide_in ya tienen fallbacks para medidas no listas.
        self._restack()
        self._slide_in(toast)
        self._animate_progress(toast, duration)
        self.parent.after(duration, lambda: self._dismiss(toast))

    def _animate_progress(self, toast, duration: int):
        steps = max(10, duration // 30)
        step_ms = max(10, duration // steps)

        def step(i):
            if toast not in self._toasts:
                return
            ratio = max(0.0, 1.0 - (i / steps))
            try:
                pw = toast.winfo_width()
                if pw < 2:
                    pw = self.TOAST_WIDTH
                bar_w = max(0, int(pw * ratio))
                toast._progress_bar.configure(width=bar_w)
            except Exception:
                return
            if i < steps and toast in self._toasts:
                toast.after(step_ms, lambda: step(i + 1))

        toast.after(50, lambda: step(0))

    def _restack(self):
        pw = self.parent.winfo_width()
        ph = self.parent.winfo_height()
        # HiDPI guard: customtkinter a veces reporta winfo_width antes de
        # que la ventana haya medido. Si lo que recibimos no podría caber
        # un toast, caemos al tamaño de pantalla como mejor aproximación
        # para no posicionar fuera del área visible.
        if pw < 320:
            try:
                pw = max(800, self.parent.winfo_screenwidth() // 2)
            except Exception:
                pw = 800
        if ph < 200:
            try:
                ph = max(600, self.parent.winfo_screenheight() // 2)
            except Exception:
                ph = 600

        base_x = pw - self.TOAST_WIDTH - self.MARGIN_RIGHT
        base_y = ph - self.MARGIN_BOTTOM

        for i, t in enumerate(reversed(self._toasts)):
            try:
                th = t.winfo_reqheight() or 72
                y = base_y - th - i * (th + self.TOAST_SPACING)
                t.place(x=base_x, y=y, width=self.TOAST_WIDTH)
                t.lift()
            except Exception:
                pass

    def _slide_in(self, toast):
        pw = self.parent.winfo_width()
        if pw < 10:
            pw = 800
        target_x = pw - self.TOAST_WIDTH - self.MARGIN_RIGHT
        start_x = pw + 20
        steps = 16
        step_ms = 14

        def step(i):
            t_ease = ease_out(min(1.0, i / steps))
            x = int(start_x + (target_x - start_x) * t_ease)
            try:
                current_y = toast.winfo_y()
                toast.place(x=x, y=current_y, width=self.TOAST_WIDTH)
            except Exception:
                return
            if i < steps:
                toast.after(step_ms, lambda: step(i + 1))
            else:
                with contextlib.suppress(Exception):
                    toast.place(x=target_x, y=toast.winfo_y(), width=self.TOAST_WIDTH)
                    # Forzar lift al final: si otro widget se pintó durante
                    # la animación, el toast podría quedar tapado.
                    toast.lift()

        step(1)

    def _on_parent_resize(self, event):
        if event.widget is self.parent and self._toasts:
            self._restack()

    def _dismiss(self, toast):
        try:
            if toast in self._toasts:
                self._toasts.remove(toast)
            toast.destroy()
            self._restack()
        except Exception:
            pass

"""Modal de resultados del diagnóstico de sesión.

Llamado desde main.py si SessionDiagnostic.run_all() encuentra warnings/errors.
Cada check con auto_fix puede arreglarse individualmente o en bloque ("Arreglar
todos los seguros"). El usuario también puede ignorar y continuar.

Devuelve True si el usuario eligió continuar (independiente de si arregló o no).
"""
from __future__ import annotations

import logging

import customtkinter as ctk

from core.session_diagnostic import CheckResult
from ui import theme

logger = logging.getLogger(__name__)


_SEVERITY_ICON = {"ok": "✓", "warning": "⚠", "error": "✕"}
_SEVERITY_COLOR = {
    "ok":      theme.ACCENT_GREEN,
    "warning": theme.ACCENT_ORANGE,
    "error":   theme.ACCENT_RED,
}


def show_diagnostic_modal(results: list[CheckResult]) -> bool:
    """Muestra modal bloqueante. Devuelve True si el usuario aceptó continuar.

    Si todos los checks son "ok", no muestra nada y devuelve True directamente.
    """
    issues = [r for r in results if r.severity in ("warning", "error")]
    if not issues:
        logger.info("Diagnóstico: todos los checks OK, sin modal")
        return True

    # Usamos un ctk.CTk() directo en vez de un CTkToplevel sobre un root oculto:
    # ese patrón (tk.Tk().withdraw() + Toplevel) NO se mapea como ventana bajo
    # Hyprland/XWayland, así que el proceso quedaba colgado en mainloop() sin
    # nada visible en pantalla. El CTk normal sí se mapea (es lo que usa la app).
    win = ctk.CTk()
    win.title("Diagnóstico de sesión")
    win.configure(fg_color=theme.BG_PRIMARY)
    win.geometry("640x520")
    # Forzar que la ventana aparezca al frente y con foco (algunos WM no lo
    # hacen solos para una ventana recién creada).
    win.deiconify()
    win.lift()
    win.focus_force()
    win.attributes("-topmost", True)
    win.after(300, lambda: win.attributes("-topmost", False))

    user_continued = {"ok": False}

    ctk.CTkLabel(
        win,
        text=f"🔍 Encontramos {len(issues)} cosa(s) que revisar",
        font=theme.FONT_TITLE, text_color=theme.TEXT_PRIMARY,
    ).pack(pady=(20, 4))
    ctk.CTkLabel(
        win,
        text="Puedes arreglar las que ofrecen auto-fix, ignorar y continuar, o cerrar la app.",
        font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        wraplength=560, justify="center",
    ).pack(pady=(0, 12))

    scroll = ctk.CTkScrollableFrame(win, fg_color=theme.BG_SECONDARY, corner_radius=8)
    scroll.pack(fill="both", expand=True, padx=20, pady=8)

    rows: list[tuple[CheckResult, ctk.CTkButton | None, ctk.CTkLabel]] = []

    def _render_row(result: CheckResult) -> None:
        row = ctk.CTkFrame(
            scroll, fg_color=theme.BG_TERTIARY, corner_radius=6,
            border_width=1, border_color=_SEVERITY_COLOR.get(result.severity, theme.BORDER),
        )
        row.pack(fill="x", pady=4, padx=4)

        icon = _SEVERITY_ICON.get(result.severity, "•")
        color = _SEVERITY_COLOR.get(result.severity, theme.TEXT_PRIMARY)
        head_lbl = ctk.CTkLabel(
            row, text=f"  {icon}  {result.name}",
            font=theme.FONT_SUBHEADING, text_color=color,
        )
        head_lbl.pack(side="left", padx=8, pady=8)

        msg_lbl = ctk.CTkLabel(
            row, text=result.message,
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
            wraplength=320, justify="left",
        )
        msg_lbl.pack(side="left", padx=8, pady=8, fill="x", expand=True)

        fix_btn = None
        if result.is_fixable:
            def _do_fix(r=result, b=None, m=msg_lbl):
                try:
                    ok = r.auto_fix()
                    r.fixed = ok
                except Exception as exc:
                    logger.error("auto_fix %s lanzó: %s", r.name, exc, exc_info=True)
                    ok = False
                if ok:
                    m.configure(
                        text=f"✓ Arreglado — {r.message}",
                        text_color=theme.ACCENT_GREEN,
                    )
                    if b is not None:
                        b.configure(state="disabled", text="✓ Hecho")
                else:
                    m.configure(
                        text=f"✕ Falló — {r.message}",
                        text_color=theme.ACCENT_RED,
                    )

            fix_btn = ctk.CTkButton(
                row, text="🔧 Arreglar", width=110, height=30,
                fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
                font=theme.FONT_SMALL,
            )
            fix_btn.configure(command=lambda r=result, b=fix_btn, m=msg_lbl:
                              _do_fix(r, b, m))
            fix_btn.pack(side="right", padx=8, pady=8)

        rows.append((result, fix_btn, msg_lbl))

    for r in issues:
        _render_row(r)

    btn_bar = ctk.CTkFrame(win, fg_color="transparent")
    btn_bar.pack(fill="x", padx=20, pady=12)

    def _fix_all_safe():
        for r, b, _m in rows:
            if r.is_fixable and (b is None or str(b.cget("state")) == "normal") and b is not None:
                b.invoke()

    ctk.CTkButton(
        btn_bar, text="🔧 Arreglar todos los seguros", width=240, height=36,
        fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
        font=theme.get_font("bold", 11),
        command=_fix_all_safe,
    ).pack(side="left")

    def _close_continue():
        user_continued["ok"] = True
        win.destroy()

    def _close_quit():
        user_continued["ok"] = False
        win.destroy()

    ctk.CTkButton(
        btn_bar, text="✕ Salir de Huevonitis", width=180, height=36,
        fg_color=theme.ACCENT_RED, hover_color=theme.ACCENT_RED_HOVER,
        font=theme.FONT_SMALL,
        command=_close_quit,
    ).pack(side="right")
    ctk.CTkButton(
        btn_bar, text="→ Continuar", width=140, height=36,
        fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
        font=theme.get_font("bold", 11),
        command=_close_continue,
    ).pack(side="right", padx=8)

    win.protocol("WM_DELETE_WINDOW", _close_continue)
    win.mainloop()

    return user_continued["ok"]

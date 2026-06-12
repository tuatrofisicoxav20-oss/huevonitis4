import logging
import sys

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)


class BaseView(ctk.CTkFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color=theme.BG_PRIMARY, corner_radius=0, **kwargs)
        self.app = app

    def on_show(self):
        """Called each time this view is shown."""
        pass

    def on_hide(self):
        """Called each time this view is hidden (before another view is shown)."""
        pass

    def toast(self, message: str, kind: str = "info"):
        """Mostrar toast. Si el manager falla o no existe, fallback a stderr.

        Sin el fallback, fallos de toast (HiDPI mal calculado, manager
        no inicializado, excepción interna) hacen que los mensajes
        desaparezcan en silencio — el usuario percibe que la acción no
        hizo nada aunque internamente sí se ejecutó.
        """
        tm = getattr(self.app, "toast_manager", None)
        if tm is not None:
            try:
                tm.show(message, kind)
                return
            except Exception as exc:
                logger.warning("toast.show falló: %s", exc, exc_info=True)
        # Fallback visible mínimo: stderr + log
        print(f"[TOAST/{kind}] {message}", file=sys.stderr, flush=True)
        logger.info("toast fallback (sin UI): [%s] %s", kind, message)

    def section_label(self, parent, text: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent,
            text=text,
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        )
        return label

    def card_frame(self, parent, hover: bool = False, **kwargs) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(
            parent,
            fg_color=theme.CARD_BG,
            corner_radius=theme.RADIUS["l"],
            border_width=1,
            border_color=theme.BORDER,
            **kwargs,
        )
        if hover:
            # U8/M5: hover unificado con lerp (~120 ms) vía ui/motion
            from ui import motion
            motion.hoverable(frame, theme.CARD_BG, theme.CARD_BG_HOVER,
                             accent_border=theme.BORDER_LIGHT)
        return frame

    def primary_button(self, parent, text: str, command, width: int = 140) -> ctk.CTkButton:
        # U2: el primario es ámbar (claro) → texto oscuro para contraste AA
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            fg_color=theme.ACCENT_PRIMARY, hover_color=theme.ACCENT_PRIMARY_HOVER,
            text_color=theme.ACCENT_TEXT_ON,
            font=theme.FONT_BODY, corner_radius=theme.RADIUS["m"],
        )

    def secondary_button(self, parent, text: str, command, width: int = 140) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            text_color=theme.TEXT_SECONDARY, font=theme.FONT_BODY,
            corner_radius=theme.RADIUS["m"],
        )

    def danger_button(self, parent, text: str, command, width: int = 140) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            fg_color=theme.ACCENT_RED, hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_BODY, corner_radius=theme.RADIUS["m"],
        )

import customtkinter as ctk
from ui import theme
from ui.animations import bind_hover_color


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
        if hasattr(self.app, 'toast_manager'):
            self.app.toast_manager.show(message, kind)

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
            corner_radius=10,
            border_width=1,
            border_color=theme.BORDER,
            **kwargs,
        )
        if hover:
            # Smooth hover: bg shifts slightly lighter, border highlights
            def on_enter(e):
                frame.configure(fg_color=theme.CARD_BG_HOVER, border_color=theme.BORDER_LIGHT)
            def on_leave(e):
                frame.configure(fg_color=theme.CARD_BG, border_color=theme.BORDER)
            frame.bind("<Enter>", on_enter, add="+")
            frame.bind("<Leave>", on_leave, add="+")
        return frame

    def primary_button(self, parent, text: str, command, width: int = 140) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_BODY, corner_radius=8,
        )

    def secondary_button(self, parent, text: str, command, width: int = 140) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            fg_color=theme.BG_TERTIARY, hover_color=theme.BORDER,
            text_color=theme.TEXT_SECONDARY, font=theme.FONT_BODY, corner_radius=8,
        )

    def danger_button(self, parent, text: str, command, width: int = 140) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            fg_color=theme.ACCENT_RED, hover_color=theme.ACCENT_RED_HOVER,
            font=theme.FONT_BODY, corner_radius=8,
        )

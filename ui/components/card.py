import customtkinter as ctk

from ui import theme
from ui.animations import count_up


class StatCard(ctk.CTkFrame):
    """
    A stat card with:
      - Left coloured accent bar (4 px)
      - Circular icon badge in the accent colour
      - Large animated value label
      - Subtle hover glow on border
    """

    def __init__(self, parent, title: str, value, icon: str, color: str,
                 is_currency: bool = False, **kwargs):
        super().__init__(
            parent,
            fg_color=theme.CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=theme.CARD_BORDER,
            **kwargs,
        )
        self._color = color
        self._value = value
        self._is_currency = is_currency

        # Hover: lift border to accent colour
        self.bind("<Enter>", lambda e: self.configure(
            fg_color=theme.CARD_BG_HOVER, border_color=color), add="+")
        self.bind("<Leave>", lambda e: self.configure(
            fg_color=theme.CARD_BG, border_color=theme.CARD_BORDER), add="+")

        # ── Left accent bar ────────────────────────────────────────
        accent_bar = ctk.CTkFrame(self, fg_color=color, width=4, corner_radius=3)
        accent_bar.pack(side="left", fill="y", padx=(0, 0))

        # ── Content ────────────────────────────────────────────────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=14, pady=14)

        # Top row: circular icon badge + title
        top_row = ctk.CTkFrame(content, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 6))

        # Circular badge
        badge = ctk.CTkFrame(
            top_row,
            fg_color=self._dim_color(color),
            width=38, height=38,
            corner_radius=19,
        )
        badge.pack(side="left")
        badge.pack_propagate(False)
        ctk.CTkLabel(
            badge,
            text=icon,
            font=("Segoe UI", 18),
            text_color=color,
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            top_row,
            text=title,
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=10, anchor="center")

        # Value row
        self._val_label = ctk.CTkLabel(
            content,
            text=self._format_value(value),
            font=("Segoe UI", 26, "bold"),
            text_color=color,
        )
        self._val_label.pack(anchor="w")

    @staticmethod
    def _dim_color(hex_color: str) -> str:
        """Return a very dark version of the accent color for the badge bg."""
        dim_map = {
            theme.ACCENT_BLUE:   theme.BADGE_BG_BLUE,
            theme.ACCENT_GREEN:  theme.BADGE_BG_GREEN,
            theme.ACCENT_ORANGE: theme.BADGE_BG_ORANGE,
            theme.ACCENT_RED:    theme.BADGE_BG_RED,
            theme.ACCENT_PURPLE: "#2D1A50",
            theme.ACCENT_YELLOW: "#2D2000",
        }
        return dim_map.get(hex_color, "#1A2030")

    def _format_value(self, value) -> str:
        if self._is_currency:
            return f"${float(value):,.2f} MXN"
        return f"{int(value):,}"

    def animate_value(self):
        try:
            count_up(
                self._val_label,
                float(self._value),
                prefix="$" if self._is_currency else "",
                suffix=" MXN" if self._is_currency else "",
                is_float=self._is_currency,
                steps=24,
                step_ms=25,
            )
        except Exception:
            pass


class ProjectCard(ctk.CTkFrame):
    """
    Project list card with:
      - Coloured left border matching project status
      - Hover effect
    """

    def __init__(self, parent, project, on_click, **kwargs):
        status_color = theme.STATUS_COLORS.get(
            getattr(project, "status", "Borrador"), theme.ACCENT_BLUE
        )
        super().__init__(
            parent,
            fg_color=theme.CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=theme.CARD_BORDER,
            cursor="hand2",
            **kwargs,
        )
        self._project = project

        # Left status stripe (4 px)
        stripe = ctk.CTkFrame(self, fg_color=status_color, width=4, corner_radius=2)
        stripe.pack(side="left", fill="y")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        name_label = ctk.CTkLabel(
            body,
            text=project.name[:28],
            font=theme.FONT_SUBHEADING,
            text_color=theme.TEXT_PRIMARY,
        )
        name_label.pack(anchor="w")

        pages_count = len(project.pages)
        mod = project.modified_at[:10] if len(project.modified_at) >= 10 else project.modified_at
        ctk.CTkLabel(
            body,
            text=f"📄 {pages_count} pág  •  {mod}",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(2, 0))

        for widget in (self, body, name_label):
            widget.bind("<Button-1>", lambda e, p=project: on_click(p))
            widget.bind("<Enter>", lambda e: self.configure(
                fg_color=theme.CARD_BG_HOVER, border_color=status_color), add="+")
            widget.bind("<Leave>", lambda e: self.configure(
                fg_color=theme.CARD_BG, border_color=theme.CARD_BORDER), add="+")

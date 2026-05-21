import contextlib
from datetime import datetime

import customtkinter as ctk

from ui import theme
from ui.components.card import ProjectCard, StatCard
from ui.views.base_view import BaseView


class DashboardView(BaseView):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._stats_animate_job = None
        self._build()

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=24, pady=20)

        # ── Greeting header ────────────────────────────────────────
        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", pady=(0, 20))

        now = datetime.now()
        if now.hour < 12:
            greeting = "Buenos días"
            greet_color = theme.ACCENT_YELLOW
        elif now.hour < 19:
            greeting = "Buenas tardes"
            greet_color = theme.ACCENT_ORANGE
        else:
            greeting = "Buenas noches"
            greet_color = theme.ACCENT_BLUE

        ctk.CTkLabel(
            header,
            text=f"{greeting} 👋",
            font=("Segoe UI", 22, "bold"),
            text_color=greet_color,
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Aquí tienes el resumen de tu trabajo",
            font=theme.FONT_BODY,
            text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(2, 0))

        # ── Section: Resumen ───────────────────────────────────────
        self._section_row(scroll, "📊  Resumen")

        self._stats_row = ctk.CTkFrame(scroll, fg_color="transparent")
        self._stats_row.pack(fill="x", pady=(0, 28))

        self._stat_cards: list[StatCard] = []
        self._build_stats()

        # ── Section: Proyectos Recientes ───────────────────────────
        self._section_row(scroll, "📁  Proyectos Recientes")

        self._projects_grid = ctk.CTkFrame(scroll, fg_color="transparent")
        self._projects_grid.pack(fill="x", pady=(0, 28))

        # ── Section: Acciones Rápidas ──────────────────────────────
        self._section_row(scroll, "⚡  Acciones Rápidas")

        self._glyph_status_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._glyph_status_frame.pack(fill="x", pady=(0, 10))

        actions_frame = ctk.CTkFrame(
            scroll,
            fg_color=theme.BG_SECONDARY,
            corner_radius=14,
            border_width=1,
            border_color=theme.BORDER,
        )
        actions_frame.pack(fill="x", pady=(0, 16))

        actions = [
            (
                "📁", "Nuevo Proyecto",
                "Crea o edita un proyecto de apuntes",
                lambda: self.app.navigate("projects"),
                theme.ACCENT_BLUE,
                theme.BADGE_BG_BLUE,
            ),
            (
                "📖", "Estudiar Texto",
                "Convierte texto en flashcards",
                lambda: self.app.navigate("study"),
                theme.ACCENT_PURPLE,
                "#2D1A50",
            ),
            (
                "✍️", "Escribir con mi Letra",
                "Usa InkCore para generar apuntes",
                lambda: self.app.navigate("inkcore"),
                theme.ACCENT_GREEN,
                theme.BADGE_BG_GREEN,
            ),
            (
                "💼", "Nuevo Trabajo",
                "Registra un trabajo freelance",
                lambda: self.app.navigate("business"),
                theme.ACCENT_ORANGE,
                theme.BADGE_BG_ORANGE,
            ),
        ]

        for col_idx, (icon, title, subtitle, cmd, color, _) in enumerate(actions):
            col_frame = ctk.CTkFrame(
                actions_frame,
                fg_color="transparent",
            )
            col_frame.grid(row=0, column=col_idx, sticky="ew", padx=8, pady=12)
            actions_frame.columnconfigure(col_idx, weight=1)

            btn = ctk.CTkButton(
                col_frame,
                text=f"{icon}  {title}",
                command=cmd,
                height=52,
                fg_color=color,
                hover_color=self._darken(color),
                font=("Segoe UI", 12, "bold"),
                corner_radius=10,
                text_color="#FFFFFF",
            )
            btn.pack(fill="x")

            ctk.CTkLabel(
                col_frame,
                text=subtitle,
                font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
                wraplength=150,
                justify="center",
            ).pack(pady=(4, 0))

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _section_row(parent, text: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            row,
            text=text,
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")

        sep = ctk.CTkFrame(row, height=1, fg_color=theme.BORDER, corner_radius=0)
        sep.pack(side="left", fill="x", expand=True, padx=(12, 0), pady=(6, 0))

    @staticmethod
    def _darken(hex_color: str) -> str:
        darken_map = {
            theme.ACCENT_BLUE:   theme.ACCENT_BLUE_HOVER,
            theme.ACCENT_GREEN:  theme.ACCENT_GREEN_HOVER,
            theme.ACCENT_ORANGE: theme.ACCENT_ORANGE_HOVER,
            theme.ACCENT_PURPLE: theme.ACCENT_PURPLE_HOVER,
        }
        return darken_map.get(hex_color, "#111111")

    def _build_stats(self):
        # Cancel any pending animate callback from a previous on_show() call
        if self._stats_animate_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._stats_animate_job)
            self._stats_animate_job = None

        for w in self._stats_row.winfo_children():
            w.destroy()
        self._stat_cards.clear()

        pm = self.app.project_manager
        ledger = self.app.ledger
        inkcore = self.app.inkcore

        projects = pm.list_projects()
        active_jobs = ledger.active_jobs_count()
        coverage = inkcore.bank_coverage()
        glyph_count = coverage.get("total_glyphs", 0)
        now = datetime.now()
        income = ledger.monthly_income(now.year, now.month)

        stats = [
            ("Proyectos",       len(projects), "📁", theme.ACCENT_BLUE,   False),
            ("Trabajos Activos", active_jobs,  "💼", theme.ACCENT_ORANGE, False),
            ("Glifos en Banco",  glyph_count,  "✍️", theme.ACCENT_GREEN,  False),
            ("Ingresos del Mes", income,        "💰", theme.ACCENT_PURPLE, True),
        ]

        for col_idx, (title, value, icon, color, is_curr) in enumerate(stats):
            self._stats_row.columnconfigure(col_idx, weight=1)
            card = StatCard(
                self._stats_row,
                title, value, icon, color,
                is_currency=is_curr,
            )
            card.grid(row=0, column=col_idx, padx=6, sticky="ew", ipady=4)
            self._stat_cards.append(card)

        def _animate_stats():
            if not self.winfo_exists():
                return
            for c in self._stat_cards:
                try:
                    if c.winfo_exists():
                        c.animate_value()
                except Exception:
                    pass
            self._stats_animate_job = None

        self._stats_animate_job = self.after(120, _animate_stats)

    def _build_glyph_status(self):
        """Indicator dot: green if glyphs exist, orange if bank is empty."""
        for w in self._glyph_status_frame.winfo_children():
            w.destroy()

        inkcore = self.app.inkcore
        coverage = inkcore.bank_coverage()
        glyph_count = coverage.get("total_glyphs", 0)

        if glyph_count > 0:
            dot_color = theme.ACCENT_GREEN
            status_text = f"InkCore listo — {glyph_count} glifos en banco"
        else:
            dot_color = theme.ACCENT_ORANGE
            status_text = "InkCore sin glifos — ve a 'Mi Letra' para extraer"

        indicator = ctk.CTkFrame(
            self._glyph_status_frame,
            fg_color=self._dim_badge(dot_color),
            corner_radius=8,
            border_width=1,
            border_color=dot_color,
        )
        indicator.pack(anchor="w")

        dot = ctk.CTkFrame(indicator, fg_color=dot_color, width=10, height=10, corner_radius=5)
        dot.pack(side="left", padx=(8, 4), pady=6)
        dot.pack_propagate(False)

        ctk.CTkLabel(
            indicator,
            text=status_text,
            font=theme.FONT_SMALL,
            text_color=dot_color,
        ).pack(side="left", padx=(0, 10), pady=6)

    @staticmethod
    def _dim_badge(color: str) -> str:
        return {
            theme.ACCENT_GREEN:  theme.BADGE_BG_GREEN,
            theme.ACCENT_ORANGE: theme.BADGE_BG_ORANGE,
        }.get(color, theme.BG_TERTIARY)

    def _build_projects(self):
        for w in self._projects_grid.winfo_children():
            w.destroy()

        projects = self.app.project_manager.list_projects()[:6]
        if not projects:
            ctk.CTkLabel(
                self._projects_grid,
                text="No hay proyectos aún. ¡Crea uno desde Acciones Rápidas!",
                font=theme.FONT_BODY,
                text_color=theme.TEXT_MUTED,
            ).pack(pady=20)
            return

        for i, proj in enumerate(projects):
            card = ProjectCard(self._projects_grid, proj, self._open_project)
            row, col = divmod(i, 3)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="ew")

        for c in range(3):
            self._projects_grid.columnconfigure(c, weight=1)

    def _open_project(self, project):
        self.app.app_state.current_project = project
        self.app.navigate("projects")

    def on_hide(self):
        if self._stats_animate_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._stats_animate_job)
            self._stats_animate_job = None

    def on_show(self):
        self._build_stats()
        self._build_projects()
        self._build_glyph_status()

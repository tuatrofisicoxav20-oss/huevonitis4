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

        # ── Greeting header (U2: banner orbital estático generado con PIL,
        # cacheado en disco — cero animación) ──────────────────────
        header = ctk.CTkFrame(scroll, fg_color="transparent", height=110)
        header.pack(fill="x", pady=(0, theme.SPACE["l"]))
        header.pack_propagate(False)

        banner = self._load_header_banner()
        if banner is not None:
            ctk.CTkLabel(header, image=banner, text="").place(
                x=0, y=0, relwidth=1.0, relheight=1.0)

        now = datetime.now()
        if now.hour < 12:
            greeting = "Buenos días"
        elif now.hour < 19:
            greeting = "Buenas tardes"
        else:
            greeting = "Buenas noches"
        # Ámbar de día, cian de noche (secundario informativo)
        greet_color = theme.ACCENT_CYAN if now.hour >= 19 else theme.ACCENT_PRIMARY

        # Los labels llevan fondo sólido BG_PRIMARY: la zona izquierda del
        # banner es plana de ese mismo color, así que no se nota costura
        # (Tk no compone transparencia entre widgets hermanos).
        ctk.CTkLabel(
            header,
            text=f"{greeting} 👋",
            font=theme.get_font("bold", 22),
            text_color=greet_color,
            fg_color=theme.BG_PRIMARY,
            bg_color=theme.BG_PRIMARY,
        ).place(x=theme.SPACE["xl"], y=24)
        ctk.CTkLabel(
            header,
            text="Aquí tienes el resumen de tu trabajo",
            font=theme.FONT_BODY,
            text_color=theme.TEXT_SECONDARY,
            fg_color=theme.BG_PRIMARY,
            bg_color=theme.BG_PRIMARY,
        ).place(x=theme.SPACE["xl"], y=62)

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

        # U2: acento único — las 4 acciones primarias van en ámbar.
        actions = [
            ("📁", "Nuevo Proyecto", "Crea o edita un proyecto de apuntes",
             lambda: self.app.navigate("projects")),
            ("📖", "Estudiar Texto", "Convierte texto en flashcards",
             lambda: self.app.navigate("study")),
            ("✍️", "Escribir con mi Letra", "Usa InkCore para generar apuntes",
             lambda: self.app.navigate("inkcore")),
            ("💼", "Nuevo Trabajo", "Registra un trabajo freelance",
             lambda: self.app.navigate("business")),
        ]

        for col_idx, (icon, title, subtitle, cmd) in enumerate(actions):
            col_frame = ctk.CTkFrame(
                actions_frame,
                fg_color="transparent",
            )
            col_frame.grid(row=0, column=col_idx, sticky="ew",
                           padx=theme.SPACE["s"], pady=theme.SPACE["m"])
            actions_frame.columnconfigure(col_idx, weight=1)

            btn = ctk.CTkButton(
                col_frame,
                text=f"{icon}  {title}",
                command=cmd,
                height=52,
                fg_color=theme.ACCENT_PRIMARY,
                hover_color=theme.ACCENT_PRIMARY_HOVER,
                font=theme.get_font("bold", 12),
                corner_radius=theme.RADIUS["m"],
                text_color=theme.ACCENT_TEXT_ON,
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

    def _load_header_banner(self):
        """Banner orbital del header: gradiente espacio profundo + estrellas
        ámbar/cian tenues. Se genera 1 vez con PIL y se cachea en disco por
        tema; la zona izquierda queda plana BG_PRIMARY para asentar el texto.
        """
        try:
            from PIL import Image
        except ImportError:
            return None
        import config
        w, h = 1100, 110
        mode = "light" if theme._LIGHT["BG_PRIMARY"] == theme.BG_PRIMARY else "dark"
        cache_dir = config.DATA_DIR / "cache"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            path = cache_dir / f"dash_header_{w}x{h}_{mode}_v1.png"
            if not path.exists():
                self._render_header_banner(w, h).save(path)
            with Image.open(path) as f:
                pil = f.convert("RGB")
        except Exception:
            return None
        self._banner_image = ctk.CTkImage(light_image=pil, dark_image=pil, size=(w, h))
        return self._banner_image

    @staticmethod
    def _render_header_banner(w: int, h: int):
        """Dibuja el banner con PIL: izquierda plana → gradiente a la derecha
        con ~80 estrellas de 1-2 px (determinista, seed fija)."""
        import random

        from PIL import Image, ImageDraw

        from ui.motion import hex_to_rgb, lerp_color

        base = theme.BG_PRIMARY
        deep = theme.GRADIENT_START
        img = Image.new("RGB", (w, h), hex_to_rgb(base))
        draw = ImageDraw.Draw(img)
        # Gradiente horizontal: plano hasta el 35%, luego funde a "espacio"
        flat_end = int(w * 0.35)
        for x in range(flat_end, w):
            t = (x - flat_end) / max(1, w - flat_end)
            draw.line([(x, 0), (x, h)], fill=hex_to_rgb(lerp_color(base, deep, t)))
        # Estrellas en la zona del gradiente (ámbar/cian tenues + blancas)
        rng = random.Random(42)
        star_colors = [theme.ACCENT_PRIMARY_SOFT, theme.ACCENT_CYAN,
                       theme.TEXT_SECONDARY]
        for _ in range(80):
            x = rng.randint(flat_end + 20, w - 4)
            y = rng.randint(4, h - 4)
            color = hex_to_rgb(lerp_color(
                deep, rng.choice(star_colors), rng.uniform(0.35, 0.9)))
            size = rng.choice((1, 1, 1, 2))
            draw.rectangle([x, y, x + size - 1, y + size - 1], fill=color)
        return img

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

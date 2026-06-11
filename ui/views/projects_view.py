from tkinter import messagebox

import customtkinter as ctk

from core.models import Page, Project
from core.project_manager import ProjectManager
from ui import theme
from ui.components.canvas_editor import CanvasEditor
from ui.views.base_view import BaseView


class ProjectsView(BaseView):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._pm: ProjectManager = app.project_manager
        self._current: Project | None = None
        self._page_index: int = 0
        self._build()

    def _build(self):
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # Left panel — slightly richer background
        left = ctk.CTkFrame(
            outer,
            fg_color=theme.BG_SECONDARY,
            width=280,
            corner_radius=0,
            border_width=0,
        )
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        self._build_project_list(left)

        right = ctk.CTkFrame(outer, fg_color=theme.BG_PRIMARY, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_canvas_area(right)

    def _build_project_list(self, parent):
        # Header row with gradient feel
        header = ctk.CTkFrame(parent, fg_color=theme.BG_PRIMARY, height=56, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="Proyectos",
            font=theme.FONT_HEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(side="left", padx=14, pady=10)

        ctk.CTkButton(
            header, text="+ Nuevo", width=80, height=30,
            fg_color=theme.ACCENT_PRIMARY, hover_color=theme.ACCENT_PRIMARY_HOVER,
            font=theme.FONT_SMALL, corner_radius=8,
            text_color=theme.ACCENT_TEXT_ON,
            command=self._new_project,
        ).pack(side="right", padx=10, pady=10)

        # Thin accent line below header
        ctk.CTkFrame(parent, height=2, fg_color=theme.ACCENT_GREEN, corner_radius=0).pack(fill="x")

        self._search_entry = ctk.CTkEntry(
            parent, placeholder_text="🔍 Buscar...",
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.BORDER,
            font=theme.FONT_SMALL, height=32,
        )
        self._search_entry.pack(fill="x", padx=10, pady=(10, 6))
        self._search_entry.bind("<KeyRelease>", lambda e: self._refresh_list())

        self._list_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._list_scroll.pack(fill="both", expand=True, padx=6)

    def _build_canvas_area(self, parent):
        top_bar = ctk.CTkFrame(
            parent, fg_color=theme.BG_SECONDARY, height=52, corner_radius=0,
        )
        top_bar.pack(fill="x")
        top_bar.pack_propagate(False)

        self._proj_name_entry = ctk.CTkEntry(
            top_bar, placeholder_text="Nombre del proyecto",
            font=theme.FONT_SUBHEADING,
            fg_color="transparent",
            text_color=theme.TEXT_PRIMARY,
            border_width=0, height=36,
        )
        self._proj_name_entry.pack(side="left", padx=16, pady=8, fill="x", expand=True)
        self._proj_name_entry.bind("<FocusOut>", self._save_name)

        page_nav = ctk.CTkFrame(top_bar, fg_color="transparent")
        page_nav.pack(side="right", padx=10)

        ctk.CTkButton(
            page_nav, text="←", width=32, height=32,
            command=self._prev_page,
            fg_color=theme.BG_TERTIARY, font=theme.FONT_BODY, corner_radius=6,
        ).pack(side="left")

        self._page_label = ctk.CTkLabel(
            page_nav, text="Pág 1/1",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY, width=60,
        )
        self._page_label.pack(side="left", padx=4)

        ctk.CTkButton(
            page_nav, text="→", width=32, height=32,
            command=self._next_page,
            fg_color=theme.BG_TERTIARY, font=theme.FONT_BODY, corner_radius=6,
        ).pack(side="left")

        ctk.CTkButton(
            page_nav, text="+ Pág", width=60, height=32,
            command=self._add_page,
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL, corner_radius=6,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            top_bar, text="💾  Guardar",
            command=self._save_project,
            width=100, height=32,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=theme.get_font("bold", 11), corner_radius=8,
        ).pack(side="right", padx=8, pady=10)

        self._canvas_editor = CanvasEditor(parent, on_change=self._on_canvas_change)
        self._canvas_editor.pack(fill="both", expand=True)

        self._empty_label = ctk.CTkLabel(
            parent,
            text="Selecciona o crea un proyecto para comenzar",
            font=theme.FONT_HEADING, text_color=theme.TEXT_MUTED,
        )
        self._empty_label.place(relx=0.5, rely=0.5, anchor="center")

    def _new_project(self):
        proj = Project(name="Nuevo Proyecto")
        self._pm.save(proj)
        self._load_project(proj)
        self._refresh_list()
        self.toast("Proyecto creado", "success")

    def _load_project(self, proj: Project):
        if (self._current and self._current.id != proj.id
                and getattr(self.app.app_state, "unsaved_changes", False)):
            answer = messagebox.askyesnocancel(
                "Cambios sin guardar",
                f"El proyecto «{self._current.name}» tiene cambios sin guardar.\n"
                "¿Deseas guardarlos antes de abrir otro proyecto?",
            )
            if answer is None:
                return
            if answer:
                self._save_project()
        self._current = proj
        self._page_index = 0
        self._proj_name_entry.delete(0, "end")
        self._proj_name_entry.insert(0, proj.name)
        self._update_canvas()
        self._empty_label.place_forget()
        self.app.app_state.current_project = proj
        self.app.app_state.unsaved_changes = False

    def _update_canvas(self):
        if not self._current:
            return
        pages = self._current.pages
        if not pages:
            self._current.pages.append(Page())
        idx = min(self._page_index, len(pages) - 1)
        self._page_index = idx
        self._page_label.configure(text=f"Pág {idx + 1}/{len(pages)}")
        self._canvas_editor.load_page(pages[idx])

    def _on_canvas_change(self):
        if self._current:
            self.app.app_state.unsaved_changes = True

    def _save_project(self):
        if not self._current:
            return
        self._current.name = self._proj_name_entry.get().strip() or "Sin nombre"
        self._pm.save(self._current)
        self.app.app_state.unsaved_changes = False
        self.toast("Proyecto guardado", "success")
        self._refresh_list()

    def _save_name(self, event=None):
        if self._current:
            self._current.name = self._proj_name_entry.get().strip() or "Sin nombre"

    def _prev_page(self):
        if not self._current:
            return
        self._page_index = max(0, self._page_index - 1)
        self._update_canvas()

    def _next_page(self):
        if not self._current:
            return
        self._page_index = min(len(self._current.pages) - 1, self._page_index + 1)
        self._update_canvas()

    def _add_page(self):
        if not self._current:
            return
        new_page = Page(name=f"Página {len(self._current.pages) + 1}")
        self._current.pages.append(new_page)
        self._page_index = len(self._current.pages) - 1
        self._update_canvas()
        self.toast("Página agregada", "success")

    def _refresh_list(self):
        for w in self._list_scroll.winfo_children():
            w.destroy()
        query = self._search_entry.get().lower().strip()
        projects = [p for p in self._pm.list_projects() if query in p.name.lower()]
        if not projects:
            ctk.CTkLabel(
                self._list_scroll, text="Sin proyectos",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=20)
            return

        for proj in projects:
            is_current = self._current and proj.id == self._current.id
            status = getattr(proj, "status", "Borrador")
            status_color = theme.STATUS_COLORS.get(status, theme.ACCENT_BLUE)
            border_c = status_color if is_current else theme.CARD_BORDER

            card = ctk.CTkFrame(
                self._list_scroll,
                fg_color=theme.CARD_BG if not is_current else theme.CARD_BG_HOVER,
                corner_radius=10,
                border_width=1,
                border_color=border_c,
                cursor="hand2",
            )
            card.pack(fill="x", pady=4)

            # Left status stripe
            stripe = ctk.CTkFrame(card, fg_color=status_color, width=4, corner_radius=2)
            stripe.pack(side="left", fill="y", padx=(0, 0))

            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(side="left", fill="both", expand=True, padx=8, pady=8)

            name_row = ctk.CTkFrame(body, fg_color="transparent")
            name_row.pack(fill="x")

            ctk.CTkLabel(
                name_row, text=proj.name[:22],
                font=theme.FONT_BODY, text_color=theme.TEXT_PRIMARY,
            ).pack(side="left", anchor="w")

            ctk.CTkButton(
                name_row, text="\u00d7", width=22, height=22,
                font=theme.get_font(size=13),
                fg_color="transparent", hover_color=theme.ACCENT_RED,
                text_color=theme.TEXT_MUTED,
                command=lambda p=proj: self._delete_project(p),
            ).pack(side="right")

            pages_count = len(proj.pages)
            ctk.CTkLabel(
                body,
                text=f"📄 {pages_count} pág  •  {proj.modified_at[:10]}",
                font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            ).pack(anchor="w", pady=(2, 0))

            for widget in (card, body, name_row):
                widget.bind("<Button-1>", lambda e, p=proj: self._load_project(p))
                widget.bind("<Enter>", lambda e, c=card, sc=status_color: c.configure(
                    fg_color=theme.CARD_BG_HOVER, border_color=sc), add="+")
                widget.bind("<Leave>", lambda e, c=card, bc=border_c: c.configure(
                    fg_color=theme.CARD_BG, border_color=bc), add="+")

    def _delete_project(self, proj: Project):
        if messagebox.askyesno("Eliminar", f"¿Eliminar '{proj.name}'?"):
            self._pm.delete(proj.id)
            if self._current and self._current.id == proj.id:
                self._current = None
                self._empty_label.place(relx=0.5, rely=0.5, anchor="center")
            self._refresh_list()
            self.toast("Proyecto eliminado", "info")

    def on_show(self):
        self._refresh_list()
        if (self.app.app_state.current_project
                and (not self._current
                     or self._current.id != self.app.app_state.current_project.id)):
            self._load_project(self.app.app_state.current_project)

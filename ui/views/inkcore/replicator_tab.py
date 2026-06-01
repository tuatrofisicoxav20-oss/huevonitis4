"""ReplicatorTabMixin — tab 🔁 Reproducir apunte (MVP v4.2)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class ReplicatorTabMixin:
    """Tab: cargar apunte → analizar → re-renderizar con el perfil activo."""

    def _build_replicator(self, parent):
        # Estado
        self._repl_image_path: str | None = None
        self._repl_layout = None
        self._repl_rendered = None
        self._repl_block_vars: list = []
        self._repl_original_photo = None
        self._repl_rendered_photo = None

        main = ctk.CTkFrame(parent, fg_color="transparent")
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=30)
        main.columnconfigure(1, weight=44)
        main.columnconfigure(2, weight=26)
        main.rowconfigure(0, weight=1)

        # Panel izquierdo: carga + sliders
        left = self.card_frame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._build_repl_left(left)

        # Centro: preview lado a lado
        center = self.card_frame(main)
        center.grid(row=0, column=1, sticky="nsew", padx=6)
        self._build_repl_center(center)

        # Derecha: bloques detectados con toggles
        right = self.card_frame(main)
        right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        self._build_repl_right(right)

    def _build_repl_left(self, parent):
        ctk.CTkLabel(
            parent, text="📥  Cargar apunte",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(padx=14, pady=(14, 4), anchor="w")

        ctk.CTkLabel(
            parent,
            text="Sube una imagen de un apunte ajeno y la reproducimos con la letra "
                 "de tu perfil activo. MVP: maneja texto + recuadros. Fórmulas/dibujos "
                 "se preservan como bitmap.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            wraplength=240, justify="left",
        ).pack(padx=14, pady=(0, 8), anchor="w")

        self.primary_button(parent, "📷 Elegir imagen…", self._repl_load_image, width=200).pack(
            padx=14, pady=4, anchor="w",
        )

        self._repl_image_name = ctk.CTkLabel(
            parent, text="Sin imagen cargada",
            font=theme.FONT_SMALL, text_color=theme.ACCENT_RED,
        )
        self._repl_image_name.pack(padx=14, pady=(2, 8), anchor="w")

        # Slider de fidelidad
        ctk.CTkLabel(
            parent, text="Fidelidad (0=todo replicado, 100=copia exacta)",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(padx=14, pady=(8, 2), anchor="w")
        slider_row = ctk.CTkFrame(parent, fg_color="transparent")
        slider_row.pack(fill="x", padx=14, pady=2)
        self._repl_fidelity = ctk.CTkSlider(
            slider_row, from_=0, to=100, number_of_steps=20,
            progress_color=theme.ACCENT_ORANGE,
            button_color=theme.ACCENT_ORANGE,
            button_hover_color=theme.ACCENT_ORANGE_HOVER,
        )
        self._repl_fidelity.set(0)
        self._repl_fidelity.pack(side="left", fill="x", expand=True)
        self._repl_fidelity_lbl = ctk.CTkLabel(
            slider_row, text="0%", width=40,
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._repl_fidelity_lbl.pack(side="left", padx=4)
        self._repl_fidelity.configure(
            command=lambda v: self._repl_fidelity_lbl.configure(text=f"{int(float(v))}%"),
        )

        ctk.CTkButton(
            parent, text="🔎  Analizar imagen", height=38,
            fg_color=theme.ACCENT_ORANGE, hover_color=theme.ACCENT_ORANGE_HOVER,
            font=("Segoe UI", 12, "bold"), corner_radius=8,
            command=self._repl_analyze,
        ).pack(padx=14, pady=(14, 4), fill="x")

        ctk.CTkButton(
            parent, text="✨  Re-renderizar con mi letra", height=38,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 12, "bold"), corner_radius=8,
            command=self._repl_render,
        ).pack(padx=14, pady=4, fill="x")

        ctk.CTkButton(
            parent, text="✏️  Editar y retocar…", height=34,
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
            command=self._repl_open_editor,
        ).pack(padx=14, pady=(4, 2), fill="x")

        ctk.CTkButton(
            parent, text="📥  Exportar resultado", height=34,
            fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.FONT_SMALL,
            command=self._repl_export,
        ).pack(padx=14, pady=(2, 14), fill="x")

        self._repl_status = ctk.CTkLabel(
            parent, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            wraplength=240, justify="left",
        )
        self._repl_status.pack(padx=14, pady=(0, 8), anchor="w")

    def _build_repl_center(self, parent):
        ctk.CTkLabel(
            parent, text="Original  ↔  Reproducido",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(padx=14, pady=(14, 4))

        previews_row = ctk.CTkFrame(parent, fg_color="transparent")
        previews_row.pack(fill="both", expand=True, padx=8, pady=4)
        previews_row.columnconfigure(0, weight=1)
        previews_row.columnconfigure(1, weight=1)

        self._repl_original_lbl = ctk.CTkLabel(
            previews_row, text="(Sin imagen)\nCarga un apunte\npara empezar",
            fg_color=theme.BG_TERTIARY, corner_radius=8,
            text_color=theme.TEXT_MUTED, justify="center",
        )
        self._repl_original_lbl.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._repl_rendered_lbl = ctk.CTkLabel(
            previews_row, text="(Aún no se ha reproducido)",
            fg_color=theme.BG_TERTIARY, corner_radius=8,
            text_color=theme.TEXT_MUTED, justify="center",
        )
        self._repl_rendered_lbl.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        previews_row.rowconfigure(0, weight=1)

    def _build_repl_right(self, parent):
        ctk.CTkLabel(
            parent, text="📋 Bloques detectados",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(padx=14, pady=(14, 4), anchor="w")
        ctk.CTkLabel(
            parent,
            text="Desmarca los bloques que NO quieres replicar.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            wraplength=220, justify="left",
        ).pack(padx=14, pady=(0, 4), anchor="w")
        self._repl_blocks_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._repl_blocks_scroll.pack(fill="both", expand=True, padx=8, pady=4)
        self._repl_no_blocks_lbl = ctk.CTkLabel(
            self._repl_blocks_scroll,
            text="Analiza una imagen para ver los bloques.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._repl_no_blocks_lbl.pack(pady=20)

    # ── Logic ────────────────────────────────────────────────────

    def _repl_load_image(self):
        path = filedialog.askopenfilename(
            title="Elegir apunte a reproducir",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp")],
        )
        if not path:
            return
        self._repl_image_path = path
        self._repl_image_name.configure(
            text=f"✓ {Path(path).name}", text_color=theme.ACCENT_GREEN,
        )
        self._repl_layout = None
        self._repl_rendered = None
        self._show_repl_original_preview(path)
        self._show_repl_rendered_preview(None)
        self._repl_status.configure(
            text="Imagen cargada. Pulsa 'Analizar imagen' para detectar bloques.",
            text_color=theme.TEXT_SECONDARY,
        )

    def _show_repl_original_preview(self, path: str):
        if not _PIL_OK or not Path(path).exists():
            return
        try:
            img = Image.open(path).convert("RGB")
            img.thumbnail((420, 540), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._repl_original_lbl.configure(image=photo, text="")
            self._repl_original_photo = photo
        except Exception as exc:
            logger.warning("show_repl_original_preview falló: %s", exc)

    def _show_repl_rendered_preview(self, img):
        if img is None:
            self._repl_rendered_lbl.configure(image="", text="(Aún no se ha reproducido)")
            self._repl_rendered_photo = None
            return
        try:
            preview = img.copy()
            preview.thumbnail((420, 540), Image.LANCZOS)
            photo = ImageTk.PhotoImage(preview)
            self._repl_rendered_lbl.configure(image=photo, text="")
            self._repl_rendered_photo = photo
        except Exception as exc:
            logger.warning("show_repl_rendered_preview falló: %s", exc)

    def _repl_analyze(self):
        if not self._repl_image_path:
            self.toast("Carga una imagen primero", "warning")
            return
        self._repl_status.configure(
            text="🔎 Analizando bloques…", text_color=theme.ACCENT_ORANGE,
        )
        path = self._repl_image_path

        def worker():
            try:
                from core.inkcore.replicator import NoteReplicator
                rep = NoteReplicator(self._pipeline.bank)
                layout = rep.analyze(path)
            except Exception as exc:
                logger.error("repl_analyze worker: %s", exc, exc_info=True)
                layout = None

            def _done():
                if layout is None:
                    self._repl_status.configure(
                        text="⚠ No se pudo analizar (¿cv2/tesseract instalados?)",
                        text_color=theme.ACCENT_RED,
                    )
                    self.toast("Análisis falló — revisa el log", "error")
                    return
                self._repl_layout = layout
                self._repl_render_block_list(layout)
                n_text = sum(1 for b in layout.blocks if b.type == "text")
                n_rect = sum(1 for b in layout.blocks if b.type == "rect")
                self._repl_status.configure(
                    text=f"✓ {len(layout.blocks)} bloques ({n_text} texto, {n_rect} recuadros)",
                    text_color=theme.ACCENT_GREEN,
                )
                self.toast(f"{len(layout.blocks)} bloques detectados", "success")

            if self.winfo_exists():
                self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

    def _repl_render_block_list(self, layout):
        for w in self._repl_blocks_scroll.winfo_children():
            w.destroy()
        self._repl_block_vars.clear()
        if not layout.blocks:
            ctk.CTkLabel(
                self._repl_blocks_scroll,
                text="Sin bloques detectados.",
                font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            ).pack(pady=10)
            return
        for block in layout.blocks:
            row = ctk.CTkFrame(
                self._repl_blocks_scroll, fg_color=theme.BG_TERTIARY,
                corner_radius=4,
            )
            row.pack(fill="x", pady=2)
            var = ctk.BooleanVar(value=True)
            self._repl_block_vars.append((block, var))

            def _on_toggle(b=block, v=var):
                b.enabled = bool(v.get())

            ctk.CTkCheckBox(
                row, text="", variable=var, width=20,
                fg_color=theme.ACCENT_BLUE,
                command=_on_toggle,
            ).pack(side="left", padx=4, pady=4)
            icon = "📝" if block.type == "text" else "▭" if block.type == "rect" else "🖼️"
            ctk.CTkLabel(
                row, text=f"{icon} {block.label}",
                font=theme.FONT_SMALL, text_color=theme.TEXT_PRIMARY,
                wraplength=180, justify="left",
            ).pack(side="left", padx=4, pady=4)

    def _repl_render(self):
        if self._repl_layout is None:
            self.toast("Primero analiza una imagen", "warning")
            return
        fidelity = int(float(self._repl_fidelity.get()))
        self._repl_status.configure(
            text="✨ Re-renderizando…", text_color=theme.ACCENT_ORANGE,
        )
        layout = self._repl_layout

        def worker():
            try:
                from core.inkcore.replicator import NoteReplicator
                rep = NoteReplicator(self._pipeline.bank)
                rendered = rep.render(layout, fidelity=fidelity)
            except Exception as exc:
                logger.error("repl_render worker: %s", exc, exc_info=True)
                rendered = None

            def _done():
                if rendered is None:
                    self._repl_status.configure(
                        text="⚠ Render falló — revisa el log",
                        text_color=theme.ACCENT_RED,
                    )
                    self.toast("Render falló", "error")
                    return
                self._repl_rendered = rendered
                self._show_repl_rendered_preview(rendered)
                self._repl_status.configure(
                    text=f"✓ Reproducido con fidelidad {fidelity}%",
                    text_color=theme.ACCENT_GREEN,
                )
                self.toast("Apunte reproducido", "success")

            if self.winfo_exists():
                self.after(0, _done)

        threading.Thread(target=worker, daemon=True).start()

    def _repl_export(self):
        if self._repl_rendered is None:
            self.toast("Primero genera un render", "warning")
            return
        path = filedialog.asksaveasfilename(
            title="Exportar resultado",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf")],
        )
        if not path:
            return
        try:
            from core.inkcore.replicator import export_replicated
            out = export_replicated(self._repl_rendered, path)
            self.toast(f"Exportado: {Path(out).name}", "success")
        except Exception as exc:
            logger.error("repl_export: %s", exc, exc_info=True)
            self.toast(f"Export falló: {exc}", "error")

    # ── Edición interactiva (Fase 2) ─────────────────────────────

    def _repl_open_editor(self):
        """Abre el apunte detectado en un editor de canvas para retocarlo.

        Convierte los bloques (respetando los toggles del panel derecho) en una
        Page editable, la carga en un CanvasEditor en una ventana aparte y
        permite mover/agregar/borrar/editar texto antes de exportar con la letra
        del perfil. El canvas muestra el texto con fuente normal; el export final
        lo re-escribe con el banco.
        """
        if self._repl_layout is None:
            self.toast("Primero analiza una imagen", "warning")
            return
        try:
            from core.inkcore.replicator_edit import layout_to_page
            from ui.components.canvas_editor import CanvasEditor
        except Exception as exc:
            logger.error("_repl_open_editor import: %s", exc, exc_info=True)
            self.toast("No se pudo abrir el editor", "error")
            return

        page = layout_to_page(self._repl_layout)
        if not page.elements:
            self.toast("No hay bloques editables (analiza primero)", "warning")
            return
        self._repl_edit_page = page

        win = ctk.CTkToplevel(self)
        win.title("✏️ Retocar apunte — mover / agregar / borrar bloques")
        win.geometry("1100x760")
        win.transient(self.winfo_toplevel())

        bar = ctk.CTkFrame(win, fg_color=theme.BG_TERTIARY, height=46)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkLabel(
            bar,
            text="Arrastra para mover · doble clic para editar texto · herramientas T/▭/línea arriba",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=12)
        ctk.CTkButton(
            bar, text="📥  Exportar con mi letra", height=32,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 12, "bold"),
            command=lambda: self._repl_export_edited(page),
        ).pack(side="right", padx=10, pady=7)

        editor = CanvasEditor(win)
        editor.pack(fill="both", expand=True)
        editor.load_page(page)
        self._repl_editor = editor

    def _repl_export_edited(self, page):
        """Renderiza la Page editada con la letra del banco y la exporta."""
        from tkinter import filedialog
        try:
            from core.inkcore.replicator import export_replicated
            from core.inkcore.replicator_edit import render_page_handwritten
        except Exception as exc:
            logger.error("_repl_export_edited import: %s", exc, exc_info=True)
            self.toast("Export no disponible", "error")
            return

        img = render_page_handwritten(page, self._pipeline.bank)
        if img is None:
            self.toast("No se pudo renderizar (¿PIL?)", "error")
            return
        # Reflejar el resultado en la preview principal del tab
        self._repl_rendered = img
        self._show_repl_rendered_preview(img)

        path = filedialog.asksaveasfilename(
            title="Exportar apunte retocado",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf")],
        )
        if not path:
            self.toast("Render listo (no exportado)", "info")
            return
        try:
            out = export_replicated(img, path)
            self.toast(f"Exportado: {Path(out).name}", "success")
        except Exception as exc:
            logger.error("_repl_export_edited: %s", exc, exc_info=True)
            self.toast(f"Export falló: {exc}", "error")

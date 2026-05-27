import copy
import tkinter as tk

import customtkinter as ctk

from core.models import LineElement, Page, RectElement, TextElement
from ui import theme

_IMG_CACHE_MAX = 50


class CanvasEditor(ctk.CTkFrame):
    def __init__(self, parent, on_change=None, **kwargs):
        super().__init__(parent, fg_color=theme.BG_SECONDARY, **kwargs)
        self.on_change = on_change
        self._page: Page | None = None
        self._selected_id: str | None = None
        self._tool = "select"
        self._zoom = 1.0
        self._drag_start = None
        self._drag_offset = (0, 0)
        self._rect_start = None
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._canvas_images: dict = {}
        self._img_cache: dict = {}  # (path, w, h) → PhotoImage, FIFO max 50
        self._build()

    def _build(self):
        toolbar = ctk.CTkFrame(self, fg_color=theme.BG_TERTIARY, height=44)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        tools = [
            ("select", "⬡ Seleccionar", "S"),
            ("text", "T Texto", "T"),
            ("rect", "▭ Rect", "R"),
            ("line", "\u2571 Línea", "L"),
        ]
        self._tool_buttons: dict = {}
        for tool_id, label, _ in tools:
            btn = ctk.CTkButton(
                toolbar, text=label, width=90, height=32,
                font=theme.FONT_SMALL,
                fg_color=theme.ACCENT_BLUE if tool_id == "select" else theme.BG_SECONDARY,
                hover_color=theme.ACCENT_BLUE_HOVER,
                text_color=theme.TEXT_PRIMARY,
                corner_radius=6,
                command=lambda t=tool_id: self.set_tool(t),
            )
            btn.pack(side="left", padx=4, pady=6)
            self._tool_buttons[tool_id] = btn

        zoom_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        zoom_frame.pack(side="right", padx=8)
        ctk.CTkButton(zoom_frame, text="\u2212", width=28, height=28, font=("Segoe UI", 14),
                      fg_color=theme.BG_SECONDARY, command=self._zoom_out).pack(side="left")
        self._zoom_label = ctk.CTkLabel(zoom_frame, text="100%", font=theme.FONT_SMALL,
                                        text_color=theme.TEXT_SECONDARY, width=44)
        self._zoom_label.pack(side="left")
        ctk.CTkButton(zoom_frame, text="+", width=28, height=28, font=("Segoe UI", 14),
                      fg_color=theme.BG_SECONDARY, command=self._zoom_in).pack(side="left")

        canvas_frame = ctk.CTkFrame(self, fg_color=theme.BG_PRIMARY, corner_radius=0)
        canvas_frame.pack(fill="both", expand=True)

        self._hbar = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        self._hbar.pack(side="bottom", fill="x")
        self._vbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        self._vbar.pack(side="right", fill="y")

        self._canvas = tk.Canvas(
            canvas_frame,
            bg=theme.BG_PRIMARY,
            highlightthickness=0,
            xscrollcommand=self._hbar.set,
            yscrollcommand=self._vbar.set,
        )
        self._canvas.pack(fill="both", expand=True)
        self._hbar.config(command=self._canvas.xview)
        self._vbar.config(command=self._canvas.yview)

        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Double-Button-1>", self._on_double_click)
        self._canvas.bind("<MouseWheel>", self._on_scroll)
        self._canvas.bind("<Control-z>", lambda e: self.undo())
        self._canvas.bind("<Control-y>", lambda e: self.redo())
        self._canvas.focus_set()
        self.bind("<Destroy>", self._on_destroy)

        props_frame = ctk.CTkFrame(self, fg_color=theme.BG_TERTIARY, height=50)
        props_frame.pack(fill="x")
        props_frame.pack_propagate(False)

        self._props_label = ctk.CTkLabel(
            props_frame, text="Selecciona un elemento para editar sus propiedades",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        )
        self._props_label.pack(side="left", padx=12, pady=6)
        self._props_entries: dict = {}

        ctk.CTkButton(
            props_frame, text="🗑 Eliminar", width=90, height=32,
            fg_color=theme.ACCENT_RED, hover_color="#DC2626",
            font=theme.FONT_SMALL, command=self._delete_selected,
        ).pack(side="right", padx=8, pady=6)

    def load_page(self, page: Page):
        self._page = page
        self._selected_id = None
        # BUG-01: limpiar historial al cambiar de página/proyecto. Sin esto
        # Ctrl+Z pushea elementos deep-copied de OTRA página al actual,
        # corrompiendo la página visible.
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.redraw()

    def set_tool(self, tool_id: str):
        self._tool = tool_id
        for tid, btn in self._tool_buttons.items():
            btn.configure(
                fg_color=theme.ACCENT_BLUE if tid == tool_id else theme.BG_SECONDARY
            )

    def redraw(self):
        if not self._page:
            return
        self._canvas.delete("all")
        self._canvas_images.clear()
        z = self._zoom
        pw = int(self._page.width * z)
        ph = int(self._page.height * z)
        ox, oy = 30, 30

        self._canvas.configure(scrollregion=(0, 0, pw + 60, ph + 60))
        self._canvas.create_rectangle(ox, oy, ox + pw, oy + ph,
                                      fill=self._page.background_color, outline="#888888", width=1)
        self._draw_grid(ox, oy, pw, ph)

        for el in self._page.elements:
            if not el.visible:
                continue
            self._draw_element(el, ox, oy, z)

    def _draw_grid(self, ox, oy, pw, ph):
        grid_size = int(20 * self._zoom)
        for x in range(0, pw, grid_size):
            self._canvas.create_line(ox + x, oy, ox + x, oy + ph, fill="#E8E8E8", width=1, dash=(2, 8))
        for y in range(0, ph, grid_size):
            self._canvas.create_line(ox, oy + y, ox + pw, oy + y, fill="#E8E8E8", width=1, dash=(2, 8))

    def _draw_element(self, el, ox, oy, z):
        x1 = ox + el.x * z
        y1 = oy + el.y * z
        x2 = x1 + el.width * z
        y2 = y1 + el.height * z
        selected = el.id == self._selected_id

        if hasattr(el, 'fill_color'):
            self._canvas.create_rectangle(
                x1, y1, x2, y2,
                fill=el.fill_color, outline=el.border_color,
                width=el.border_width if not selected else 2,
                tags=("element", el.id),
            )
        elif hasattr(el, 'text'):
            self._canvas.create_rectangle(x1, y1, x2, y2,
                                          fill="#FFFFFF" if not selected else "#EEF4FF",
                                          outline="#AAAAAA" if not selected else theme.ACCENT_BLUE,
                                          width=1 if not selected else 2,
                                          tags=("element", el.id))
            font_size = max(8, int(el.font_size * z))
            self._canvas.create_text(
                x1 + 4, y1 + 4, text=el.text, anchor="nw",
                font=(el.font_family, font_size),
                fill=el.color, width=el.width * z - 8,
                tags=("element", el.id),
            )
        elif hasattr(el, 'x2'):
            x2e = ox + el.x2 * z
            y2e = oy + el.y2 * z
            self._canvas.create_line(x1, y1, x2e, y2e,
                                     fill=el.color, width=max(1, int(el.line_width * z)),
                                     tags=("element", el.id))
        elif hasattr(el, 'image_path') and el.image_path:
            try:
                from PIL import Image, ImageTk
                tw, th = int(el.width * z), int(el.height * z)
                cache_key = (el.image_path, tw, th)
                photo = self._img_cache.get(cache_key)
                if photo is None:
                    img = Image.open(el.image_path).resize((tw, th))
                    photo = ImageTk.PhotoImage(img)
                    if len(self._img_cache) >= _IMG_CACHE_MAX:
                        self._img_cache.pop(next(iter(self._img_cache)))
                    self._img_cache[cache_key] = photo
                self._canvas_images[el.id] = photo
                self._canvas.create_image(x1, y1, anchor="nw", image=photo, tags=("element", el.id))
            except Exception:
                self._canvas.create_rectangle(x1, y1, x2, y2, fill="#CCCCCC", outline="#999999",
                                              tags=("element", el.id))
                self._canvas.create_text((x1+x2)//2, (y1+y2)//2, text="[img]", tags=("element", el.id))

        if selected:
            hw = 7
            for hx, hy in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
                self._canvas.create_rectangle(
                    hx - hw, hy - hw, hx + hw, hy + hw,
                    fill=theme.ACCENT_BLUE, outline="white", width=1,
                )

    def _on_click(self, event):
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        if self._tool == "select":
            self._try_select(cx, cy)
        elif self._tool == "text":
            self._create_text(cx, cy)
        elif self._tool == "rect" or self._tool == "line":
            self._rect_start = (cx, cy)

    def _try_select(self, cx, cy):
        if not self._page:
            return
        z = self._zoom
        ox, oy = 30, 30
        best = None
        for el in reversed(self._page.elements):
            x1 = ox + el.x * z
            y1 = oy + el.y * z
            x2 = x1 + el.width * z
            y2 = y1 + el.height * z
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                best = el
                break
        if best:
            self._selected_id = best.id
            self._drag_start = (cx, cy)
            self._drag_offset = (cx - (30 + best.x * z), cy - (30 + best.y * z))
            self._push_undo()
            self._show_props(best)
        else:
            self._selected_id = None
            self._props_label.configure(text="Selecciona un elemento para editar sus propiedades")
        self.redraw()

    def _on_drag(self, event):
        if not self._page or not self._selected_id or self._tool != "select":
            return
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        z = self._zoom
        for el in self._page.elements:
            if el.id == self._selected_id and not el.locked:
                el.x = max(0, (cx - 30 - self._drag_offset[0]) / z)
                el.y = max(0, (cy - 30 - self._drag_offset[1]) / z)
                break
        self.redraw()

    def _on_release(self, event):
        if self._tool in ("rect", "line") and self._rect_start:
            cx = self._canvas.canvasx(event.x)
            cy = self._canvas.canvasy(event.y)
            sx, sy = self._rect_start
            self._rect_start = None
            z = self._zoom
            ox, oy = 30, 30
            x = (min(sx, cx) - ox) / z
            y = (min(sy, cy) - oy) / z
            w = abs(cx - sx) / z
            h = abs(cy - sy) / z
            if w < 5 or h < 5:
                return
            if self._tool == "rect":
                el = RectElement(x=x, y=y, width=w, height=h)
            else:
                el = LineElement(x=x, y=y, width=w, height=h, x2=x + w, y2=y + h)
            self._push_undo()
            self._page.elements.append(el)
            self._selected_id = el.id
            self.redraw()
            self._notify_change()
        elif self._tool == "select" and self._drag_start:
            self._notify_change()
        self._drag_start = None

    def _on_double_click(self, event):
        if self._selected_id and self._tool == "select":
            for el in self._page.elements:
                if el.id == self._selected_id and hasattr(el, 'text'):
                    self._edit_text_dialog(el)
                    break

    def _on_scroll(self, event):
        if event.delta > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    def _create_text(self, cx, cy):
        if not self._page:
            return
        z = self._zoom
        x = (cx - 30) / z
        y = (cy - 30) / z
        el = TextElement(x=x, y=y, text="Nuevo texto", width=180, height=40)
        self._push_undo()
        self._page.elements.append(el)
        self._selected_id = el.id
        self.redraw()
        self._edit_text_dialog(el)
        self._notify_change()

    def _edit_text_dialog(self, el):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Editar texto")
        dlg.geometry("380x200")
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Texto:", font=theme.FONT_BODY).pack(padx=16, pady=(16, 4), anchor="w")
        entry = ctk.CTkTextbox(dlg, height=80, font=theme.FONT_BODY)
        entry.pack(fill="x", padx=16)
        entry.insert("0.0", el.text)

        def apply():
            self._push_undo()
            el.text = entry.get("0.0", "end").strip()
            dlg.destroy()
            self.redraw()
            self._notify_change()

        ctk.CTkButton(dlg, text="Aplicar", command=apply, fg_color=theme.ACCENT_BLUE).pack(pady=12)

    def _delete_selected(self):
        if not self._selected_id or not self._page:
            return
        self._push_undo()
        self._page.elements = [e for e in self._page.elements if e.id != self._selected_id]
        self._selected_id = None
        self.redraw()
        self._notify_change()

    def _show_props(self, el):
        info_parts = [f"ID: {el.id[:8]}..."]
        info_parts.append(f"Pos: ({int(el.x)}, {int(el.y)})")
        info_parts.append(f"Tam: {int(el.width)}\u00d7{int(el.height)}")
        if hasattr(el, 'text'):
            info_parts.append(f"Texto: {el.text[:20]}")
        self._props_label.configure(text="  |  ".join(info_parts), text_color=theme.TEXT_SECONDARY)

    def _zoom_in(self):
        self._zoom = min(3.0, self._zoom + 0.1)
        self._zoom_label.configure(text=f"{int(self._zoom * 100)}%")
        self.redraw()

    def _zoom_out(self):
        self._zoom = max(0.2, self._zoom - 0.1)
        self._zoom_label.configure(text=f"{int(self._zoom * 100)}%")
        self.redraw()

    def _push_undo(self):
        if not self._page:
            return
        self._undo_stack.append(copy.deepcopy(self._page.elements))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack or not self._page:
            return
        self._redo_stack.append(self._page.elements)
        self._page.elements = self._undo_stack.pop()
        self._selected_id = None
        self.redraw()

    def redo(self):
        if not self._redo_stack or not self._page:
            return
        self._undo_stack.append(self._page.elements)
        self._page.elements = self._redo_stack.pop()
        self.redraw()

    def _on_destroy(self, event):
        """Unbind all canvas events when the widget is destroyed."""
        if event.widget is not self:
            return
        try:
            for seq in ("<Button-1>", "<B1-Motion>", "<ButtonRelease-1>",
                        "<Double-Button-1>", "<MouseWheel>", "<Control-z>", "<Control-y>"):
                self._canvas.unbind(seq)
        except Exception:
            pass

    def _notify_change(self):
        if self.on_change:
            self.on_change()

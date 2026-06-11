"""BankCellsMixin — celdas del Banco dibujadas en canvas (U4).

En este equipo (Tk 9 + XWayland) CADA widget cuesta ~100-200 ms de primer
pintado: una celda de 4 widgets CTk salía a ~1 s y el grid era inutilizable.
Solución: el body de cada sección es UN solo tk.Canvas y cada celda son 4
ITEMS de canvas (rect del anillo de tier + thumb + texto + barra de calidad)
— prácticamente gratis de crear y de re-acomodar.

Interacción sobre el canvas: <Motion> resuelve la celda bajo el cursor y
coloca la barra flotante compartida de acciones (pen/tier/trash); click
alterna selección en modo selección (anillo cian). Los thumbs salen del
cache de disco (core/inkcore/thumb_cache, 64px) vía ImageTk.
"""
import contextlib
import logging
import threading
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from core.inkcore import thumb_cache
from ui import icons, theme
from ui.motion import hex_to_rgb

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

CELL_W, CELL_H = 80, 100
GAP = 6
COLS = 8


def _tier_ring(tier: str) -> str:
    return {
        "Gold": theme.ACCENT_PRIMARY,
        "Silver": theme.TIER_COLORS["Silver"],
        "Bronze": theme.TIER_COLORS["Bronze"],
    }.get(tier, theme.BORDER)


def _cell_xy(idx: int) -> tuple[int, int]:
    r, c = divmod(idx, COLS)
    return GAP + c * (CELL_W + GAP), GAP + r * (CELL_H + GAP)


class BankCellsMixin:
    """Celdas canvas del grid del banco: dibujo, thumbs, hover y selección."""

    # ── Body (canvas por sección) ──────────────────────────────────

    def _bank_make_body(self, sec: dict) -> None:
        body = tk.Canvas(
            self._bank_scroll, highlightthickness=0,
            bg=theme.BG_PRIMARY, height=GAP,
            width=GAP + COLS * (CELL_W + GAP), bd=0,
        )
        body.bind("<Motion>", lambda e, s=sec: self._bank_canvas_motion(s, e))
        body.bind("<Leave>", lambda _e: self._bank_hover_hide())
        body.bind("<Button-1>", lambda e, s=sec: self._bank_canvas_click(s, e))
        sec["body"] = body
        sec["cells"] = {}
        sec["order"] = []

    def _bank_cell_at(self, sec: dict, x: int, y: int) -> str | None:
        """image_path de la celda bajo (x, y) del canvas, o None."""
        col = (x - GAP) // (CELL_W + GAP)
        row = (y - GAP) // (CELL_H + GAP)
        if col < 0 or col >= COLS or row < 0:
            return None
        if (x - GAP) % (CELL_W + GAP) > CELL_W or (y - GAP) % (CELL_H + GAP) > CELL_H:
            return None  # cayó en el gap
        idx = row * COLS + col
        order = sec.get("order") or []
        return order[idx] if idx < len(order) else None

    # ── Celdas (items de canvas) ───────────────────────────────────

    def _bank_destroy_cell(self, sec: dict, path: str) -> None:
        cell = sec["cells"].pop(path, None)
        body = sec.get("body")
        if cell and body is not None:
            with contextlib.suppress(Exception):
                for item in cell["items"]:
                    body.delete(item)

    def _bank_build_cell(self, sec: dict, glyph) -> None:
        """4 items: rect del anillo, thumb, texto char·calidad y barra."""
        body = sec["body"]
        x, y = _cell_xy(len(sec["cells"]))  # posición provisional; regrid acomoda
        ring = _tier_ring(glyph.tier)
        rect = body.create_rectangle(
            x, y, x + CELL_W, y + CELL_H,
            outline=ring, width=2, fill=theme.CARD_BG)
        photo = self._bank_thumb(glyph.image_path)
        if photo is not None:
            img_item = body.create_image(x + CELL_W // 2, y + 38, image=photo)
        else:
            img_item = body.create_text(
                x + CELL_W // 2, y + 38, text=glyph.char,
                font=theme.get_font(size=20), fill=theme.TEXT_PRIMARY)
        txt = body.create_text(
            x + CELL_W // 2, y + CELL_H - 18,
            text=f"{glyph.char} · {glyph.quality_score:.0%}",
            font=theme.FONT_SMALL, fill=theme.TEXT_SECONDARY)
        qw = max(6, int((CELL_W - 12) * glyph.quality_score))
        qbar = body.create_rectangle(
            x + 6, y + CELL_H - 8, x + 6 + qw, y + CELL_H - 5,
            outline="", fill=ring)
        sec["cells"][glyph.image_path] = {
            "glyph": glyph, "items": (rect, img_item, txt, qbar),
            "photo": photo,
        }
        self._bank_apply_selection_visual(sec, glyph.image_path)

    def _bank_update_cell(self, sec: dict, path: str, glyph) -> None:
        cell = sec["cells"].get(path)
        if cell is None:
            self._bank_build_cell(sec, glyph)
            return
        body = sec["body"]
        cell["glyph"] = glyph
        _rect, _img, txt, qbar = cell["items"]
        with contextlib.suppress(Exception):
            body.itemconfigure(txt, text=f"{glyph.char} · {glyph.quality_score:.0%}")
            body.itemconfigure(qbar, fill=_tier_ring(glyph.tier))
        self._bank_apply_selection_visual(sec, path)

    def _bank_regrid(self, sec: dict, order: list) -> None:
        """Reacomoda los items por índice y ajusta la altura del canvas."""
        body = sec.get("body")
        if body is None:
            return
        sec["order"] = [p for p in order if p in sec["cells"]]
        for i, path in enumerate(sec["order"]):
            cell = sec["cells"][path]
            x, y = _cell_xy(i)
            rect, img, txt, qbar = cell["items"]
            g = cell["glyph"]
            qw = max(6, int((CELL_W - 12) * g.quality_score))
            with contextlib.suppress(Exception):
                body.coords(rect, x, y, x + CELL_W, y + CELL_H)
                body.coords(img, x + CELL_W // 2, y + 38)
                body.coords(txt, x + CELL_W // 2, y + CELL_H - 18)
                body.coords(qbar, x + 6, y + CELL_H - 8, x + 6 + qw, y + CELL_H - 5)
        rows = max(1, -(-len(sec["order"]) // COLS))
        body.configure(height=GAP + rows * (CELL_H + GAP))

    # ── Thumbs (disco → ImageTk) ───────────────────────────────────

    def _bank_thumb(self, image_path: str):
        if not PIL_OK:
            return None
        try:
            bank_dir = self._pipeline.bank.bank_dir
        except Exception:
            return None
        tpath = thumb_cache.ensure_thumb(bank_dir, image_path)
        if tpath is None:
            return None
        try:
            mtime = tpath.stat().st_mtime_ns
        except OSError:
            return None
        key = str(tpath)
        cached = self._bank_thumb_photos.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        try:
            with Image.open(tpath) as f:
                img = f.convert("RGBA")
            bg = Image.new("RGBA", img.size, (*hex_to_rgb(theme.BG_TERTIARY), 255))
            bg.alpha_composite(img)
            photo = ImageTk.PhotoImage(bg.convert("RGB"))
        except Exception:
            return None
        self._bank_thumb_photos[key] = (mtime, photo)
        if len(self._bank_thumb_photos) > 800:
            self._bank_thumb_photos.pop(next(iter(self._bank_thumb_photos)))
        return photo

    def _bank_pregen_thumbs(self, paths: list) -> None:
        """Genera en worker thread los thumbs que falten (UI-05)."""
        try:
            bank_dir = self._pipeline.bank.bank_dir
        except Exception:
            return
        pending = [p for p in paths
                   if thumb_cache.is_stale(Path(p), thumb_cache.thumb_path(bank_dir, p))]
        if not pending:
            return
        app = self.app

        def worker():
            try:
                n = thumb_cache.build_thumbs(bank_dir, pending)
                logger.info("thumbs pregenerados: %d", n)
            finally:
                app.after(0, app.end_background_work)

        app.begin_background_work()
        threading.Thread(target=worker, daemon=True, name="bank-thumbs").start()

    # ── Hover bar compartida ───────────────────────────────────────

    def _bank_ensure_hover_bar(self):
        bar = self._bank_hover_bar
        if bar is not None and bar.winfo_exists():
            return bar
        bar = ctk.CTkFrame(self._bank_scroll, fg_color=theme.BG_SECONDARY,
                           corner_radius=theme.RADIUS["s"],
                           border_width=1, border_color=theme.BORDER_LIGHT)
        for icon, hover, cmd in (
            ("pen", theme.ACCENT_PRIMARY, lambda: self._open_rename_modal(bar._glyph)),
            ("chevron-u", theme.ACCENT_GREEN, lambda: self._bank_cycle_tier(bar._glyph)),
            ("trash", theme.ACCENT_RED, lambda: self._bank_delete_glyph(bar._glyph)),
        ):
            ctk.CTkButton(bar, text="", image=icons.get_icon(icon, 12),
                          width=24, height=22, corner_radius=theme.RADIUS["s"],
                          fg_color="transparent", hover_color=hover,
                          command=cmd).pack(side="left", padx=1, pady=1)
        bar.bind("<Enter>", lambda _e: self._bank_hover_cancel_hide(), add="+")
        bar.bind("<Leave>", lambda _e: self._bank_hover_hide(), add="+")
        bar._glyph = None
        self._bank_hover_bar = bar
        return bar

    def _bank_canvas_motion(self, sec: dict, event) -> None:
        path = self._bank_cell_at(sec, event.x, event.y)
        if path is None:
            self._bank_hover_hide()
            return
        cell = sec["cells"].get(path)
        if cell is None:
            return
        bar = self._bank_ensure_hover_bar()
        if bar._glyph is cell["glyph"] and bar.winfo_ismapped():
            self._bank_hover_cancel_hide()
            return
        self._bank_hover_cancel_hide()
        bar._glyph = cell["glyph"]
        idx = sec["order"].index(path)
        x, y = _cell_xy(idx)
        bar.place(in_=sec["body"], x=x + CELL_W // 2, y=y + CELL_H - 28, anchor="n")
        bar.lift()

    def _bank_hover_cancel_hide(self) -> None:
        if self._bank_hover_hide_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._bank_hover_hide_job)
            self._bank_hover_hide_job = None

    def _bank_hover_hide(self, now: bool = False) -> None:
        self._bank_hover_cancel_hide()

        def _hide():
            self._bank_hover_hide_job = None
            bar = self._bank_hover_bar
            if bar is not None:
                bar._glyph = None
                with contextlib.suppress(Exception):
                    bar.place_forget()

        if now:
            _hide()
        else:
            # Delay corto: permite pasar de la celda a la barra sin parpadeo
            self._bank_hover_hide_job = self.after(200, _hide)

    # ── Selección (click en modo selección) ────────────────────────

    def _bank_canvas_click(self, sec: dict, event) -> None:
        if not bool(self._bank_select_mode.get()):
            return
        path = self._bank_cell_at(sec, event.x, event.y)
        if path is None:
            return
        if path in self._bank_selected_paths:
            self._bank_selected_paths.discard(path)
        else:
            self._bank_selected_paths.add(path)
        self._bank_apply_selection_visual(sec, path)
        self._update_bank_selection_bar()

    def _bank_apply_selection_visual(self, sec: dict, path: str) -> None:
        cell = sec["cells"].get(path)
        body = sec.get("body")
        if cell is None or body is None:
            return
        rect = cell["items"][0]
        with contextlib.suppress(Exception):
            if path in self._bank_selected_paths:
                body.itemconfigure(rect, outline=theme.ACCENT_CYAN,
                                   fill=theme.ACCENT_CYAN_BG)
            else:
                body.itemconfigure(rect, outline=_tier_ring(cell["glyph"].tier),
                                   fill=theme.CARD_BG)

    def _bank_clear_selection_visuals(self) -> None:
        for sec in self._bank_sections.values():
            for path in list(sec.get("cells", ())):
                self._bank_apply_selection_visual(sec, path)

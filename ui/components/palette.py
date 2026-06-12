"""Command Palette (Ctrl+K) — U7.

Lanzador rápido de acciones: un buscador fuzzy sobre una lista de Command.
La lógica de matching/ranking (fuzzy_score, rank_commands) es PURA — sin
tkinter — y se testea en tests/test_palette_fuzzy.py.

Presupuesto de widgets (Tk 9 + XWayland: cada widget cuesta ~100-200 ms de
primer pintado): la paleta entera son 6 widgets — Toplevel + frame + header +
icono + CTkEntry + UN tk.Listbox para TODOS los resultados (prohibido un
frame/label por fila). Se construye una sola vez (lazy) y open()/close()
solo hacen deiconify/withdraw; los colores se reconfiguran en cada open()
para respetar el tema claro/oscuro vigente.
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from ui import theme

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────────────────
MAX_RESULTS = 8          # filas visibles/rankeadas como máximo
PALETTE_WIDTH = 560      # ancho fijo del toplevel
_LABEL_PAD = 52          # columnas de relleno para alinear el shortcut
_WORD_SEPS = " \t_-./:·"  # separadores que definen "inicio de palabra"

# Pesos del scoring (relativos entre sí, no normalizados)
_BASE_CHAR = 1.0         # cada carácter de la query que matchea
_BONUS_WORD_START = 2.0  # el match cae en inicio de palabra
_BONUS_CONSECUTIVE = 1.5  # el match es contiguo al anterior
_BONUS_PREFIX = 2.0      # por carácter, si el texto empieza exactamente con la query
_KEYWORD_FACTOR = 0.8    # un match vía keywords vale un poco menos que vía label
_EMPTY_QUERY_SCORE = 1.0  # query vacía: todo matchea con este score base


# ── Lógica pura (testeable sin tkinter) ──────────────────────────────────────

def _greedy_score(query: str, text: str, start: int) -> float:
    """Score de la subsecuencia de `query` en `text` anclando el primer
    carácter en `start` y tomando greedy la primera ocurrencia siguiente.
    Devuelve 0 si la subsecuencia no completa. Ambos ya en minúsculas."""
    score = 0.0
    prev = -2
    pos = start
    for ch in query:
        idx = text.find(ch, pos)
        if idx == -1:
            return 0.0
        score += _BASE_CHAR
        if idx == 0 or text[idx - 1] in _WORD_SEPS:
            score += _BONUS_WORD_START
        if idx == prev + 1:
            score += _BONUS_CONSECUTIVE
        prev = idx
        pos = idx + 1
    return score


def _subsequence_score(query: str, text: str) -> float:
    """Mejor score probando cada ocurrencia del primer carácter como ancla
    (así "ban" prefiere el "banco" de "abrir banco" y no la b de "abrir")."""
    if not query:
        return _EMPTY_QUERY_SCORE
    best = 0.0
    start = text.find(query[0])
    while start != -1:
        best = max(best, _greedy_score(query, text, start))
        start = text.find(query[0], start + 1)
    if best > 0.0 and text.startswith(query):
        best += _BONUS_PREFIX * len(query)
    return best


def fuzzy_score(query: str, text: str, keywords: str = "") -> float:
    """Match por subsecuencia case-insensitive con scoring.

    Bonus por inicio de palabra, por matches consecutivos y por prefijo
    exacto; las keywords también cuentan (con peso menor que el label).
    Devuelve 0.0 si no hay match; query vacía matchea todo con score base.
    """
    q = query.strip().lower()
    score = _subsequence_score(q, text.lower())
    if keywords:
        score = max(score, _KEYWORD_FACTOR * _subsequence_score(q, keywords.lower()))
    return score


@dataclass
class Command:
    """Acción ejecutable desde la paleta."""
    id: str
    label: str
    icon: str = ""                 # nombre de icono de ui/icons.py
    shortcut: str = ""             # texto del atajo, p.ej. "Ctrl+E" (puede ser "")
    fn: Callable[[], None] | None = None
    keywords: str = ""             # términos extra para el fuzzy match


def rank_commands(query: str, commands: list[Command],
                  limit: int = MAX_RESULTS) -> list[Command]:
    """Ordena los comandos por fuzzy_score descendente y devuelve el top.

    Excluye los que no matchean (score 0); a igualdad de score conserva el
    orden de entrada (sort estable). Pura — sin tkinter.
    """
    scored = [(fuzzy_score(query, c.label, c.keywords), c) for c in commands]
    ranked = sorted((sc for sc in scored if sc[0] > 0.0), key=lambda sc: -sc[0])
    return [c for _score, c in ranked[:limit]]


def _format_row(cmd: Command) -> str:
    """Texto de una fila del Listbox: label + shortcut alineado con espacios."""
    if cmd.shortcut:
        return f" {cmd.label.ljust(_LABEL_PAD)}{cmd.shortcut}"
    return f" {cmd.label}"


# ── Widget ───────────────────────────────────────────────────────────────────

@dataclass
class _Widgets:
    """Refs de los 6 widgets de la paleta (None hasta el primer open())."""
    top: object = None
    body: object = None
    header: object = None
    icon: object = None
    entry: object = None
    listbox: object = None
    query_var: object = None
    rows_shown: int = field(default=-1)


class CommandPalette:
    """Paleta de comandos flotante. Construir una vez; abrir con open()."""

    def __init__(self, parent):
        self.parent = parent
        self._commands: list[Command] = []
        self._results: list[Command] = []
        self._sel = 0
        self._w = _Widgets()

    # ── API pública ──────────────────────────────────────────────────────
    def set_commands(self, commands: list[Command]) -> None:
        self._commands = list(commands)
        if self._is_open():
            self._refresh()

    def open(self) -> None:
        """Muestra la paleta centrada arriba de la ventana principal."""
        if self._w.top is None:
            self._build()
        self._apply_theme()
        self._w.query_var.set("")  # dispara _refresh vía trace
        self._refresh()
        self._place()
        self._w.top.deiconify()
        self._w.top.lift()
        self._w.entry.focus_set()

    def close(self) -> None:
        if self._w.top is None:
            return
        try:
            self._w.top.withdraw()
            self.parent.focus_set()
        except Exception:  # ventana padre destruida a mitad de sesión
            pass

    # ── Construcción (una sola vez) ──────────────────────────────────────
    def _build(self) -> None:
        import tkinter as tk

        import customtkinter as ctk

        w = self._w
        w.top = tk.Toplevel(self.parent)
        w.top.withdraw()
        w.top.overrideredirect(True)

        w.body = ctk.CTkFrame(w.top, corner_radius=theme.RADIUS["l"], border_width=1)
        w.body.pack(fill="both", expand=True)

        w.header = ctk.CTkFrame(w.body, fg_color="transparent")
        w.header.pack(fill="x", padx=theme.SPACE["m"],
                      pady=(theme.SPACE["m"], theme.SPACE["s"]))
        w.icon = ctk.CTkLabel(w.header, text="", width=20)
        w.icon.pack(side="left", padx=(0, theme.SPACE["s"]))

        w.query_var = tk.StringVar()
        w.entry = ctk.CTkEntry(w.header, textvariable=w.query_var, border_width=1,
                               corner_radius=theme.RADIUS["m"], height=32)
        w.entry.pack(side="left", fill="x", expand=True)

        # UN solo Listbox para todos los resultados — nada de frame+label por fila.
        w.listbox = tk.Listbox(w.body, height=MAX_RESULTS, activestyle="none",
                               borderwidth=0, highlightthickness=0, relief="flat",
                               exportselection=False, takefocus=0)
        w.listbox.pack(fill="both", expand=True, padx=theme.SPACE["m"],
                       pady=(0, theme.SPACE["m"]))

        w.query_var.trace_add("write", lambda *_a: self._refresh())
        w.top.bind("<Escape>", lambda _e: self.close())
        w.entry.bind("<Escape>", lambda _e: self.close())
        w.entry.bind("<Return>", lambda _e: self._execute(self._sel))
        w.entry.bind("<KP_Enter>", lambda _e: self._execute(self._sel))
        w.entry.bind("<Up>", lambda _e: self._move(-1))
        w.entry.bind("<Down>", lambda _e: self._move(1))
        w.entry.bind("<FocusOut>", self._on_focus_out)
        w.listbox.bind("<ButtonRelease-1>",
                       lambda e: self._execute(w.listbox.nearest(e.y)))

    def _apply_theme(self) -> None:
        """Reconfigura colores/fuentes con los tokens VIGENTES del tema
        (theme.apply_theme intercambia los globals, por eso se lee aquí y
        no se hornea en _build)."""
        from ui import icons
        w = self._w
        with contextlib.suppress(Exception):
            w.top.configure(bg=theme.BG_PRIMARY)
        w.body.configure(fg_color=theme.CARD_BG, border_color=theme.BORDER_LIGHT)
        w.icon.configure(image=icons.get_icon("search", 16, theme.TEXT_SECONDARY))
        w.entry.configure(fg_color=theme.BG_SECONDARY, border_color=theme.BORDER,
                          text_color=theme.TEXT_PRIMARY, font=theme.FONT_BODY)
        w.listbox.configure(bg=theme.CARD_BG, fg=theme.TEXT_PRIMARY,
                            font=theme.FONT_BODY,
                            selectbackground=theme.ACCENT_BG,
                            selectforeground=theme.ACCENT_PRIMARY,
                            highlightbackground=theme.CARD_BG,
                            highlightcolor=theme.CARD_BG)

    # ── Comportamiento ───────────────────────────────────────────────────
    def _is_open(self) -> bool:
        try:
            return self._w.top is not None and self._w.top.winfo_viewable()
        except Exception:
            return False

    def _refresh(self) -> None:
        w = self._w
        if w.listbox is None:
            return
        self._results = rank_commands(w.query_var.get(), self._commands, MAX_RESULTS)
        w.listbox.delete(0, "end")
        for cmd in self._results:
            w.listbox.insert("end", _format_row(cmd))
        self._sel = 0
        self._mark_selection()
        rows = max(1, len(self._results))
        if rows != w.rows_shown:  # solo redimensionar si cambió el nº de filas
            w.listbox.configure(height=rows)
            w.rows_shown = rows
            if self._is_open():
                self._resize_height()

    def _mark_selection(self) -> None:
        lb = self._w.listbox
        lb.selection_clear(0, "end")
        if self._results:
            lb.selection_set(self._sel)
            lb.activate(self._sel)
            lb.see(self._sel)

    def _move(self, delta: int) -> str:
        if self._results:
            self._sel = (self._sel + delta) % len(self._results)
            self._mark_selection()
        return "break"  # que ↑/↓ no muevan el cursor del entry

    def _execute(self, index: int) -> None:
        if not (0 <= index < len(self._results)):
            return
        cmd = self._results[index]
        self.close()  # cerrar ANTES: fn puede abrir diálogos modales
        if cmd.fn is not None:
            try:
                cmd.fn()
            except Exception:
                logger.exception("Command Palette: fallo ejecutando %r", cmd.id)

    def _on_focus_out(self, _event=None) -> None:
        # El foco puede rebotar dentro de la propia paleta (entry↔listbox):
        # decidir un poco después, mirando dónde quedó realmente.
        if self._w.top is not None:
            self._w.top.after(80, self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        if not self._is_open():
            return
        try:
            focused = self._w.top.focus_get()
        except Exception:
            focused = None
        if focused is None or not str(focused).startswith(str(self._w.top)):
            self.close()

    # ── Geometría ────────────────────────────────────────────────────────
    def _place(self) -> None:
        try:
            px, py = self.parent.winfo_rootx(), self.parent.winfo_rooty()
            pw = self.parent.winfo_width()
        except Exception:
            px, py, pw = 0, 0, PALETTE_WIDTH
        if pw < 10:  # la ventana padre aún no midió
            pw = PALETTE_WIDTH
        x = px + max(0, (pw - PALETTE_WIDTH) // 2)
        y = py + 72
        self._w.top.update_idletasks()
        h = self._w.top.winfo_reqheight()
        self._w.top.geometry(f"{PALETTE_WIDTH}x{h}+{x}+{y}")

    def _resize_height(self) -> None:
        top = self._w.top
        top.update_idletasks()
        try:
            x, y = top.winfo_x(), top.winfo_y()
            top.geometry(f"{PALETTE_WIDTH}x{top.winfo_reqheight()}+{x}+{y}")
        except Exception:
            pass

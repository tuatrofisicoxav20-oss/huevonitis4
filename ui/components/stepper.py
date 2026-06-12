"""Stepper del pipeline de "Mi Letra" (U6).

Indicador horizontal de los 4 pasos del flujo InkCore:
1·Plantilla → 2·Extraer → 3·Banco → 4·Escribir.

Diseño crítico de rendimiento (Tk 9 + XWayland: ~100-200 ms de primer
pintado POR WIDGET): el stepper completo es UN SOLO tk.Canvas con items
dibujados (óvalos, líneas y texto) — nada de un frame/label por paso.
Redibujar con delete("all") es barato; crear widgets no.

La lógica de estados vive en compute_step_states(), función pura testeable
sin tkinter (tests/test_stepper_state.py).
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

from ui import theme

# Pasos del pipeline: (step_id, etiqueta visible)
STEPS: list[tuple[str, str]] = [
    ("template", "Plantilla"),
    ("capture", "Extraer"),
    ("bank", "Banco"),
    ("write", "Escribir"),
]

# Flag de progreso que marca cada paso como completado
_FLAG_BY_STEP: dict[str, str] = {
    "template": "has_template",
    "capture": "has_glyphs",
    "bank": "coverage_ok",
    "write": "has_render",
}

_VALID_STATES = frozenset({"done", "current", "pending"})


def compute_step_states(flags: dict) -> dict[str, str]:
    """Calcula el estado visual de cada paso a partir de los flags de progreso.

    PURA (sin tkinter). ``flags`` admite las llaves: has_template, has_glyphs,
    coverage_ok, has_render (faltantes cuentan como False).

    Reglas:
      - Un paso es "done" si su flag es True.
      - El "current" es el PRIMER paso no-done (en orden de STEPS).
      - Si todos están done, el ÚLTIMO paso es "current".
      - El resto queda "pending".
    """
    states: dict[str, str] = {}
    current_assigned = False
    for step_id, _label in STEPS:
        if flags.get(_FLAG_BY_STEP[step_id], False):
            states[step_id] = "done"
        elif not current_assigned:
            states[step_id] = "current"
            current_assigned = True
        else:
            states[step_id] = "pending"
    if not current_assigned:
        # Todos completados: el último paso queda como "current"
        states[STEPS[-1][0]] = "current"
    return states


class PipelineStepper(tk.Canvas):
    """Stepper horizontal del pipeline en un solo Canvas.

    API:
      PipelineStepper(parent, on_step_click=None, compact=False, **kwargs)
      set_states({"template": "done", "capture": "current", ...})

    Estados visuales por paso:
      - "done":    círculo relleno ámbar con check.
      - "current": anillo cian con número, etiqueta en TEXT_PRIMARY.
      - "pending": círculo gris, etiqueta en TEXT_MUTED.
    Las líneas conectoras son ámbar si el paso anterior está done.
    """

    HEIGHT = 36          # alto fijo del canvas
    CIRCLE_R = 9         # radio del círculo de cada paso
    _LABEL_GAP = 6       # círculo → etiqueta
    _CONN_LEN = 24       # largo de la línea conectora (modo normal)
    _CONN_LEN_COMPACT = 18
    _CONN_PAD = 7        # aire entre círculo/etiqueta y la línea

    def __init__(self, parent, on_step_click: Callable[[str], None] | None = None,
                 compact: bool = False, **kwargs):
        kwargs.setdefault("height", self.HEIGHT)
        kwargs.setdefault("bg", theme.BG_SECONDARY)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("bd", 0)
        super().__init__(parent, **kwargs)
        self._on_step_click = on_step_click
        self._compact = bool(compact)
        # Estado inicial: nada hecho → primer paso current
        self._states = compute_step_states({})
        # Zonas clicables: (x0, x1, step_id) — hit-test por rangos x
        self._hit_zones: list[tuple[int, int, str]] = []
        if self._on_step_click is not None:
            self.bind("<Button-1>", self._on_click)
            self.bind("<Motion>", self._on_motion)
        self._redraw()

    # ── API pública ──────────────────────────────────────────────────────

    def set_states(self, states: dict[str, str]) -> None:
        """Aplica nuevos estados y redibuja (delete("all") + redraw — barato)."""
        for step_id, _label in STEPS:
            value = states.get(step_id)
            if value in _VALID_STATES:
                self._states[step_id] = value
        self._redraw()

    # ── Layout ───────────────────────────────────────────────────────────

    def _label_font(self) -> tuple:
        # Negrita SIEMPRE para medir/dibujar: el layout no salta al cambiar
        # cuál paso es el current.
        return theme.get_font("bold", theme.FONT_SMALL[1])

    def _measure_label(self, text: str) -> int:
        try:
            return tkfont.Font(font=self._label_font()).measure(text)
        except Exception:
            # Sin servidor de fuentes (no debería pasar con un canvas vivo):
            # aproximación que evita reventar.
            return len(text) * 7

    def _layout(self) -> tuple[list[dict], int]:
        """Posición x del centro de cada círculo + ancho total del canvas."""
        pad = theme.SPACE["m"]
        conn = self._CONN_LEN_COMPACT if self._compact else self._CONN_LEN
        items: list[dict] = []
        x = pad + self.CIRCLE_R
        for step_id, label in STEPS:
            label_w = 0 if self._compact else self._measure_label(label)
            items.append({"id": step_id, "label": label, "cx": x, "label_w": label_w})
            # avance: borde derecho del paso + conector + radio del siguiente
            right = x + self.CIRCLE_R
            if label_w:
                right += self._LABEL_GAP + label_w
            x = right + self._CONN_PAD + conn + self._CONN_PAD + self.CIRCLE_R
        total = items[-1]["cx"] + self.CIRCLE_R
        if not self._compact:
            total += self._LABEL_GAP + items[-1]["label_w"]
        total += pad
        return items, total

    # ── Dibujo ───────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        self.delete("all")
        self._hit_zones = []
        items, total_w = self._layout()
        # Ancho autocalculado: no dependemos de winfo_width (puede ser 1
        # antes del primer <Configure>).
        self.configure(width=total_w)

        cy = self.HEIGHT // 2
        r = self.CIRCLE_R
        conn_pad = self._CONN_PAD
        label_font = self._label_font()

        for i, item in enumerate(items):
            step_id, cx, label_w = item["id"], item["cx"], item["label_w"]
            state = self._states[step_id]

            # Línea conectora hacia el paso anterior (color según el previo)
            if i > 0:
                prev = items[i - 1]
                prev_done = self._states[prev["id"]] == "done"
                line_color = theme.ACCENT_PRIMARY if prev_done else theme.BORDER
                x0 = prev["cx"] + r + conn_pad
                if prev["label_w"]:
                    x0 += self._LABEL_GAP + prev["label_w"]
                x1 = cx - r - conn_pad
                self.create_line(x0, cy, x1, cy, fill=line_color, width=2)

            # Círculo + contenido según estado
            if state == "done":
                self.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 fill=theme.ACCENT_PRIMARY,
                                 outline=theme.ACCENT_PRIMARY)
                self.create_text(cx, cy, text="✓", fill=theme.ACCENT_TEXT_ON,
                                 font=theme.get_font("bold", 9))
                label_color = theme.TEXT_SECONDARY
            elif state == "current":
                self.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 fill=theme.BG_SECONDARY,
                                 outline=theme.ACCENT_CYAN, width=2)
                self.create_text(cx, cy, text=str(i + 1), fill=theme.ACCENT_CYAN,
                                 font=theme.get_font("bold", 9))
                label_color = theme.TEXT_PRIMARY
            else:  # pending
                self.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 fill=theme.BG_SECONDARY,
                                 outline=theme.BORDER)
                self.create_text(cx, cy, text=str(i + 1), fill=theme.TEXT_MUTED,
                                 font=theme.get_font("bold", 9))
                label_color = theme.TEXT_MUTED

            # Etiqueta a la derecha del círculo (omitida en modo compacto)
            zone_x1 = cx + r
            if label_w:
                lx = cx + r + self._LABEL_GAP
                self.create_text(lx, cy, text=item["label"], anchor="w",
                                 fill=label_color, font=label_font)
                zone_x1 = lx + label_w
            self._hit_zones.append((cx - r, zone_x1, step_id))

    # ── Interacción ──────────────────────────────────────────────────────

    def _zone_at(self, x: int) -> str | None:
        for x0, x1, step_id in self._hit_zones:
            if x0 <= x <= x1:
                return step_id
        return None

    def _on_click(self, event) -> None:
        step_id = self._zone_at(event.x)
        if step_id is not None and self._on_step_click is not None:
            self._on_step_click(step_id)

    def _on_motion(self, event) -> None:
        cursor = "hand2" if self._zone_at(event.x) else ""
        if self.cget("cursor") != cursor:
            self.configure(cursor=cursor)

"""Primitivas de diagrama dibujadas con estética manuscrita (Fase 6).

Líneas/flechas/cajas/círculos/llaves con "wobble" (temblor suave que se anula en
los extremos), del mismo color de tinta y grosor que el texto, para que un
diagrama y los apuntes se vean del mismo puño. NO reconoce diagramas desde una
foto: el usuario define la estructura y esto la dibuja (decisión del master
prompt). Las etiquetas de nodos se renderizan con el MOTOR DE TEXTO del banco
(HandwritingRenderer), no acá — esta capa es sólo trazo.

Se mantiene independiente de concept_map.py (que ya dibuja mapas-árbol) para ser
reutilizable en cualquier diagrama suelto y mezclable con bloques de texto.
"""
from __future__ import annotations

import math
import random

try:
    from PIL import ImageColor
    PIL_OK = True
except ImportError:  # pragma: no cover
    PIL_OK = False


def _ink_rgb(ink_color: str) -> tuple[int, int, int]:
    try:
        return ImageColor.getrgb(ink_color)[:3]
    except (ValueError, TypeError):
        return (26, 26, 46)


class HandDraw:
    """Dibuja primitivas a mano sobre un ImageDraw existente.

    ink_color/width replican el trazo del texto. ``wobble`` es la amplitud (px)
    del temblor; ``rng`` (random.Random) hace el dibujo reproducible junto con el
    seed del render. Todas las primitivas se anclan en sus extremos (el temblor se
    anula ahí) para que las formas cierren y las flechas apunten bien.
    """

    def __init__(self, ink_color: str = "#1A1A2E", width: int = 2,
                 wobble: float = 1.6, rng: random.Random | None = None):
        self.ink = _ink_rgb(ink_color)
        self.width = max(1, int(width))
        self.wobble = max(0.0, float(wobble))
        self.rng = rng or random

    # ── trazo base ────────────────────────────────────────────────
    def _wobble_points(self, p0, p1, segments: int = 10) -> list:
        """Polilínea de p0→p1 con temblor suave (taper en extremos)."""
        (x0, y0), (x1, y1) = p0, p1
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        px, py = -dy / length, dx / length  # perpendicular unitaria
        amp = min(self.wobble, length * 0.12)
        pts = []
        off = 0.0
        for i in range(segments + 1):
            t = i / segments
            off += self.rng.uniform(-amp, amp) * 0.6
            off = max(-amp, min(amp, off))
            o = off * math.sin(math.pi * t)  # 0 en extremos, máx al medio
            pts.append((x0 + dx * t + px * o, y0 + dy * t + py * o))
        return pts

    def line(self, draw, p0, p1, segments: int = 10) -> None:
        draw.line(self._wobble_points(p0, p1, segments), fill=self.ink,
                  width=self.width, joint="curve")

    def arrow(self, draw, p0, p1, head_len: float = 14.0, head_angle_deg: float = 26.0,
              segments: int = 10) -> None:
        """Línea a mano de p0→p1 con punta de flecha en p1 (dos trazos cortos)."""
        self.line(draw, p0, p1, segments)
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        a = math.radians(head_angle_deg)
        for da in (-a, a):
            ex = p1[0] - head_len * math.cos(ang + da)
            ey = p1[1] - head_len * math.sin(ang + da)
            self.line(draw, p1, (ex, ey), segments=3)

    def rect(self, draw, box) -> None:
        """Rectángulo de esquinas imperfectas (4 aristas con wobble)."""
        x0, y0, x1, y1 = box
        tl, tr, br, bl = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
        perim = self._wobble_points(tl, tr)
        perim += self._wobble_points(tr, br)[1:]
        perim += self._wobble_points(br, bl)[1:]
        perim += self._wobble_points(bl, tl)[1:]
        perim.append(perim[0])
        draw.line(perim, fill=self.ink, width=self.width, joint="curve")

    def ellipse(self, draw, box, segments: int = 48) -> None:
        """Elipse a mano: contorno cerrado con radio temblado."""
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = abs(x1 - x0) / 2, abs(y1 - y0) / 2
        amp = self.wobble
        pts = []
        off = 0.0
        for i in range(segments + 1):
            t = i / segments
            off += self.rng.uniform(-amp, amp) * 0.5
            off = max(-amp, min(amp, off))
            ang = 2 * math.pi * t
            pts.append((cx + (rx + off) * math.cos(ang), cy + (ry + off) * math.sin(ang)))
        pts[-1] = pts[0]  # cierra
        draw.line(pts, fill=self.ink, width=self.width, joint="curve")

    def circle(self, draw, center, radius: float, segments: int = 48) -> None:
        cx, cy = center
        self.ellipse(draw, (cx - radius, cy - radius, cx + radius, cy + radius), segments)

    def brace(self, draw, x: float, y0: float, y1: float, depth: float = 16.0,
              facing: str = "left") -> None:
        """Llave { (facing='left') o } (facing='right') que agrupa de y0 a y1.

        La punta central apunta hacia afuera de x según facing. Hecha de cuatro
        tramos suaves con wobble para que se vea trazada a mano.
        """
        ym = (y0 + y1) / 2
        d = depth if facing == "left" else -depth
        spine = x
        tip = x - d  # la punta central sobresale
        # dos mitades: y0→medio y medio→y1, cada una curva hacia la punta
        self.line(draw, (spine, y0), (spine - d * 0.5, (y0 + ym) / 2), segments=4)
        self.line(draw, (spine - d * 0.5, (y0 + ym) / 2), (tip, ym), segments=4)
        self.line(draw, (tip, ym), (spine - d * 0.5, (ym + y1) / 2), segments=4)
        self.line(draw, (spine - d * 0.5, (ym + y1) / 2), (spine, y1), segments=4)

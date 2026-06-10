"""Modo MAPA CONCEPTUAL — renderiza una jerarquía tipo árbol como un mapa
conceptual "hecho a mano", separado del render lineal de apuntes.

Alcance (Ticket 3, fases A–C):
  - Fase A: la estructura entra como TEXTO INDENTADO (o lista markdown anidada),
    no desde una imagen. La sangría define la jerarquía (raíz → hijos → nietos).
  - Fase B: layout de árbol de arriba-abajo. Cada subárbol reserva su propio
    ancho, así dos ramas hermanas NUNCA se enciman horizontalmente.
  - Fase C: cada nodo es una caja con contorno a mano alzada (leve temblor) y el
    texto en la letra del usuario; los padres se unen a sus hijos con conectores
    curvos con jitter y una flecha sutil. El toque humano son offsets ACOTADOS
    por nodo: humano ≠ caótico.

La Fase D (inferir la estructura desde una imagen escaneada) NO está acá: es
visión por computadora real y la entrada por texto ya resuelve el caso de uso.

El contrato de salida es una lista de imágenes RGB (una "página"), igual que
render_pages/render_document, para que la UI las muestre y exporte sin cambios.
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field, replace

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageColor, ImageDraw
    PIL_OK = True
except ImportError:
    PIL_OK = False


# Viñetas que se descartan al inicio de una línea (la sangría ya da la jerarquía).
_BULLET_CHARS = "-*+•·◦‣"

# Parámetros de layout (px). Generosos respecto al jitter de nodo para que el
# toque "a mano" nunca llegue a encimar cajas vecinas.
_H_GAP = 46          # hueco horizontal mínimo entre subárboles hermanos
_V_GAP = 72          # hueco vertical entre niveles
_PAGE_MARGIN = 70    # margen alrededor de todo el mapa
_NODE_JITTER_X = 5   # offset humano por nodo (acotado << _H_GAP)
_NODE_JITTER_Y = 4
_MAX_LABEL_W = 260   # ancho máx del texto dentro de una caja antes de envolver

# Escala de fuente por profundidad: la raíz resalta, las hojas se achican un poco.
_DEPTH_FONT_SCALE = {0: 1.25, 1: 1.05}
_DEPTH_FONT_SCALE_DEFAULT = 0.92


@dataclass
class MapNode:
    """Un nodo del árbol con su geometría de layout ya resuelta.

    Las coordenadas (x, y) son la esquina superior-izquierda de la caja; (w, h)
    su tamaño. ``label`` es el texto ya renderizado en la letra del usuario
    (RGBA, recortado). ``virtual`` marca una raíz sintética que agrupa varios
    nodos de primer nivel sin dibujarse.
    """
    text: str
    children: list = field(default_factory=list)
    depth: int = 0
    virtual: bool = False
    # Geometría (rellenada por el layout)
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    label: object = None  # Image.Image | None
    # Offset "humano" acotado, fijado una vez para que conectores y caja coincidan
    jx: int = 0
    jy: int = 0

    @property
    def cx(self) -> float:
        return self.x + self.jx + self.w / 2

    def top_center(self) -> tuple[float, float]:
        return (self.cx, self.y + self.jy)

    def bottom_center(self) -> tuple[float, float]:
        return (self.cx, self.y + self.jy + self.h)


# ── Fase A: parsing ─────────────────────────────────────────────────────────

def _strip_bullet(text: str) -> str:
    """Quita una viñeta inicial (- * + •) y el espacio que la sigue."""
    t = text.lstrip()
    if t[:1] in _BULLET_CHARS:
        t = t[1:].lstrip()
    return t


def parse_indented_tree(text: str) -> MapNode | None:
    """Convierte texto indentado en un árbol de MapNode.

    La jerarquía sale de la sangría: una línea con más sangría que la anterior
    es su hija. Funciona con cualquier paso de sangría (2 o 4 espacios) y con
    tabs (se expanden a 4). Las viñetas markdown (-, *, +) son opcionales y se
    descartan. Las líneas en blanco se ignoran.

    Si hay un único nodo de primer nivel, ese es la raíz. Si hay varios, se
    envuelven en una raíz sintética (``virtual=True``) que el dibujo no pinta
    pero que sirve de punto de unión del layout. Devuelve None si no hay texto.
    """
    lines = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        expanded = raw.expandtabs(4)
        stripped = expanded.strip()
        if not stripped:
            continue
        indent = len(expanded) - len(expanded.lstrip(" "))
        label = _strip_bullet(stripped)
        if label:
            lines.append((indent, label))

    if not lines:
        return None

    # Pila de (indent, nodo). Para cada línea, se busca su padre: el nodo más
    # reciente con sangría ESTRICTAMENTE menor. La normalización a niveles
    # enteros (depth) se hace al vincular, no por el valor crudo de sangría.
    roots: list[MapNode] = []
    stack: list[tuple[int, MapNode]] = []
    for indent, label in lines:
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            parent = stack[-1][1]
            node = MapNode(text=label, depth=parent.depth + 1)
            parent.children.append(node)
        else:
            node = MapNode(text=label, depth=0)
            roots.append(node)
        stack.append((indent, node))

    if len(roots) == 1:
        return roots[0]
    virtual = MapNode(text="", depth=-1, virtual=True, children=roots)
    return virtual


def iter_nodes(root: MapNode):
    """Recorre el árbol en pre-orden (incluida la raíz, virtual o no)."""
    yield root
    for child in root.children:
        yield from iter_nodes(child)


# ── Renderer ────────────────────────────────────────────────────────────────

class ConceptMapRenderer:
    """Dibuja un árbol como mapa conceptual a mano usando el banco de glifos.

    Envuelve un HandwritingRenderer para reutilizar su carga/recoloreado de
    glifos y su word-wrap; no toca el render lineal.
    """

    def __init__(self, hw_renderer):
        self.hw = hw_renderer

    # -- API pública --
    def render(self, text: str, options, page_height: int | None = None) -> list:
        """Texto indentado → lista con UNA página RGB (el mapa completo).

        Devuelve [] si no hay PIL, [] si el texto no produce nodos.
        """
        if not PIL_OK:
            return []
        root = parse_indented_tree(text)
        if root is None:
            return []

        options = self.hw.apply_style(replace(options))
        options = self.hw._apply_background_style(options)

        self._measure(root, options)
        self._layout(root)
        # Re-encuadra a coordenadas positivas con margen y fija el jitter por nodo.
        page_w, page_h = self._normalize_positions(root)

        canvas = Image.new("RGBA", (page_w, page_h), options.background_color)
        self._paint_background(canvas, options)
        draw = ImageDraw.Draw(canvas)
        ink = self._ink(options)

        # Orden de pintado: conectores detrás, luego cajas, luego etiquetas.
        for node in iter_nodes(root):
            if node.virtual:
                continue
            for child in node.children:
                self._draw_connector(draw, node.bottom_center(), child.top_center(), ink)
        for node in iter_nodes(root):
            if node.virtual:
                continue
            self._draw_box(draw, node, ink)
        for node in iter_nodes(root):
            if node.virtual or node.label is None:
                continue
            lx = int(node.x + node.jx + (node.w - node.label.width) / 2)
            ly = int(node.y + node.jy + (node.h - node.label.height) / 2)
            canvas.paste(node.label, (lx, ly), node.label)

        return [canvas.convert("RGB")]

    # -- Fase A.5: medir cada nodo (texto + caja) --
    def _measure(self, root: MapNode, options) -> None:
        for node in iter_nodes(root):
            if node.virtual:
                node.w = node.h = 0.0
                continue
            scale = _DEPTH_FONT_SCALE.get(node.depth, _DEPTH_FONT_SCALE_DEFAULT)
            fs = max(8, int(options.font_size * scale))
            nopts = replace(options, font_size=fs)
            label = self._render_label(node.text, nopts)
            node.label = label
            pad_x = max(10, int(fs * 0.55))
            pad_y = max(8, int(fs * 0.45))
            lw = label.width if label is not None else fs
            lh = label.height if label is not None else fs
            node.w = lw + 2 * pad_x
            node.h = lh + 2 * pad_y

    def _render_label(self, text: str, options):
        """Renderiza una etiqueta corta multi-línea en la letra del usuario.

        Reutiliza el word-wrap y _render_line del HandwritingRenderer, recorta
        cada renglón a su tinta y los apila centrados. Devuelve RGBA o None.
        """
        wrapped = self.hw._soft_wrap_text(text, options, _MAX_LABEL_W)
        crops = []
        for ln in wrapped:
            li = self.hw._render_line(ln, options, _MAX_LABEL_W)
            if li is None:
                continue
            bbox = li.getchannel("A").getbbox()
            if bbox:
                crops.append(li.crop(bbox))
        if not crops:
            return None
        line_gap = max(2, int(options.font_size * 0.22))
        w = max(c.width for c in crops)
        h = sum(c.height for c in crops) + line_gap * (len(crops) - 1)
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        y = 0
        for c in crops:
            out.paste(c, ((w - c.width) // 2, y), c)
            y += c.height + line_gap
        return out

    # -- Fase B: layout de árbol --
    def _layout(self, root: MapNode) -> None:
        """Asigna (x, y) a cada nodo: raíz arriba, hijos debajo, sin solapes."""
        # Y por nivel: cada profundidad arranca tras la fila más alta de la previa.
        level_h: dict[int, float] = {}
        for node in iter_nodes(root):
            if node.virtual:
                continue
            level_h[node.depth] = max(level_h.get(node.depth, 0.0), node.h)
        level_y: dict[int, float] = {}
        acc = 0.0
        for d in sorted(level_h):
            level_y[d] = acc
            acc += level_h[d] + _V_GAP

        # X por sub-árbol: cada nodo reserva block_width = max(ancho propio,
        # span de los hijos). Como los hermanos se colocan uno tras otro por su
        # block_width, dos subárboles nunca se enciman horizontalmente.
        def block_width(n: MapNode) -> float:
            if not n.children:
                return n.w
            inner = sum(block_width(c) for c in n.children)
            inner += _H_GAP * (len(n.children) - 1)
            return max(n.w, inner)

        def place(n: MapNode, x_left: float) -> None:
            bw = block_width(n)
            if n.children:
                inner = sum(block_width(c) for c in n.children)
                inner += _H_GAP * (len(n.children) - 1)
                cursor = x_left + (bw - inner) / 2
                for c in n.children:
                    place(c, cursor)
                    cursor += block_width(c) + _H_GAP
            center = x_left + bw / 2
            n.x = center - n.w / 2
            if not n.virtual:
                n.y = level_y.get(n.depth, 0.0)

        place(root, 0.0)

    def _normalize_positions(self, root: MapNode) -> tuple[int, int]:
        """Traslada todo a coordenadas ≥ margen, fija el jitter por nodo y
        devuelve el tamaño de página que contiene el mapa entero."""
        real = [n for n in iter_nodes(root) if not n.virtual]
        if not real:
            return (1, 1)
        min_x = min(n.x for n in real)
        min_y = min(n.y for n in real)
        dx = _PAGE_MARGIN - min_x
        dy = _PAGE_MARGIN - min_y
        max_x = max_y = 0.0
        for n in real:
            n.x += dx
            n.y += dy
            n.jx = random.randint(-_NODE_JITTER_X, _NODE_JITTER_X)
            n.jy = random.randint(-_NODE_JITTER_Y, _NODE_JITTER_Y)
            max_x = max(max_x, n.x + n.jx + n.w)
            max_y = max(max_y, n.y + n.jy + n.h)
        page_w = int(max_x + _PAGE_MARGIN)
        page_h = int(max_y + _PAGE_MARGIN)
        return (max(1, page_w), max(1, page_h))

    # -- Fase C: dibujo a mano alzada --
    @staticmethod
    def _ink(options) -> tuple[int, int, int]:
        try:
            return ImageColor.getrgb(options.ink_color)[:3]
        except (ValueError, TypeError):
            return (26, 26, 46)

    def _paint_background(self, canvas, options) -> None:
        """Fondo limpio. Sólo dibuja cuadrícula si el estilo es cuadrícula; las
        rayas de libreta ensucian un mapa, así que no se aplican acá."""
        if getattr(options, "background_style", "") == "hoja_cuadricula":
            draw = ImageDraw.Draw(canvas)
            try:
                grid = ImageColor.getrgb(getattr(options, "line_color", "#C5D5F0"))[:3]
            except (ValueError, TypeError):
                grid = (197, 213, 240)
            step = 28
            for gx in range(0, canvas.width, step):
                draw.line([(gx, 0), (gx, canvas.height)], fill=grid, width=1)
            for gy in range(0, canvas.height, step):
                draw.line([(0, gy), (canvas.width, gy)], fill=grid, width=1)

    @staticmethod
    def _wobble_edge(p0, p1, amp: float, segments: int = 8) -> list:
        """Puntos de una arista recta con temblor suave que se anula en los
        extremos (taper), para que las esquinas de la caja sigan cerrando."""
        (x0, y0), (x1, y1) = p0, p1
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        px, py = -dy / length, dx / length  # perpendicular unitaria
        pts = []
        off = 0.0
        for i in range(segments + 1):
            t = i / segments
            off += random.uniform(-amp, amp) * 0.6
            off = max(-amp, min(amp, off))
            taper = math.sin(math.pi * t)  # 0 en extremos, 1 al medio
            o = off * taper
            pts.append((x0 + dx * t + px * o, y0 + dy * t + py * o))
        return pts

    def _draw_box(self, draw, node: MapNode, ink) -> None:
        x = node.x + node.jx
        y = node.y + node.jy
        w, h = node.w, node.h
        tl, tr = (x, y), (x + w, y)
        br, bl = (x + w, y + h), (x, y + h)
        amp = max(1.2, min(3.5, h * 0.05))
        width = 2 if node.depth > 0 else 3
        perim = []
        perim += self._wobble_edge(tl, tr, amp)
        perim += self._wobble_edge(tr, br, amp)[1:]
        perim += self._wobble_edge(br, bl, amp)[1:]
        perim += self._wobble_edge(bl, tl, amp)[1:]
        perim.append(perim[0])  # cierra el contorno
        draw.line(perim, fill=ink, width=width, joint="curve")

    def _draw_connector(self, draw, a, b, ink) -> None:
        """Conector curvo (bezier cuadrático) con leve jitter del punto de
        control y una flecha sutil en el extremo del hijo."""
        ax, ay = a
        bx, by = b
        mx = (ax + bx) / 2 + random.uniform(-7, 7)
        my = (ay + by) / 2 + random.uniform(-3, 3)
        pts = []
        steps = 14
        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * ax + 2 * (1 - t) * t * mx + t * t * bx
            y = (1 - t) ** 2 * ay + 2 * (1 - t) * t * my + t * t * by
            pts.append((x, y))
        draw.line(pts, fill=ink, width=2, joint="curve")
        # Flecha: dirección de los últimos dos puntos del trazo.
        p_prev = pts[-2]
        ang = math.atan2(by - p_prev[1], bx - p_prev[0])
        size = 9
        for da in (-0.45, 0.45):
            ex = bx - size * math.cos(ang + da)
            ey = by - size * math.sin(ang + da)
            draw.line([(bx, by), (ex, ey)], fill=ink, width=2)

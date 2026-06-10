"""DiagramRenderer — dibuja un diagrama a mano desde una mini-sintaxis de texto.

Expone las primitivas de diagram_primitives.HandDraw al Escritor con el MISMO
patrón que el modo "mapa" (texto → dibujo): el usuario escribe una línea por
primitiva y el sistema la dibuja a mano, con las etiquetas renderizadas por el
motor de texto del banco (no se duplica el render de texto).

Sintaxis (una primitiva por línea; las líneas que empiezan con # son comentarios):

    box  x1,y1 x2,y2 [etiqueta]      caja de esquinas imperfectas
    circle  cx,cy r [etiqueta]       círculo a mano
    arrow  x1,y1 x2,y2               flecha a mano con punta
    line  x1,y1 x2,y2                línea a mano
    brace  x,y1,y2 [L|R]             llave { (L, def.) o } (R)
    text  x,y la etiqueta            texto en la letra del banco

Coordenadas en píxeles sobre la página (page_width × page_height). Una línea
inválida se ignora (no rompe el render). Devuelve [Image] como ConceptMapRenderer,
así el Escritor lo enchufa igual que el modo mapa.
"""
from __future__ import annotations

import logging

from core.inkcore.diagram_primitives import HandDraw

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except ImportError:  # pragma: no cover
    PIL_OK = False


def _pt(tok: str) -> tuple[float, float]:
    x, y = tok.split(",")
    return float(x), float(y)


class DiagramRenderer:
    """Renderiza un diagrama a mano desde el DSL de texto. Reusa el motor de texto
    del HandwritingRenderer para las etiquetas."""

    def __init__(self, hw_renderer):
        self.hw = hw_renderer

    def render(self, text: str, options, page_height: int | None = None) -> list:
        if not PIL_OK:
            return []
        opts = self.hw.apply_style(options)
        self.hw._begin_render(opts)  # inicializa selección de variantes para etiquetas
        if page_height is None:
            page_height = getattr(opts, "page_height_px", 1122)
        W, H = opts.page_width, page_height
        canvas = Image.new("RGB", (W, H), opts.background_color or "#FFFFFF")
        draw = ImageDraw.Draw(canvas)
        hd = HandDraw(
            ink_color=opts.ink_color, width=2, wobble=2.2,
            rng=getattr(self.hw, "_sel_rng", None),
        )
        for raw in text.split("\n"):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                self._draw(line, draw, canvas, hd, opts)
            except Exception as exc:
                logger.debug("DiagramRenderer: línea ignorada %r (%s)", line, exc)
        return [canvas]

    # ── etiquetas con la letra del banco ──────────────────────────
    def _label_img(self, text: str, options):
        """Renderiza ``text`` con el motor del banco y lo recorta a su tinta."""
        if not text:
            return None
        li = self.hw._render_line(text, options, max_width=int(options.page_width * 0.9))
        if li is None:
            return None
        bb = li.getchannel("A").getbbox()
        return li.crop(bb) if bb else li

    def _paste_centered(self, canvas, label_img, cx, cy):
        if label_img is None:
            return
        x = int(cx - label_img.width / 2)
        y = int(cy - label_img.height / 2)
        canvas.paste(label_img, (x, y), label_img)

    # ── comandos ──────────────────────────────────────────────────
    def _draw(self, line, draw, canvas, hd: HandDraw, opts):
        parts = line.split()
        cmd = parts[0].lower()
        if cmd == "box":
            (x1, y1), (x2, y2) = _pt(parts[1]), _pt(parts[2])
            hd.rect(draw, (x1, y1, x2, y2))
            label = " ".join(parts[3:])
            if label:
                self._paste_centered(canvas, self._label_img(label, opts),
                                     (x1 + x2) / 2, (y1 + y2) / 2)
        elif cmd == "circle":
            cx, cy = _pt(parts[1])
            rad = float(parts[2])
            hd.circle(draw, (cx, cy), rad)
            label = " ".join(parts[3:])
            if label:
                self._paste_centered(canvas, self._label_img(label, opts), cx, cy)
        elif cmd == "arrow":
            hd.arrow(draw, _pt(parts[1]), _pt(parts[2]))
        elif cmd == "line":
            hd.line(draw, _pt(parts[1]), _pt(parts[2]))
        elif cmd == "brace":
            x, y1, y2 = (float(v) for v in parts[1].split(","))
            facing = "right" if (len(parts) > 2 and parts[2].upper() == "R") else "left"
            hd.brace(draw, x, y1, y2, facing=facing)
        elif cmd == "text":
            cx, cy = _pt(parts[1])
            label = " ".join(parts[2:])
            img = self._label_img(label, opts)
            if img is not None:
                canvas.paste(img, (int(cx), int(cy)), img)
        else:
            logger.debug("DiagramRenderer: comando desconocido %r", cmd)

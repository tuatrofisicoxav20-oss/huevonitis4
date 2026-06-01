"""Puente entre el replicador y el editor de canvas (Fase 2).

El replicador (`replicator.py`) detecta un apunte como `PageLayout` (lista de
`Block` con posición y texto OCR). Para *retocar* ese apunte (mover/agregar/
borrar/editar bloques) reutilizamos el `CanvasEditor`, que trabaja sobre
`core.models.Page` con `TextElement`/`RectElement`/`LineElement`.

Este módulo hace las dos conversiones que faltaban:
  - `layout_to_page`: PageLayout detectado → Page editable en el canvas.
  - `render_page_handwritten`: Page editada → imagen final con la letra del
    perfil activo, respetando posiciones (lo que el usuario exporta como hoja).
"""
from __future__ import annotations

import logging
import random

from core.models import LineElement, Page, RectElement, TextElement

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def layout_to_page(layout, background_color: str = "#FFFFFF") -> Page:
    """Convierte un `PageLayout` del replicador en una `Page` editable.

    Sólo se traen los bloques `enabled` (los que el usuario no desmarcó). El
    texto se mapea a `TextElement` con un `font_size` proporcional a la altura
    OCR; los recuadros a `RectElement` con relleno transparente (no tapan).
    """
    page = Page(
        name="Apunte replicado",
        width=int(layout.page_width or 794),
        height=int(layout.page_height or 1123),
        background_color=background_color,
    )
    for block in layout.blocks:
        if not getattr(block, "enabled", True):
            continue
        if block.type == "text" and block.text.strip():
            font_size = max(10, min(60, int(block.h * 0.75)))
            page.elements.append(TextElement(
                x=float(block.x), y=float(block.y),
                width=float(max(40, block.w)), height=float(max(20, block.h)),
                text=block.text, font_size=font_size, color="#1A1A2E",
            ))
        elif block.type == "rect":
            page.elements.append(RectElement(
                x=float(block.x), y=float(block.y),
                width=float(max(10, block.w)), height=float(max(10, block.h)),
                fill_color="", border_color="#1A1A2E", border_width=2,
            ))
    logger.info("layout_to_page: %d bloques → %d elementos",
                len(layout.blocks), len(page.elements))
    return page


def render_page_handwritten(page: Page, bank, ink_color: str = "#1A1A2E"):
    """Renderiza una `Page` con la letra del banco, respetando el acomodo.

    Cada `TextElement` se re-escribe con el `HandwritingRenderer` y se composita
    transparente en su posición; los `RectElement`/`LineElement` se re-trazan con
    leve jitter para que se vean manuscritos. Devuelve una imagen RGB lista para
    exportar, o None si falta PIL.
    """
    if not _PIL_OK:
        return None
    try:
        from core.inkcore.renderer import HandwritingRenderer, RenderOptions
    except ImportError as exc:
        logger.error("render_page_handwritten: renderer no disponible: %s", exc)
        return None

    canvas = Image.new("RGB", (page.width, page.height), page.background_color or "#FFFFFF")
    draw = ImageDraw.Draw(canvas)
    hr = HandwritingRenderer(bank)

    for el in page.elements:
        if not getattr(el, "visible", True):
            continue
        if isinstance(el, TextElement):
            if not el.text.strip():
                continue
            opts = RenderOptions(
                font_size=max(12, int(el.font_size)),
                page_width=int(el.width) + 20,
                page_margin=2,
                jitter_px=2, size_variation=0.08, rotation_range=2.5,
                ink_color=ink_color, style="Limpio",
            )
            try:
                block_img = hr.render_transparent(el.text, opts)
            except Exception as exc:
                logger.warning("render_page_handwritten: bloque %r falló: %s",
                               el.text[:30], exc)
                block_img = None
            if block_img is not None:
                canvas.paste(block_img, (int(el.x), int(el.y)), block_img)
        elif isinstance(el, RectElement):
            _draw_jittered_rect(draw, el)
        elif isinstance(el, LineElement):
            jx = random.randint(-2, 2)
            draw.line(
                (el.x + jx, el.y, el.x2 + jx, el.y2),
                fill=(40, 40, 40), width=max(1, el.line_width),
            )
    return canvas


def _draw_jittered_rect(draw, el) -> None:
    x1, y1 = el.x + random.randint(-2, 2), el.y + random.randint(-2, 2)
    x2 = el.x + el.width + random.randint(-2, 2)
    y2 = el.y + el.height + random.randint(-2, 2)
    for offset in (0, 1):
        draw.rectangle((x1 - offset, y1 - offset, x2 + offset, y2 + offset),
                       outline=(40, 40, 40), width=1)

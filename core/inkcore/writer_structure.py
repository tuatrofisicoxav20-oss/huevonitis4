"""Capa de LAYOUT ESTRUCTURADO para el Escritor (apuntes escolares).

Convierte el texto plano que el usuario TECLEA en el Escritor en bloques
(títulos, listas numeradas, viñetas, secciones) y los renderiza encima del
motor físico existente. Es ADITIVA y AUTÓNOMA:

  • No toca el banco ni las métricas geométricas (nat_h/em/baseline).
  • No toca renderer_layout.py: reutiliza como caja negra _render_line,
    _soft_wrap_text, _line_baseline_offset y _flow_blocklines_to_pages.
  • No usa el modelo OCR (document_model.Document): tiene su propio StructBlock,
    ligero y dedicado al Escritor.

Sigue el MISMO patrón que ConceptMapRenderer / DiagramRenderer: una clase que
recibe el HandwritingRenderer y expone .render(text, options, page_height)->list.

NO-REGRESIÓN POR CONSTRUCCIÓN
-----------------------------
El disparador de estructura (detect_structure) es ÚNICAMENTE la presencia de
una MARCA (#, viñeta o N:). La línea vacía y la indentación por espacios NO
disparan estructura por sí solas: así la prosa normal (que rutinariamente trae
líneas en blanco entre párrafos y a veces sangrías) cae al camino de texto
plano de hoy y se renderiza IDÉNTICA. La detección es de sólo lectura: nunca
muta el texto, y el caller delega en render_pages/iter_pages con el string
original cuando no hay marcas.

MARCADO (espacio tras la marca OBLIGATORIO para no confundir "3:30", "1.5",
"-5°C", "well-being"):

    # Título            encabezado nivel 1   (## nivel 2, ### nivel 3)
    1: texto            lista numerada (conserva el número literal del usuario)
    2. texto            (también '.' o ')' tras el número)
    - texto             viñeta  (también '*' o '•')
    (línea vacía)       separación de sección
      - subviñeta       anidación por espacios al inicio (2 espacios / 1 tab = 1 nivel)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    PIL_OK = True
except ImportError:  # pragma: no cover
    PIL_OK = False

# Marcas de estructura. El \s final es DELIBERADO: exige un espacio tras la
# marca, así "3:30 reunión", "1.5 litros", "-5°C" o "#hashtag" NO se confunden
# con estructura (clave para la no-regresión de prosa).
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_NUMBERED_RE = re.compile(r"^(\d+)[:.)]\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*•]\s+(.*)$")

# Sangría: cada 2 espacios (o 1 tab) al inicio de la línea = 1 nivel de
# anidación. Conservador: una sangría suelta de 1 espacio no escala nada.
_SPACES_PER_LEVEL = 2
_TAB_AS_SPACES = 2


@dataclass
class StructBlock:
    """Un bloque de apunte parseado del texto del usuario (modelo propio,
    independiente del TextBlock del OCR)."""
    kind: str                 # "heading" | "numbered" | "bullet" | "paragraph"
    text: str                 # texto ya SIN la marca
    level: int = 1            # nivel de encabezado (1-3); sólo si kind=="heading"
    marker: str = ""          # número literal del usuario; sólo si kind=="numbered"
    indent_level: int = 0     # profundidad por espacios/tabs al inicio
    gap_section: bool = False  # venía precedido de al menos una línea vacía


def _measure_indent(raw: str) -> int:
    """Nivel de anidación por los espacios/tabs iniciales de la línea."""
    spaces = 0
    for ch in raw:
        if ch == " ":
            spaces += 1
        elif ch == "\t":
            spaces += _TAB_AS_SPACES
        else:
            break
    return spaces // _SPACES_PER_LEVEL


def _match_mark(stripped: str):
    """Devuelve (kind, payload) si la línea (ya sin sangría) trae una marca, o
    None. payload = (level, marker, text) según el tipo."""
    m = _HEADING_RE.match(stripped)
    if m:
        return "heading", (len(m.group(1)), "", m.group(2).strip())
    m = _NUMBERED_RE.match(stripped)
    if m:
        return "numbered", (1, m.group(1), m.group(2).strip())
    m = _BULLET_RE.match(stripped)
    if m:
        return "bullet", (1, "", m.group(1).strip())
    return None


def detect_structure(text: str) -> bool:
    """True si el texto trae AL MENOS UNA marca de estructura.

    SÓLO las marcas disparan (no las líneas vacías ni la sangría): garantiza
    que la prosa normal se quede en el camino de texto plano de hoy. Sólo
    lectura — no modifica el texto.
    """
    for raw in text.split("\n"):
        if _match_mark(raw.lstrip(" \t")) is not None:
            return True
    return False


def parse_structure(text: str) -> list[StructBlock]:
    """Parsea el texto en bloques. Cada línea no vacía es un bloque; las líneas
    vacías marcan gap_section en el SIGUIENTE bloque. La sangría inicial se
    traduce a indent_level (sólo se interpreta acá, ya en el camino estructurado).
    """
    blocks: list[StructBlock] = []
    pending_gap = False
    for raw in text.split("\n"):
        if not raw.strip():
            pending_gap = True
            continue
        indent_level = _measure_indent(raw)
        stripped = raw.lstrip(" \t")
        matched = _match_mark(stripped)
        if matched is not None:
            kind, (level, marker, body) = matched
            blocks.append(StructBlock(
                kind=kind, text=body, level=level, marker=marker,
                indent_level=indent_level, gap_section=pending_gap))
        else:
            blocks.append(StructBlock(
                kind="paragraph", text=stripped.strip(),
                indent_level=indent_level, gap_section=pending_gap))
        pending_gap = False
    return blocks


def render_text_for_coverage(text: str) -> str:
    """Texto TAL COMO se va a pintar, para el chequeo de glifos faltantes.

    Las marcas que el parser DESCARTA (``#`` de encabezado, ``*``/``•`` de
    viñeta) no se renderizan, así que no deben contar como caracteres sin
    glifo: si no, cada export de un apunte avisaría "⚠ Sin glifo: #" y el
    usuario creería que se le omiten los títulos. Reconstruye el contenido con
    los prefijos que SÍ se dibujan (``- `` para viñeta, ``N: `` para numerada).
    Sin estructura, devuelve el texto intacto.
    """
    if not detect_structure(text):
        return text
    parts: list[str] = []
    for b in parse_structure(text):
        if b.kind == "numbered":
            parts.append(f"{b.marker}: {b.text}")
        elif b.kind == "bullet":
            parts.append(f"- {b.text}")
        else:  # heading / paragraph: sólo el contenido (la # se descarta)
            parts.append(b.text)
    return "\n".join(parts)


class WriterStructureRenderer:
    """Renderiza apuntes estructurados reutilizando el motor de texto del banco.

    Mismo contrato que ConceptMapRenderer/DiagramRenderer: __init__(renderer) y
    render(text, options, page_height) -> list[Image RGB]. Replica el preámbulo
    COMPLETO de HandwritingRenderer.render_document (apply_style, supersample,
    _begin_render, fondo) para no perder papel/tinta/anti-aliasing.
    """

    def __init__(self, hw_renderer):
        self.hw = hw_renderer

    def render(self, text: str, options, page_height: "int | None" = None) -> list:
        if not PIL_OK:
            return []
        hw = self.hw
        # — Preámbulo idéntico a render_document —
        options = hw.apply_style(options)
        ss = max(1, int(getattr(options, "supersample", 1)))
        if ss > 1:
            big = hw._scaled_options(options, ss)
            big_h = None if page_height is None else page_height * ss
            return [hw._downscale(p, ss)
                    for p in self.render(text, big, big_h)]
        hw._begin_render(options)
        options = hw._apply_background_style(options)
        if page_height is None:
            page_height = options.page_height_px

        blocks = parse_structure(text)
        if not blocks:
            # Sin bloques (texto vacío): cae al camino plano, como render_document.
            return hw.render_pages(text, options, page_height)

        items = self._build_blocklines(blocks, options)
        return hw._flow_blocklines_to_pages(
            items, options, page_height, options.line_height_px)

    def _build_blocklines(self, blocks: list[StructBlock], options) -> list:
        """Convierte StructBlocks en _BlockLines, replicando la geometría
        por-bloque de render_document y sumándole indent_level y gap_section."""
        from dataclasses import replace

        from core.inkcore.renderer import (
            _HEADING_SCALE,
            _HEADING_SCALE_DEFAULT,
        )
        from core.inkcore.renderer_layout import _BlockLine

        hw = self.hw
        base_font = options.font_size
        usable_width = options.usable_width_px
        # Paso de grilla = el renglón FÍSICO (mm), no font_size (igual que
        # render_document): el cuerpo avanza un renglón real por línea.
        base_line_h = options.line_height_px
        indent_step = base_font * 0.9  # un escalón de sangría por nivel

        items: list = []
        for block in blocks:
            text = (block.text or "").strip()
            if not text:
                continue

            if block.kind == "heading":
                level = block.level or 1
                scale = _HEADING_SCALE.get(level, _HEADING_SCALE_DEFAULT)
                fs = max(1, int(base_font * scale))
                base_indent = 0
                prefix = ""
                gap_extra = int(base_font * 0.8)
            elif block.kind == "numbered":
                fs = base_font
                base_indent = int(base_font * 0.9)
                # Conserva el número LITERAL del usuario (sin auto-renumerar).
                prefix = f"{block.marker}: "
                gap_extra = int(base_font * 0.15)
            elif block.kind == "bullet":
                fs = base_font
                base_indent = int(base_font * 0.9)
                prefix = "- "
                gap_extra = int(base_font * 0.15)
            else:  # paragraph
                fs = base_font
                base_indent = 0
                prefix = ""
                gap_extra = int(base_font * 0.4)

            indent = base_indent + int(block.indent_level * indent_step)
            if block.gap_section:
                # Separación de sección: un hueco extra antes del bloque (se
                # cuantiza a renglón entero por el snap en fondos rayados).
                gap_extra += int(base_font * 0.6)

            bopts = replace(options, font_size=fs)
            line_h = base_line_h if fs == base_font else int(fs * options.line_height)
            boff = hw._line_baseline_offset(fs)
            block_usable = max(1, usable_width - indent)
            # Offset POR BLOQUE (no por letra), acotado: natural pero no caótico.
            bjx = hw._rng.randint(-4, 4)
            bjy = hw._rng.randint(-3, 3)

            wrapped = hw._soft_wrap_text(prefix + text, bopts, block_usable)
            for i, ln in enumerate(wrapped):
                img = hw._render_line(ln, bopts, block_usable)
                if img is not None:
                    angle = hw._rng.uniform(-0.5, 0.5)
                    img = img.rotate(angle, expand=False, resample=Image.BICUBIC)
                items.append(_BlockLine(
                    img=img,
                    x=options.margin_left_px + indent + bjx
                      + hw._next_margin_offset(options),
                    line_height=line_h,
                    gap_before=(gap_extra + bjy) if i == 0 else 0,
                    baseline_offset=boff,
                ))
        return items

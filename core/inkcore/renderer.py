import logging
import random
from dataclasses import dataclass, replace
from pathlib import Path

from core.inkcore.renderer_backgrounds import (
    BACKGROUND_STYLES,
    STYLE_PRESETS,
    BackgroundMixin,
)
from core.inkcore.renderer_glyph import GlyphLoadMixin

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

# Re-exportados para compatibilidad: BACKGROUND_STYLES y STYLE_PRESETS vivían
# acá antes de mover las decoraciones de fondo a renderer_backgrounds.py.
__all__ = [
    "BACKGROUND_STYLES",
    "STYLE_PRESETS",
    "HandwritingRenderer",
    "RenderOptions",
]


@dataclass
class RenderOptions:
    font_size: int = 40
    jitter_px: int = 3
    size_variation: float = 0.12
    letter_spacing: float = 1.1
    line_height: float = 1.6
    rotation_range: float = 4.0
    ink_alpha_min: float = 0.80
    ink_alpha_max: float = 1.0
    # Realismo de la escritura (Fase 3). Valores conservadores: suben la
    # credibilidad sin volver el texto ilegible.
    #   baseline_drift: amplitud máx (px) del vaivén lento de la línea base a lo
    #     largo del renglón — una persona no escribe perfectamente recto.
    #   kerning_jitter: fracción del hueco entre letras que varía al azar (0-1);
    #     da espaciado irregular y leves solapes como en la letra real.
    #   slant_deg: inclinación (shear) de cada glifo en grados; >0 = cursiva
    #     ligeramente reclinada a la derecha.
    baseline_drift: float = 1.2
    kerning_jitter: float = 0.5
    slant_deg: float = 0.0
    # Color de tinta. Los glifos del extractor son blancos (forma en alpha) para
    # verse sobre la UI oscura; sin recolorear serían INVISIBLES sobre el papel
    # claro. Un azul-negro de bolígrafo se ve más natural que el negro puro.
    ink_color: str = "#1A1A2E"
    style: str = "Limpio"
    mode: str = "PNG"
    page_width: int = 1240
    page_margin: int = 80
    background_color: str = "#FAFAFA"
    line_color: str = "#C8D8E8"
    draw_lines: bool = False
    # Estilo de fondo: "" | "hoja_blanca" | "libreta" | "hoja_cuadricula"
    background_style: str = ""


# Escalado de fuente por nivel de encabezado (h1 más grande que el cuerpo).
# Niveles >3 caen al valor por defecto: apenas mayores que un párrafo.
_HEADING_SCALE: dict[int, float] = {1: 1.5, 2: 1.3, 3: 1.15}
_HEADING_SCALE_DEFAULT = 1.1


@dataclass
class _BlockLine:
    """Un renglón ya renderizado listo para fluir en una página.

    Lo produce render_document por bloque (encabezado/lista/párrafo) y lo
    consume _flow_blocklines_to_pages, que sólo necesita saber dónde pegarlo
    en X, cuánto avanzar en Y y cuánto hueco extra dejar antes del renglón.
    """
    img: "Image.Image | None"
    x: int            # posición X absoluta de pegado (margen + sangría + jitter)
    line_height: int  # avance vertical de este renglón (mayor en encabezados)
    gap_before: int   # hueco extra antes del renglón (separación de bloque)


class HandwritingRenderer(BackgroundMixin, GlyphLoadMixin):
    def __init__(self, bank):
        self.bank = bank
        self._raw_cache: dict[str, Image.Image] = {}  # path -> RGBA image raw

    def apply_style(self, options: RenderOptions) -> RenderOptions:
        preset = STYLE_PRESETS.get(options.style, {})
        for k, v in preset.items():
            setattr(options, k, v)
        return options

    def render_transparent(self, text: str, options: RenderOptions) -> "Image.Image | None":
        """Como render_text pero sobre fondo TRANSPARENTE (RGBA), sin decoraciones.

        Pensado para compositar un bloque en una posición arbitraria (replicador):
        sólo la tinta queda, el resto es transparente, así no tapa lo de abajo.
        No aplica fondo/renglones (sería opaco); sí respeta wrap y la variación.
        """
        if not PIL_OK:
            return None
        options = self.apply_style(options)
        usable_width = max(1, options.page_width - 2 * options.page_margin)
        line_height_px = int(options.font_size * options.line_height)
        wrapped = self._soft_wrap_text(text, options, usable_width)
        rendered = [self._render_line(line, options, usable_width) for line in wrapped]
        total_h = max(line_height_px, options.page_margin * 2 + len(rendered) * line_height_px)
        canvas = Image.new("RGBA", (options.page_width, total_h), (0, 0, 0, 0))
        y_cursor = options.page_margin
        for line_img in rendered:
            if line_img:
                jitter_y = random.randint(-options.jitter_px, options.jitter_px)
                paste_y = max(0, y_cursor + jitter_y)
                if paste_y + line_img.height <= total_h:
                    canvas.paste(line_img, (options.page_margin, paste_y), line_img)
            y_cursor += line_height_px
        return canvas

    def render_text(self, text: str, options: RenderOptions) -> "Image.Image | None":
        """Renderiza texto completo. Usa render_pages internamente para textos largos."""
        if not PIL_OK:
            return None
        options = self.apply_style(options)
        options = self._apply_background_style(options)
        lines = text.split("\n")

        # Para textos con más de 30 líneas, usar render_pages y concatenar verticalmente
        if len(lines) > 30:
            pages = self.render_pages(text, options)
            if not pages:
                return None
            if len(pages) == 1:
                return pages[0]
            total_h = sum(p.height for p in pages) + (len(pages) - 1) * 20
            combined = Image.new("RGB", (options.page_width, total_h), "#E0E0E0")
            y_off = 0
            for page in pages:
                combined.paste(page, (0, y_off))
                y_off += page.height + 20
            return combined

        usable_width = options.page_width - 2 * options.page_margin
        line_height_px = int(options.font_size * options.line_height)

        # BUG-06 (faltaba en esta ruta): word-wrap antes de renderizar, igual que
        # render_pages. Sin esto, _render_line trunca (break) las líneas más anchas
        # que usable_width y se pierde texto — visible en el replicador, que llama
        # render_text por bloque. El writer principal ya usa render_pages.
        wrapped_lines = self._soft_wrap_text(text, options, usable_width)
        rendered_lines = [self._render_line(line, options, usable_width) for line in wrapped_lines]

        total_h = options.page_margin * 2 + len(rendered_lines) * line_height_px
        total_h = max(total_h, 400)
        canvas = Image.new("RGBA", (options.page_width, total_h), options.background_color)

        self._draw_background_decorations(canvas, options, line_height_px, total_h)

        y_cursor = options.page_margin
        for line_img in rendered_lines:
            if line_img:
                jitter_y = random.randint(-options.jitter_px, options.jitter_px)
                # Bug fix #3: clamp paste position so it never goes above the canvas top
                paste_y = max(0, y_cursor + jitter_y)
                # Also ensure we don't paste past the bottom of the canvas
                if paste_y + line_img.height <= total_h:
                    canvas.paste(line_img, (options.page_margin, paste_y), line_img)
                else:
                    canvas.paste(line_img, (options.page_margin, max(0, total_h - line_img.height)), line_img)
            y_cursor += line_height_px

        return canvas.convert("RGB")

    def _soft_wrap_text(
        self, text: str, options: RenderOptions, usable_width: int,
    ) -> list[str]:
        """BUG-06: word-wrap propio para evitar que _render_line descarte chars.

        Estima chars/línea con ancho promedio y parte palabras (no chars sueltos).
        Mantiene los \\n originales del usuario; solo wrappea líneas largas.
        """
        avg_char_w = max(8, int(options.font_size * 0.55))
        chars_per_line = max(10, usable_width // avg_char_w)
        out_lines: list[str] = []
        for raw in text.split("\n"):
            if len(raw) <= chars_per_line:
                out_lines.append(raw)
                continue
            words = raw.split(" ")
            current = ""
            for w in words:
                tentative = (current + " " + w).strip()
                if len(tentative) > chars_per_line and current:
                    out_lines.append(current)
                    current = w
                else:
                    current = tentative
            if current:
                out_lines.append(current)
        return out_lines

    def render_pages(
        self, text: str, options: RenderOptions, page_height: int = 1122
    ) -> list:
        """Renderiza texto dividido en páginas de altura fija. Retorna lista de imágenes RGB."""
        if not PIL_OK:
            return []
        options = self.apply_style(options)
        options = self._apply_background_style(options)
        usable_width = options.page_width - 2 * options.page_margin
        # BUG-06: wrap antes de renderizar para que párrafos largos no se trunquen
        lines = self._soft_wrap_text(text, options, usable_width)
        line_height_px = int(options.font_size * options.line_height)

        # Renderizar todas las líneas de texto
        rendered_lines = [self._render_line(line, options, usable_width) for line in lines]

        # Calcular cuántas líneas caben por página
        usable_height = page_height - 2 * options.page_margin
        lines_per_page = max(1, usable_height // line_height_px)

        pages = []
        for page_start in range(0, len(rendered_lines), lines_per_page):
            page_lines = rendered_lines[page_start:page_start + lines_per_page]
            canvas = Image.new("RGBA", (options.page_width, page_height), options.background_color)

            self._draw_background_decorations(canvas, options, line_height_px, page_height)

            y_cursor = options.page_margin
            for line_img in page_lines:
                if line_img:
                    jitter_y = random.randint(-options.jitter_px, options.jitter_px)
                    paste_y = max(0, min(page_height - line_img.height, y_cursor + jitter_y))
                    if paste_y + line_img.height <= page_height:
                        canvas.paste(line_img, (options.page_margin, paste_y), line_img)
                y_cursor += line_height_px

            pages.append(canvas.convert("RGB"))

        return pages if pages else [Image.new("RGB", (options.page_width, page_height), "#FFFFFF")]

    def render_document(self, doc, options: RenderOptions, page_height: int = 1122) -> list:
        """Renderiza un Document estructurado respetando su jerarquía.

        A diferencia de render_pages (que trata todo como un párrafo plano), recorre
        los bloques del Document en orden de arriba-abajo y los dibuja según su tipo:

          - HEADING:   font_size escalado por heading_level (h1≈1.5x … h3≈1.15x).
          - LIST_ITEM: viñeta "- " + sangría fija + el texto, con word-wrap.
          - PARAGRAPH: word-wrap por palabra, como el render normal.
          - CODE:      como párrafo, con una sangría leve.

        Cada BLOQUE (no cada letra) recibe un pequeño offset X/Y acotado y cada
        renglón una micro-rotación, para que se vea hecho a mano sin desordenarse:
        el bloque siempre arranca en su margen+sangría y nunca se encima con el de
        arriba (el flujo vertical garantiza separación). El layout es flujo limpio
        de arriba-abajo; NO se copian las coordenadas crudas del OCR (un escaneo
        torcido daría un render torcido). Retorna una lista de imágenes RGB, igual
        que render_pages, para que la UI las muestre/exporte sin cambios.

        Si el Document no tiene bloques, cae a render_pages sobre su texto plano.
        """
        if not PIL_OK:
            return []
        options = self.apply_style(options)
        options = self._apply_background_style(options)

        blocks = [b for page in getattr(doc, "pages", []) for b in page.blocks]
        if not blocks:
            text = doc.plain_text() if hasattr(doc, "plain_text") else str(doc)
            return self.render_pages(text, options, page_height)

        base_font = options.font_size
        usable_width = options.page_width - 2 * options.page_margin
        base_line_h = int(base_font * options.line_height)

        items: list[_BlockLine] = []
        for block in blocks:
            text = (getattr(block, "text", "") or "").strip()
            if not text:
                continue
            btype = str(getattr(block, "block_type", "paragraph"))

            if btype == "heading":
                level = getattr(block, "heading_level", 1) or 1
                scale = _HEADING_SCALE.get(level, _HEADING_SCALE_DEFAULT)
                fs = max(1, int(base_font * scale))
                indent = 0
                prefix = ""
                gap_extra = int(base_font * 0.8)
            elif btype == "list_item":
                fs = base_font
                indent = int(base_font * 0.9)
                prefix = "- "
                gap_extra = int(base_font * 0.15)
            elif btype == "code":
                fs = base_font
                indent = int(base_font * 0.5)
                prefix = ""
                gap_extra = int(base_font * 0.35)
            else:  # paragraph / caption / unknown
                fs = base_font
                indent = 0
                prefix = ""
                gap_extra = int(base_font * 0.4)

            bopts = replace(options, font_size=fs)
            line_h = int(fs * options.line_height)
            block_usable = max(1, usable_width - indent)
            # Offset POR BLOQUE (no por letra), acotado: natural pero no caótico.
            bjx = random.randint(-4, 4)
            bjy = random.randint(-3, 3)

            wrapped = self._soft_wrap_text(prefix + text, bopts, block_usable)
            for i, ln in enumerate(wrapped):
                img = self._render_line(ln, bopts, block_usable)
                # Micro-rotación de renglón (±0.5°): expand=False conserva el tamaño
                # para no descuadrar el offset ni encimar renglones vecinos.
                if img is not None:
                    angle = random.uniform(-0.5, 0.5)
                    img = img.rotate(angle, expand=False, resample=Image.BICUBIC)
                items.append(_BlockLine(
                    img=img,
                    x=options.page_margin + indent + bjx,
                    line_height=line_h,
                    # el hueco de bloque + el jitter Y sólo en el primer renglón
                    gap_before=(gap_extra + bjy) if i == 0 else 0,
                ))

        return self._flow_blocklines_to_pages(items, options, page_height, base_line_h)

    def _flow_blocklines_to_pages(
        self, items: list, options: RenderOptions, page_height: int, base_line_h: int,
    ) -> list:
        """Reparte los renglones ya renderizados en páginas de altura fija.

        Mantiene un cursor vertical, abre página nueva cuando un renglón no entra y
        nunca pega por encima del margen ni fuera de la hoja. Las decoraciones de
        fondo (renglones/cuadrícula/margen) se dibujan por página con el paso del
        cuerpo, así el texto de párrafo cae sobre los renglones de la libreta.
        """
        bottom = page_height - options.page_margin

        def _new_canvas():
            c = Image.new("RGBA", (options.page_width, page_height), options.background_color)
            self._draw_background_decorations(c, options, base_line_h, page_height)
            return c

        pages = []
        canvas = _new_canvas()
        y = options.page_margin
        for it in items:
            y += max(0, it.gap_before)
            # ¿Cabe este renglón? Si no, cierra la página y abre otra.
            if it.line_height > 0 and y + it.line_height > bottom and y > options.page_margin:
                pages.append(canvas.convert("RGB"))
                canvas = _new_canvas()
                y = options.page_margin
            if it.img is not None:
                x = max(0, it.x)
                paste_y = max(0, min(page_height - it.img.height, y))
                canvas.paste(it.img, (x, paste_y), it.img)
            y += it.line_height

        pages.append(canvas.convert("RGB"))
        return pages

    def _render_line(self, text: str, options: RenderOptions, max_width: int) -> "Image.Image | None":
        if not PIL_OK:
            return None
        if not text.strip():
            return None
        # Bug fix #1: increase canvas height to accommodate descenders.
        # 80% baseline means up to 20% below for ascenders and potentially
        # the full glyph height above that.  Reserve font_size * 2.5 so that
        # tall glyphs (ascenders) and deep glyphs (descenders g,p,q,y) never
        # get clipped at the bottom.
        h = int(options.font_size * 2.5)
        line_canvas = Image.new("RGBA", (max_width, h), (0, 0, 0, 0))
        x_cursor = 0

        # Bug fix #2: minimum word space of 4px for very small fonts
        word_space = max(4, int(options.font_size * 0.4))
        spacing_gap_base = max(2, int(options.font_size * 0.08))
        kj = max(0.0, min(1.0, options.kerning_jitter))
        # Jitter vertical SUTIL: como máx ±2px. Antes usaba jitter_px (≈3) y
        # descuadraba letras vecinas; el horizontal sigue gobernado por jitter_px.
        vjit = min(2, max(0, options.jitter_px))

        # Fase 3 — deriva de línea base: un offset que se mueve poco a poco a lo
        # largo del renglón (random walk acotado) en vez de una recta perfecta.
        # Cada letra hereda casi todo el offset de la anterior + un pasito al
        # azar, así el vaivén es suave y no un temblor letra-a-letra.
        drift = 0.0
        drift_amp = max(0.0, options.baseline_drift)

        # WRAP POR PALABRA: se mide cada palabra entera y, si no entra en lo que
        # queda del renglón, se pasa COMPLETA a la siguiente línea (el caller ya
        # repartió en líneas lógicas). Sólo se parte una palabra si por sí sola
        # excede el ancho total disponible. Así "la" nunca queda partida.
        first_word = True
        for word in text.split(" "):
            if word == "":
                if not first_word:
                    x_cursor += word_space
                continue
            # Cargar los glifos de la palabra una sola vez (variation=True ⇒
            # instancia distinta por aparición) y medir su ancho total.
            glyphs = []  # (char, img, gap) de la palabra
            word_w = 0
            for ch in word:
                glyph_entry = self.bank.get_best_glyph(ch.lower(), variation=True)
                if glyph_entry is None:
                    glyph_entry = self.bank.get_best_glyph(ch, variation=True)
                if glyph_entry and Path(glyph_entry.image_path).exists():
                    glyph_img = self._load_glyph(glyph_entry.image_path, options, ch)
                else:
                    glyph_img = self._render_fallback_char(ch, options)
                if glyph_img is None:
                    continue
                # Kerning variable: el hueco base puede encogerse (leve solape) o
                # crecer al azar según kerning_jitter. Nunca baja de 1px.
                gap = spacing_gap_base
                if kj > 0:
                    gap += round(random.uniform(-spacing_gap_base * kj, spacing_gap_base * kj))
                gap = max(1, gap)
                glyphs.append((ch, glyph_img, gap))
                word_w += glyph_img.width + gap

            if not glyphs:
                continue

            # ¿Cabe la palabra entera en lo que resta del renglón?
            if not first_word and x_cursor + word_space + word_w > max_width:
                break  # no parte la palabra: la deja para la siguiente línea
            if not first_word:
                x_cursor += word_space
            first_word = False

            for ch, glyph_img, gap in glyphs:
                # Sólo se llega a cortar acá si la palabra sola excede max_width.
                if x_cursor > 0 and x_cursor + glyph_img.width > max_width:
                    break
                jitter_y = random.randint(-vjit, vjit) if vjit > 0 else 0
                # Avanza el random walk de la línea base, acotado a ±drift_amp,
                # con paso reducido (±0.25) para que el renglón ondule muy poco.
                if drift_amp > 0:
                    drift += random.uniform(-drift_amp * 0.25, drift_amp * 0.25)
                    drift = max(-drift_amp, min(drift_amp, drift))
                baseline = int(h * 0.72) + round(drift)
                # Línea base por clase: las de x-height asientan su base en el
                # baseline; las ascendentes (asta alta) suben; las descendentes
                # (g,j,p,q,y) meten ~31% del glifo (su cola) bajo el baseline.
                if self._vertical_class(ch) == "desc":
                    y_pos = baseline - int(glyph_img.height * 0.69)
                else:
                    y_pos = baseline - glyph_img.height
                # Apply jitter, then clamp to stay within the canvas vertically
                y_pos = max(0, min(h - glyph_img.height, y_pos + jitter_y))
                line_canvas.paste(glyph_img, (x_cursor, y_pos), glyph_img)
                x_cursor += glyph_img.width + gap

        return line_canvas

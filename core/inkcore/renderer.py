import logging
import random
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False


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
    style: str = "Limpio"
    mode: str = "PNG"
    page_width: int = 1240
    page_margin: int = 80
    background_color: str = "#FAFAFA"
    line_color: str = "#C8D8E8"
    draw_lines: bool = False
    # Estilo de fondo: "" | "hoja_blanca" | "libreta" | "hoja_cuadricula"
    background_style: str = ""


BACKGROUND_STYLES: dict[str, dict] = {
    "hoja_blanca": {
        "bg": "#FFFFFF",
        "draw_lines": False,
        "margin_color": None,
    },
    "libreta": {
        "bg": "#FEFCE8",
        "draw_lines": True,
        "line_color": "#B9D5E0",
        "margin_color": "#F4A0A0",
        "margin_x": 80,
    },
    "hoja_cuadricula": {
        "bg": "#F0F4FF",
        "draw_lines": True,
        "line_color": "#C5D5F0",
        "draw_grid": True,
        "grid_size": 28,
    },
}


STYLE_PRESETS: dict[str, dict] = {
    "Limpio": {"jitter_px": 2, "size_variation": 0.08, "rotation_range": 2.0},
    "Escolar": {"jitter_px": 4, "size_variation": 0.14, "rotation_range": 5.0, "draw_lines": True},
    "Universitario": {"jitter_px": 2, "size_variation": 0.10, "rotation_range": 3.0},
    "Relajado": {"jitter_px": 6, "size_variation": 0.20, "rotation_range": 8.0},
    "Examen": {"jitter_px": 3, "size_variation": 0.10, "rotation_range": 3.0, "draw_lines": True},
}


class HandwritingRenderer:
    def __init__(self, bank):
        self.bank = bank
        self._raw_cache: dict[str, Image.Image] = {}  # path -> RGBA image raw

    def apply_style(self, options: RenderOptions) -> RenderOptions:
        preset = STYLE_PRESETS.get(options.style, {})
        for k, v in preset.items():
            setattr(options, k, v)
        return options

    def _apply_background_style(self, options: RenderOptions) -> RenderOptions:
        """Aplica el estilo de fondo (libreta, cuadrícula, etc.) a las opciones."""
        style_def = BACKGROUND_STYLES.get(options.background_style)
        if style_def is None:
            return options
        if "bg" in style_def:
            options.background_color = style_def["bg"]
        if "draw_lines" in style_def:
            options.draw_lines = style_def["draw_lines"]
        if "line_color" in style_def:
            options.line_color = style_def["line_color"]
        return options

    def _draw_background_decorations(
        self,
        canvas: "Image.Image",
        options: RenderOptions,
        line_height_px: int,
        canvas_h: int,
    ) -> None:
        """Dibuja líneas, cuadrícula y margen según el background_style."""
        if not PIL_OK:
            return
        style_def = BACKGROUND_STYLES.get(options.background_style, {})
        draw = ImageDraw.Draw(canvas)

        if style_def.get("draw_grid"):
            # Cuadrícula
            grid_size = style_def.get("grid_size", 28)
            line_col = style_def.get("line_color", "#C5D5F0")
            x = options.page_margin
            while x < options.page_width - options.page_margin:
                draw.line([(x, 0), (x, canvas_h)], fill=line_col, width=1)
                x += grid_size
            y = options.page_margin
            while y < canvas_h - options.page_margin:
                draw.line([(0, y), (options.page_width, y)], fill=line_col, width=1)
                y += grid_size
        elif options.draw_lines:
            # Líneas horizontales
            y = options.page_margin + line_height_px
            while y < canvas_h - options.page_margin:
                draw.line(
                    [(options.page_margin, y), (options.page_width - options.page_margin, y)],
                    fill=options.line_color, width=1,
                )
                y += line_height_px

        # Línea de margen roja (solo libreta)
        if style_def.get("margin_color"):
            margin_x = style_def.get("margin_x", 80)
            draw.line([(margin_x, 0), (margin_x, canvas_h)],
                      fill=style_def["margin_color"], width=2)

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

        rendered_lines = []
        for line in lines:
            rendered_lines.append(self._render_line(line, options, usable_width))

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

        words = text.split(" ")
        # Bug fix #4: implement simple word-wrap instead of hard break mid-line
        wrapped_chars: list[tuple[str, bool]] = []  # (char, is_space)
        for wi, word in enumerate(words):
            for ch in word:
                wrapped_chars.append((ch, False))
            if wi < len(words) - 1:
                wrapped_chars.append((" ", True))

        # Bug fix #2: minimum word space of 4px for very small fonts
        word_space = max(4, int(options.font_size * 0.4))

        for char, is_space in wrapped_chars:
            if is_space:
                x_cursor += word_space
                continue
            glyph_entry = self.bank.get_best_glyph(char.lower())
            if glyph_entry is None:
                glyph_entry = self.bank.get_best_glyph(char)
            if glyph_entry and Path(glyph_entry.image_path).exists():
                glyph_img = self._load_glyph(glyph_entry.image_path, options)
            else:
                glyph_img = self._render_fallback_char(char, options)
            if glyph_img is None:
                continue
            # Bug fix #4: soft wrap — skip glyphs that exceed max_width rather
            # than hard-breaking; caller splits into logical lines already.
            if x_cursor + glyph_img.width > max_width:
                break
            # Bug fix #1: baseline / descender alignment
            # Apply jitter independently from the baseline calculation so that
            # a negative jitter never pushes y_pos below 0.
            jitter_y = random.randint(-options.jitter_px, options.jitter_px)
            baseline = int(h * 0.75)  # 75% gives room for descenders below
            # Align glyph top edge so its bottom sits at the baseline
            y_pos = baseline - glyph_img.height
            # Apply jitter, then clamp to stay within the canvas vertically
            y_pos = max(0, min(h - glyph_img.height, y_pos + jitter_y))
            line_canvas.paste(glyph_img, (x_cursor, y_pos), glyph_img)
            spacing_gap = max(2, int(options.font_size * 0.08))
            x_cursor += glyph_img.width + spacing_gap

        return line_canvas

    def _load_glyph(self, path: str, options: RenderOptions) -> "Image.Image | None":
        if not PIL_OK:
            return None
        try:
            # Cache de imagen raw (sin escalar/rotar) para no abrir archivo desde disco cada vez
            if path in self._raw_cache:
                raw = self._raw_cache[path].copy()
            else:
                raw = Image.open(path)
                # Bug fix #3: palette ("P") images must be converted before RGBA
                # to avoid unexpected channel counts from split().
                if raw.mode == "P":
                    raw = raw.convert("RGBA")
                else:
                    raw = raw.convert("RGBA")
                # Limitar cache a 500 entradas (FIFO)
                if len(self._raw_cache) >= 500:
                    oldest_key = next(iter(self._raw_cache))
                    del self._raw_cache[oldest_key]
                self._raw_cache[path] = raw
                raw = raw.copy()
            img = raw
            # Bug fix #4: guard against zero-dimension glyphs
            if img.width < 1 or img.height < 1:
                return None
            size_factor = 1.0 + random.uniform(-options.size_variation, options.size_variation)
            target_h = max(1, int(options.font_size * size_factor))
            ratio = target_h / img.height
            target_w = max(1, int(img.width * ratio))
            img = img.resize((target_w, target_h), Image.LANCZOS)
            if options.rotation_range > 0:
                angle = random.uniform(-options.rotation_range, options.rotation_range)
                img = img.rotate(angle, expand=True, resample=Image.BICUBIC)
            # Guard again after rotation (expand=True can theoretically produce odd sizes)
            if img.width < 1 or img.height < 1:
                return None
            alpha_factor = random.uniform(options.ink_alpha_min, options.ink_alpha_max)
            if alpha_factor < 1.0:
                r, g, b, a = img.split()
                a = a.point(lambda v: int(v * alpha_factor))
                img = Image.merge("RGBA", (r, g, b, a))
            return img
        except Exception as e:
            logger.debug(f"Could not load glyph {path}: {e}")
            return None

    def _render_fallback_char(self, char: str, options: RenderOptions) -> "Image.Image | None":
        if not PIL_OK:
            return None
        size = options.font_size
        img = Image.new("RGBA", (int(size * 0.7), size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/liberation/LiberationMono-Regular.ttf", size - 4)
        except Exception:
            font = ImageFont.load_default()
        draw.text((2, 2), char, fill=(40, 40, 40, 200), font=font)
        return img


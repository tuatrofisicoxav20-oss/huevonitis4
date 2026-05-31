"""Carga y recoloreado de glifos para el HandwritingRenderer.

Se separa de renderer.py para mantener cada módulo bajo ~420 líneas. El
HandwritingRenderer hereda de GlyphLoadMixin, así que estos métodos siguen
accesibles en la clase (incluidos _recolor_ink / _vertical_class, que usan
los tests directamente sobre HandwritingRenderer).
"""
import logging
import random

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False


class GlyphLoadMixin:
    """Carga, escala, rota y recolorea los glifos del banco.

    Espera que la clase concreta tenga ``self.bank`` y ``self._raw_cache``
    (cache path -> imagen RGBA cruda) inicializados en su __init__.
    """

    # Categorías verticales para una línea base creíble (latina minúscula).
    _ASCENDERS = frozenset("bdfhklt")
    _DESCENDERS = frozenset("gjpqy")

    @classmethod
    def _vertical_class(cls, char: str) -> str:
        c = char.lower()
        if c in cls._DESCENDERS:
            return "desc"
        if c in cls._ASCENDERS:
            return "asc"
        return "xheight"

    @staticmethod
    def _recolor_ink(img: "Image.Image", ink_color: str) -> "Image.Image":
        """Repinta la forma del glifo con ink_color, preservando su alpha.

        La forma sale del canal alpha (glifos del extractor: tinta blanca, forma
        en alpha) o, si el alpha es casi uniforme (glifo opaco bulk/legacy), de la
        luminancia invertida (lo oscuro = tinta). Así la tinta siempre es visible
        sobre el papel y con un único color de bolígrafo coherente.
        """
        from PIL import ImageColor
        try:
            r, g, b = ImageColor.getrgb(ink_color)[:3]
        except (ValueError, TypeError):
            r, g, b = (26, 26, 46)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        mask = img.getchannel("A")
        lo, hi = mask.getextrema()
        if hi - lo < 12:  # alpha plano → glifo opaco: derivar forma de la luminancia
            mask = img.convert("L").point(lambda v: 255 - v)
        out = Image.new("RGBA", img.size, (r, g, b, 0))
        out.putalpha(mask)
        return out

    def _load_glyph(self, path: str, options) -> "Image.Image | None":
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
            # Recolorear la tinta al color del bolígrafo. Los glifos del extractor
            # son RGB blanco con la forma en el alpha; sobre papel claro serían
            # invisibles. Repinta la forma con ink_color preservando el alpha
            # (anti-aliasing). Maneja también glifos opacos (forma en luminancia).
            img = self._recolor_ink(img, options.ink_color)
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

    def _render_fallback_char(self, char: str, options) -> "Image.Image | None":
        if not PIL_OK:
            return None
        size = options.font_size
        img = Image.new("RGBA", (int(size * 0.7), size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/liberation/LiberationMono-Regular.ttf", size - 4)
        except Exception:
            font = ImageFont.load_default()
        from PIL import ImageColor
        try:
            ink = ImageColor.getrgb(options.ink_color)[:3]
        except (ValueError, TypeError):
            ink = (26, 26, 46)
        draw.text((2, 2), char, fill=(*ink, 220), font=font)
        return img

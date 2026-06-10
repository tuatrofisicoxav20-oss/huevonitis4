"""Carga y recoloreado de glifos para el HandwritingRenderer.

Se separa de renderer.py para mantener cada módulo bajo ~420 líneas. El
HandwritingRenderer hereda de GlyphLoadMixin, así que estos métodos siguen
accesibles en la clase (incluidos _recolor_ink / _vertical_class, que usan
los tests directamente sobre HandwritingRenderer).

R2 — escala PROPORCIONAL: cada glifo se escala por la fracción de renglón que
SU tinta ocupaba en la hoja de captura (alto_tinta / em de su hoja), nunca
normalizado a una altura de clase (eso era R-BUG-01: todas las x-height
clavadas en el mismo px). El baseline medido viaja con la imagen para que el
layout asiente cada glifo en la línea base real (R-BUG-02).
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

    # Categorías verticales (latina minúscula). R2: ya NO posicionan cuando el
    # glifo trae baseline medido/estimado; quedan como fallback para glifos
    # ilegibles por el estimador y para el escalado sin métricas.
    _ASCENDERS = frozenset("bdfhklt")
    _DESCENDERS = frozenset("gjpqy")

    @classmethod
    def _vertical_class(cls, char: str) -> str:
        c = char.lower()
        if c in cls._DESCENDERS:
            return "desc"
        if c in cls._ASCENDERS:
            return "asc"
        # Mayúsculas y dígitos suben hasta la cap-height: cuentan como ascendentes
        # para que su altura objetivo sea la de un asta alta, no la de x-height.
        if char.isupper() or char.isdigit():
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

    def _load_glyph(self, path: str, options, char: "str | None" = None,
                    geo: "dict | None" = None):
        """Carga un glifo listo para pegar. Devuelve (imagen, baseline_px) o None.

        ``baseline_px`` es la fila de la IMAGEN FINAL (ya escalada/rotada) donde
        asienta la línea base del glifo, o -1 si no hay métricas (el layout cae
        a la clase vertical legacy). ``geo`` es la geometría del entry (R1):
        baseline_off/em en PX DE CAPTURA del PNG original.
        """
        if not PIL_OK:
            return None
        try:
            # Cache de imagen raw (sin escalar/rotar) para no abrir archivo desde disco cada vez
            if path in self._raw_cache:
                raw = self._raw_cache[path].copy()
            else:
                raw = Image.open(path).convert("RGBA")
                # Limitar cache a 500 entradas (FIFO)
                if len(self._raw_cache) >= 500:
                    oldest_key = next(iter(self._raw_cache))
                    del self._raw_cache[oldest_key]
                self._raw_cache[path] = raw
                raw = raw.copy()
            img = raw
            if img.width < 1 or img.height < 1:
                return None
            # Recolorear la tinta al color del bolígrafo. Los glifos del extractor
            # son RGB blanco con la forma en el alpha; sobre papel claro serían
            # invisibles. Repinta la forma con ink_color preservando el alpha.
            img = self._recolor_ink(img, options.ink_color)
            # Recortar al bounding box REAL de la tinta: el padding transparente
            # del banco es irregular y mediría aire. ink_top queda en COORDS DEL
            # PNG = las mismas del baseline_off del manifest.
            bbox = img.getchannel("A").getbbox()
            ink_top = bbox[1] if bbox else 0
            if bbox:
                img = img.crop(bbox)
            if img.width < 1 or img.height < 1:
                return None

            size_factor = 1.0 + random.uniform(-options.size_variation, options.size_variation)
            baseline_in = -1.0
            if geo and geo.get("em_px", 0) > 0 and geo.get("baseline_off", -1) >= 0:
                # R2 — ESCALA PROPORCIONAL: la tinta ocupa en el render la misma
                # fracción del renglón (font_size = em) que ocupaba en su hoja.
                # Clamp de sanidad contra métricas corruptas, no contra la
                # variación natural.
                frac = min(1.6, max(0.04, img.height / geo["em_px"]))
                target_h = max(1, round(options.font_size * frac * size_factor))
                # Baseline en coords del crop, escalado con la imagen.
                baseline_in = (geo["baseline_off"] - ink_top) * (target_h / img.height)
                baseline_in = min(target_h * 1.4, max(0.0, baseline_in))
            else:
                # Fallback sin métricas: altura por clase tipográfica (legacy).
                # x-height ≈ 45% del renglón, astas/colas ≈ 1.45×.
                x_height = options.font_size * 0.45
                cls = self._vertical_class(char) if char else "xheight"
                base_h = x_height if cls == "xheight" else x_height * 1.45
                target_h = max(1, int(base_h * size_factor))
            ratio = target_h / img.height
            target_w = max(1, int(img.width * ratio))
            img = img.resize((target_w, target_h), Image.LANCZOS)

            if options.rotation_range > 0:
                angle = random.uniform(-options.rotation_range, options.rotation_range)
                pre_h = img.height
                img = img.rotate(angle, expand=True, resample=Image.BICUBIC)
                # expand=True centra el contenido en el lienzo nuevo: el
                # baseline baja media diferencia. (El giro del propio baseline
                # es <1px a estos ángulos; no se modela.)
                if baseline_in >= 0:
                    baseline_in += (img.height - pre_h) / 2.0
            # Inclinación tipo cursiva: shear horizontal. slant_deg>0 recuesta
            # el glifo a la derecha. El mapeo afín toma input_x = x + shear*(y-h):
            # en la base no hay desplazamiento, arriba se corre shear*h. No
            # cambia alturas → el baseline no se ajusta.
            slant = (getattr(options, "slant_deg", 0.0) or 0.0) + (getattr(self, "_cur_line_slant", 0.0) or 0.0)
            if abs(slant) > 0.1:
                import math
                shear = math.tan(math.radians(slant))
                extra = math.ceil(abs(shear) * img.height)
                if extra > 0:
                    new_w = img.width + extra
                    img = img.transform(
                        (new_w, img.height), Image.AFFINE,
                        (1, shear, -shear * img.height if shear > 0 else 0.0, 0, 1, 0),
                        resample=Image.BICUBIC,
                    )
            if img.width < 1 or img.height < 1:
                return None
            # Trazo más sólido/oscuro (bolígrafo, no lápiz): gamma<1 sobre el alpha
            # empuja los píxeles de borde hacia opaco. Luego la "presión" por glifo
            # (alpha_factor) lo atenúa un poco al azar, variando entre letras.
            ink_boost = getattr(options, "ink_boost", 1.0) or 1.0
            alpha_factor = random.uniform(options.ink_alpha_min, options.ink_alpha_max)
            if ink_boost != 1.0 or alpha_factor < 1.0:
                r, g, b, a = img.split()
                if ink_boost != 1.0:
                    boost_lut = [min(255, int(((v / 255.0) ** ink_boost) * 255)) for v in range(256)]
                    a = a.point(boost_lut)
                if alpha_factor < 1.0:
                    a = a.point(lambda v: int(v * alpha_factor))
                img = Image.merge("RGBA", (r, g, b, a))
            return img, int(round(baseline_in)) if baseline_in >= 0 else -1
        except Exception as e:
            logger.debug(f"Could not load glyph {path}: {e}")
            return None

    def _render_fallback_char(self, char: str, options, missing: bool = False) -> "Image.Image | None":
        """Glifo de respaldo (fuente mono) para un carácter sin variante en el banco.

        Fase 6.5: si ``missing`` es True (no está en el banco), se marca VISIBLE —
        en rojo y subrayado — para que en la previsualización el usuario vea qué
        carácter le falta capturar, en vez de un hueco silencioso.
        """
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
        if missing:
            mark = (204, 32, 32)  # rojo: carácter faltante en el banco
            draw.text((2, 2), char, fill=(*mark, 235), font=font)
            draw.line([(2, size - 3), (int(size * 0.7) - 2, size - 3)], fill=(*mark, 235), width=2)
        else:
            draw.text((2, 2), char, fill=(*ink, 220), font=font)
        return img

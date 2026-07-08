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
                    geo: "dict | None" = None, rotation: "float | None" = None,
                    rng: "random.Random | None" = None,
                    size_drift: float = 0.0, slant_extra: float = 0.0,
                    pressure: float = 0.0):
        """Carga un glifo listo para pegar. Devuelve (imagen, baseline_px) o None.

        ``baseline_px`` es la fila de la IMAGEN FINAL (ya escalada/rotada) donde
        asienta la línea base del glifo, o -1 si no hay métricas (el layout cae
        a la clase vertical legacy). ``geo`` es la geometría del entry (R1):
        baseline_off/em en PX DE CAPTURA del PNG original.

        R3: ``rotation`` viene precalculada por el layout (proceso OU a lo
        largo del renglón — la muñeca deriva, no tirita); None = sorteo local
        legacy. ``rng`` es el RNG inyectado del render; None = random global
        (compat con llamadas directas sin _begin_render).

        R5: ``size_drift``/``slant_extra`` son la deriva OU intra-renglón (C1):
        el tamaño y la inclinación del vecino se heredan, no se sortean i.i.d.

        R14 (Track A): ``pressure`` (≈coupling·e(t), adimensional) modula el
        gamma del alpha — presión alta = trazo más oscuro y un pelo más ancho
        (los bordes suben a opaco); mano liviana = más claro. 0.0 = sin
        efecto (byte-idéntico).
        """
        if not PIL_OK:
            return None
        rnd = rng or random
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
            # R6 (D1): micro-variación HSV por glifo — la carga del bolígrafo
            # nunca deposita el mismo color exacto dos veces.
            ink_hex = options.ink_color
            sj, vj = getattr(options, "ink_hsv_jitter", (0.0, 0.0)) or (0.0, 0.0)
            if sj > 0 or vj > 0:
                from core.inkcore.renderer_ink import jitter_ink_color
                ink_hex = jitter_ink_color(ink_hex, rnd, sj, vj)
            if pressure:
                # R14 (Track A): la presión modula la DENSIDAD de depósito →
                # el COLOR (V del HSV), no solo el alpha: edge_reconstruct
                # binariza y reconstruye el alpha, pero preserva el color del
                # glifo (mediana de sus opacos) — la oscuridad viaja ahí.
                import colorsys

                from PIL import ImageColor
                press = min(0.6, max(-0.6, pressure))
                try:
                    pr, pg, pb = ImageColor.getrgb(ink_hex)[:3]
                except (ValueError, TypeError):
                    pr, pg, pb = (26, 26, 46)
                ph, ps, pv = colorsys.rgb_to_hsv(pr / 255, pg / 255, pb / 255)
                pv = min(1.0, max(0.0, pv * (1.0 - 0.45 * press)))
                r2, g2, b2 = colorsys.hsv_to_rgb(ph, ps, pv)
                ink_hex = (f"#{int(r2 * 255):02x}{int(g2 * 255):02x}"
                           f"{int(b2 * 255):02x}")
            img = self._recolor_ink(img, ink_hex)
            # Recortar al bounding box REAL de la tinta: el padding transparente
            # del banco es irregular y mediría aire. ink_top queda en COORDS DEL
            # PNG = las mismas del baseline_off del manifest.
            bbox = img.getchannel("A").getbbox()
            ink_top = bbox[1] if bbox else 0
            if bbox:
                img = img.crop(bbox)
            if img.width < 1 or img.height < 1:
                return None

            # R3: gauss truncada en vez de uniform — la variación de tamaño de
            # una mano es de campana, no de dado. R5: encima va size_drift (la
            # deriva OU del renglón); el componente i.i.d. queda reducido.
            from core.inkcore.renderer_noise import tnorm
            sv = options.size_variation
            iid = tnorm(rnd, 0.0, sv * 0.3, -sv * 0.6, sv * 0.6) if sv > 0 else 0.0
            size_factor = max(0.5, 1.0 + iid + size_drift)
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
            # R5 (C4): warp elástico POR INSTANCIA — dos apariciones del mismo
            # glifo nunca son idénticas, ni con 1 variante en el banco. Se
            # aplica ANTES del resize (en px de captura hay resolución para que
            # el remuestreo BICUBIC deforme de verdad; después sería sub-píxel).
            warp = max(0.0, getattr(options, "warp_strength", 0.0))
            if warp > 0:
                from core.inkcore.renderer_warp import elastic_warp
                img = elastic_warp(img, rnd, warp)

            ratio = target_h / img.height
            target_w = max(1, int(img.width * ratio))
            # R17d — asta ascendente: la 'l' (etc.) se estira SOLO en vertical
            # (target_w se fija con el ratio normal, ANTES de crecer target_h),
            # así deja de confundirse con la 'i'. El baseline escala con la
            # altura nueva → se queda abajo y el asta crece hacia ARRIBA.
            asc = getattr(options, "ascender_boost", 0.0)
            if asc > 0 and char and char in getattr(options, "ascender_chars", ""):
                b = 1.0 + min(1.2, asc)
                target_h = max(1, int(target_h * b))
                if baseline_in >= 0:
                    baseline_in *= b
            # R17e — jitter de proporción por instancia (rompe "clones" sin
            # distorsionar la topología). RNG del layout sólo si la perilla >0.
            aj = getattr(options, "glyph_aspect_jitter", 0.0)
            if aj > 0:
                aj = min(0.2, aj)
                fx = 1.0 + tnorm(rnd, 0.0, aj, -2.0 * aj, 2.0 * aj)
                fy = 1.0 + tnorm(rnd, 0.0, aj, -2.0 * aj, 2.0 * aj)
                target_w = max(1, int(target_w * fx))
                target_h = max(1, int(target_h * fy))
                if baseline_in >= 0:
                    baseline_in *= fy
            img = img.resize((target_w, target_h), Image.LANCZOS)

            if rotation is not None:
                angle = rotation
            elif options.rotation_range > 0:
                angle = rnd.uniform(-options.rotation_range, options.rotation_range)
            else:
                angle = 0.0
            if abs(angle) > 0.05:
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
            slant = ((getattr(options, "slant_deg", 0.0) or 0.0)
                     + (getattr(self, "_cur_line_slant", 0.0) or 0.0)
                     + slant_extra)
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
            if pressure:
                # R14 (Track A): presión→oscuridad. El gamma efectivo del
                # alpha baja con presión positiva (bordes hacia opaco: trazo
                # más oscuro/ancho) y sube con presión negativa (más claro).
                # Clamp duro: nunca borra trazos finos ni satura del todo.
                press = min(0.6, max(-0.6, pressure))
                ink_boost = min(2.5, max(0.25, ink_boost / (1.0 + press)))
            alpha_factor = rnd.uniform(options.ink_alpha_min, options.ink_alpha_max)
            if ink_boost != 1.0 or alpha_factor < 1.0:
                r, g, b, a = img.split()
                if ink_boost != 1.0:
                    boost_lut = [min(255, int(((v / 255.0) ** ink_boost) * 255)) for v in range(256)]
                    a = a.point(boost_lut)
                if alpha_factor < 1.0:
                    a = a.point(lambda v: int(v * alpha_factor))
                img = Image.merge("RGBA", (r, g, b, a))
            # R15 — TINTA EN ESPACIO DE TRAZO. RNG PROPIO sembrado del
            # contenido (patrón del edge_rng de abajo, otra sal): el master
            # on/off no corre el stream de variación del layout. El ANCHO
            # a lo largo va ANTES del borde R12 (el borde re-decora la
            # silueta nueva); el shading de densidad/color va DESPUÉS
            # (pinta el RGB final, que el borde deja plano).
            stroke_on = bool(getattr(options, "ink_stroke_space", False))
            stroke_rng = None
            if stroke_on:
                _sh = img.getchannel("A").histogram()
                _sv2 = (img.width * 40503 + img.height * 65537 + 0x51ED2701)
                for _i, _v in enumerate(_sh):
                    _sv2 = (_sv2 * 1000003 + _v * (_i + 7)) & 0xFFFFFFFFFFFF
                stroke_rng = random.Random(_sv2)
                from core.inkcore.renderer_ink import stroke_width_along
                _fs15 = max(1.0, float(getattr(options, "font_size", 40)))
                img = stroke_width_along(img, stroke_rng, options, _fs15)
            # R12 — RECONSTRUCCIÓN DE BORDE: último paso sobre el alpha INDIVIDUAL
            # del glifo (aquí todavía no se ha compuesto en la línea). Reescribe
            # el contorno binario por uno orgánico + feather variable. Se aplica
            # DESPUÉS de ink_boost (sobrescribe el borde duro que este endurece).
            # No cambia tamaño ni baseline → métricas/espaciado intactos.
            if getattr(options, "edge_reconstruct", False):
                from core.inkcore.renderer_edge import reconstruct_glyph_edge
                fs = max(1.0, float(getattr(options, "font_size", 40)))
                # RNG PROPIO del borde, sembrado del contenido del glifo (su
                # histograma de alpha ya warpeado) — NO consume del rnd compartido
                # del layout. Crítico: si tirara del rnd del render, correría el
                # stream y cambiaría el kerning/jitter de los glifos siguientes
                # (tocaría la VARIACIÓN). Así la realización de variación queda
                # byte-idéntica con el borde on/off, y el borde igual es único por
                # instancia (el histograma varía tras el warp).
                _hist = img.getchannel("A").histogram()
                _es = img.width * 2654435761 + img.height
                for _i, _v in enumerate(_hist):
                    _es = (_es * 1000003 + _v * (_i + 1)) & 0xFFFFFFFFFFFF
                edge_rng = random.Random(_es)
                # Amplitud en px anclada a font_size (el helper la acota a
                # 0.28·dim_menor del glifo → protege trazos finos y puntuación).
                img = reconstruct_glyph_edge(
                    img, edge_rng,
                    strength_px=getattr(options, "edge_strength", 0.028) * fs,
                    cell_px=max(3.0, getattr(options, "edge_cell_frac", 0.47) * fs),
                    feather_px=getattr(options, "edge_feather", 0.025) * fs,
                    feather_amount=getattr(options, "edge_feather_amount", 0.55),
                    outward_bias=getattr(options, "edge_outward_bias", 0.3),
                    # R15: con el master on, el ancho del feather lo modula
                    # un campo de FIBRA (celdas 3× alargadas): el sangrado
                    # es direccional, no un blur redondo. 1.0 = R12 exacto.
                    feather_fiber_aspect=3.0 if stroke_on else 1.0,
                )
            if stroke_on:
                from core.inkcore.renderer_ink import stroke_space_shading
                img = stroke_space_shading(img, stroke_rng, options, _fs15)
            # R14 (Track B) — micro-skip de bolígrafo, DESPUÉS del borde (el
            # dropout debe quedar nítido, no re-feathereado). RNG PROPIO
            # sembrado del contenido, patrón del edge_rng de arriba: ni el
            # sorteo del skip ni sus draws corren el stream compartido → la
            # realización de variación es byte-idéntica con el flag on/off.
            # R17b — bolitas de tinta en los extremos (pen-down/pen-up), sobre
            # el borde ya reconstruido (el charco debe quedar nítido). RNG
            # PROPIO sembrado del contenido (patrón del edge_rng): no corre el
            # stream compartido → byte-idéntico con el flag on/off.
            blob_s = min(0.6, max(0.0, getattr(options, "ink_blob_strength", 0.0)))
            if blob_s > 0:
                _hist = img.getchannel("A").histogram()
                _bs = (img.width * 40009 + img.height * 15485863 + 0x2545F491)
                for _i, _v in enumerate(_hist):
                    _bs = (_bs * 1000003 + _v * (_i + 5)) & 0xFFFFFFFFFFFF
                blob_rng = random.Random(_bs)
                from core.inkcore.renderer_ink import apply_ink_blobs
                fs_b = max(1.0, float(getattr(options, "font_size", 40)))
                img = apply_ink_blobs(img, blob_rng, font_size=fs_b,
                                      strength=blob_s)
            skip_p = min(0.05, max(0.0, getattr(options, "pen_skip_prob", 0.0)))
            if skip_p > 0:
                _hist = img.getchannel("A").histogram()
                _ss = (img.width * 2246822519 + img.height * 3266489917
                       + 0x9E3779B9)
                for _i, _v in enumerate(_hist):
                    _ss = (_ss * 1000003 + _v * (_i + 3)) & 0xFFFFFFFFFFFF
                skip_rng = random.Random(_ss)
                if skip_rng.random() < skip_p:
                    from core.inkcore.renderer_ink import apply_pen_skips
                    fs_skip = max(1.0, float(getattr(options, "font_size", 40)))
                    img = apply_pen_skips(img, skip_rng, font_size=fs_skip)
            return img, round(baseline_in) if baseline_in >= 0 else -1
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

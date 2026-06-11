import logging
import random
from dataclasses import replace

from core.inkcore.renderer_backgrounds import (
    BACKGROUND_STYLES,
    STYLE_PRESETS,
    BackgroundMixin,
)
from core.inkcore.renderer_glyph import GlyphLoadMixin
from core.inkcore.renderer_layout import LayoutMixin, _BlockLine
from core.inkcore.renderer_options import (
    PAPER_SIZES_MM,
    RENDER_DPI,
    RenderOptions,
    mm_to_px,
)

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
    "PAPER_SIZES_MM",
    "RENDER_DPI",
    "STYLE_PRESETS",
    "HandwritingRenderer",
    "RenderOptions",
    "mm_to_px",
]

# Escalado de fuente por nivel de encabezado (h1 más grande que el cuerpo).
# Niveles >3 caen al valor por defecto: apenas mayores que un párrafo.
_HEADING_SCALE: dict[int, float] = {1: 1.5, 2: 1.3, 3: 1.15}
_HEADING_SCALE_DEFAULT = 1.1


class HandwritingRenderer(BackgroundMixin, GlyphLoadMixin, LayoutMixin):

    def __init__(self, bank):
        self.bank = bank
        self._raw_cache: dict[str, Image.Image] = {}  # path -> RGBA image raw
        # Estado de selección de variantes, por-render (lo fija _begin_render).
        self._sel_history: dict | None = None
        self._sel_rng = None
        # Fase 6.5 — estado de realismo por-render:
        self._cur_line_slant = 0.0        # inclinación base del renglón en curso
        self._last_line_slants: list[float] = []  # para verificar el gate
        self._missing_chars: set[str] = set()     # chars sin glifo en el banco
        # R2 — geometría por glifo y conteos del render:
        self._geo_overlay: dict[str, dict] = {}   # estimaciones en vivo (legacy)
        self._geo_attempted: set[str] = set()
        self._advance_cache: dict[str, float] = {}  # fracción de em por char
        self._case_downgraded: set[str] = set()   # 'A' renderizada con glifo 'a'
        self._glyphs_placed = 0                   # glifos pegados (anti-pérdida)
        # R3 — RNG inyectado (I6) y procesos correlacionados por render:
        self._rng = random.Random()
        self._line_slant_walk = None              # OU del slant entre renglones
        self._margin_walk = None                  # OU del margen izquierdo
        self._line_jitter_walk = None             # OU del jitter vertical de línea
        self._line_index = 0                      # para el drift hacia adentro
        self._pair_chars: set[str] = set()        # R10: ligaduras del banco

    def last_missing_chars(self) -> set[str]:
        """Caracteres del último render que NO tenían glifo en el banco (Fase 6.5).

        La UI los muestra para que el usuario sepa qué capturar. Se vacía al
        empezar cada render."""
        return set(getattr(self, "_missing_chars", set()))

    def last_case_downgraded(self) -> set[str]:
        """Mayúsculas del último render servidas con el glifo de su minúscula
        (no había glifo exacto en el banco). R2: el lookup exacto va primero;
        este set delata qué mayúsculas conviene capturar."""
        return set(getattr(self, "_case_downgraded", set()))

    def coverage_report(self, text: str) -> dict:
        """Cobertura del banco para `text` SIN renderizar (R0, R-BUG-06 parte 1).

        Permite a la UI avisar ANTES de exportar qué caracteres caerían en el
        fallback. R2: el criterio es char EXACTO; una mayúscula que sólo existe
        como minúscula no es "missing" pero sí "case_downgraded" (se renderiza
        con la minúscula y conviene capturarla). Los espacios no cuentan.
        """
        missing: set[str] = set()
        covered: set[str] = set()
        downgraded: set[str] = set()
        for ch in set(text):
            if ch.isspace():
                continue
            if self.bank.get_all(ch):
                covered.add(ch)
            elif ch.lower() != ch and self.bank.get_all(ch.lower()):
                covered.add(ch)
                downgraded.add(ch)
            else:
                missing.add(ch)
        total = len(missing) + len(covered)
        return {
            "missing": sorted(missing),
            "covered": sorted(covered),
            "case_downgraded": sorted(downgraded),
            "coverage": round(len(covered) / total, 4) if total else 1.0,
        }

    def _begin_render(self, options: RenderOptions) -> None:
        """Reinicia el estado por-render: selección de variantes, RNG y walks.

        R3 (I6/C8): TODO el azar del render sale de self._rng, un
        random.Random propio — seed=N reproduce el documento byte a byte sin
        tocar el estado global del proceso (el hilo de extracción y la UI
        comparten el random global; antes el seed los pisaba).
        """
        self._sel_history = {}
        seed = getattr(options, "seed", None)
        self._rng = random.Random(seed)  # seed=None → aleatorio de verdad
        self._sel_rng = self._rng
        self._last_line_slants = []
        self._missing_chars = set()
        self._case_downgraded = set()
        self._glyphs_placed = 0
        # El banco pudo crecer entre renders (extracción concurrente): los
        # anchos cacheados del wrap se recalculan por render.
        self._advance_cache = {}
        # R3 — procesos correlacionados nuevos por render:
        from core.inkcore.renderer_noise import OUProcess
        self._line_slant_walk = None      # lo crea _render_line con su amplitud
        self._line_index = 0
        jp = max(0, options.jitter_px)
        self._line_jitter_walk = (
            OUProcess(self._rng, sigma=jp * 0.5, rho=0.55, bound=jp) if jp else None
        )
        walk_amp = max(0.0, getattr(options, "margin_walk_px", 6.0))
        self._margin_walk = (
            OUProcess(self._rng, sigma=2.0, rho=0.8, bound=walk_amp) if walk_amp else None
        )

    def _next_line_y_jitter(self) -> int:
        """Jitter vertical del PRÓXIMO renglón: OU, no ruido blanco (E5).

        El interlineado respira de forma correlacionada alrededor del renglón
        físico; con jitter_px=0 es exacto (anclaje a la hoja impresa intacto).
        """
        return round(self._line_jitter_walk.step()) if self._line_jitter_walk else 0

    def _next_margin_offset(self, options) -> int:
        """Offset X del PRÓXIMO renglón (E2): random walk acotado + drift lento
        hacia adentro proporcional al índice de línea — el margen de una mano
        no es láser y tiende a meterse conforme baja la página."""
        self._line_index += 1
        walk = self._margin_walk.step() if self._margin_walk else 0.0
        per_line = max(0.0, getattr(options, "margin_drift_per_line", 0.2))
        drift_in = min(10.0, per_line * self._line_index)
        return round(walk + drift_in)

    def _scaled_options(self, options: RenderOptions, ss: int) -> RenderOptions:
        """Opciones ×ss para el supersampling (R6/I1): lo anclado a mm escala
        vía render_dpi; los px ABSOLUTOS se multiplican explícitamente."""
        return replace(
            options,
            render_dpi=options.render_dpi * ss,
            font_size=options.font_size * ss,
            page_width=options.page_width * ss,
            page_margin=options.page_margin * ss,
            jitter_px=options.jitter_px * ss,
            baseline_drift=options.baseline_drift * ss,
            margin_walk_px=options.margin_walk_px * ss,
            margin_drift_per_line=options.margin_drift_per_line * ss,
            ink_bleed=options.ink_bleed * ss,
            supersample=1,
        )

    @staticmethod
    def _downscale(img, ss: int):
        return img.resize((max(1, img.width // ss), max(1, img.height // ss)),
                          Image.LANCZOS)

    def _compose_page(self, ink, options, spacing, page_height):
        """Pase de papel (R6/I2 + R7/F1/F3): sustrato texturizado + decoraciones,
        la tinta encima con multiply, y el skew de escaneo al cerrar. El skew
        corre AQUÍ (resolución supersampleada) para que el downscale LANCZOS
        pula el remuestreo de la rotación."""
        from core.inkcore.renderer_ink import apply_paper
        from core.inkcore.renderer_paper import apply_scan_skew, make_paper
        profile_dir = getattr(self.bank, "bank_dir", None)
        paper = make_paper(ink.size, options, self._rng, profile_dir)
        self._draw_background_decorations(paper, options, spacing, page_height)
        page = apply_paper(ink, paper, options, self._rng)
        return apply_scan_skew(page, options, self._rng)

    def apply_style(self, options: RenderOptions) -> RenderOptions:
        preset = STYLE_PRESETS.get(options.style, {})
        for k, v in preset.items():
            setattr(options, k, v)
        return options

    def render_transparent(self, text: str, options: RenderOptions) -> "Image.Image | None":
        """Como render_text pero sobre fondo TRANSPARENTE (RGBA), sin decoraciones.

        Pensado para compositar un bloque en una posición arbitraria: sólo la
        tinta queda, el resto es transparente, así no tapa lo de abajo.
        No aplica fondo/renglones (sería opaco); sí respeta wrap y la variación.
        """
        if not PIL_OK:
            return None
        options = self.apply_style(options)
        ss = max(1, int(getattr(options, "supersample", 1)))
        if ss > 1:
            big = self._scaled_options(options, ss)
            out = self.render_transparent(text, big)
            return self._downscale(out, ss) if out is not None else None
        self._begin_render(options)
        usable_width = max(1, options.page_width - 2 * options.page_margin)
        line_height_px = int(options.font_size * options.line_height)
        wrapped = self._soft_wrap_text(text, options, usable_width)
        rendered = [self._render_line(line, options, usable_width) for line in wrapped]
        total_h = max(line_height_px, options.page_margin * 2 + len(rendered) * line_height_px)
        canvas = Image.new("RGBA", (options.page_width, total_h), (0, 0, 0, 0))
        y_cursor = options.page_margin
        for line_img in rendered:
            if line_img:
                paste_y = max(0, y_cursor + self._next_line_y_jitter())
                if paste_y + line_img.height <= total_h:
                    x = options.page_margin + self._next_margin_offset(options)
                    canvas.paste(line_img, (x, paste_y), line_img)
            y_cursor += line_height_px
        return canvas

    def render_text(self, text: str, options: RenderOptions) -> "Image.Image | None":
        """Renderiza texto completo. Usa render_pages internamente para textos largos."""
        if not PIL_OK:
            return None
        options = self.apply_style(options)
        ss = max(1, int(getattr(options, "supersample", 1)))
        if ss > 1:
            out = self.render_text(text, self._scaled_options(options, ss))
            return self._downscale(out, ss) if out is not None else None
        self._begin_render(options)
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

        usable_width = options.usable_width_px
        spacing = options.line_spacing_px

        # BUG-06: word-wrap antes de renderizar, igual que render_pages. Sin
        # esto se perdía texto en líneas más anchas que usable_width.
        wrapped_lines = self._soft_wrap_text(text, options, usable_width)
        rendered_lines = [self._render_line(line, options, usable_width) for line in wrapped_lines]

        total_h = options.margin_top_px + options.margin_bottom_px + round(len(rendered_lines) * spacing)
        # Mínimo de cortesía ESCALADO por DPI: con supersampling (R6) el render
        # corre a render_dpi×ss; un mínimo fijo de 400 dejaba la página final
        # en 400/ss px tras el downscale.
        total_h = max(total_h, round(400 * options.render_dpi / RENDER_DPI))
        # R6 (I2): la tinta se compone en su propia capa transparente y el
        # papel se aplica al final (multiply) — ver _compose_page.
        ink = Image.new("RGBA", (options.page_width, total_h), (0, 0, 0, 0))

        # Cursor flotante con redondeo por renglón: el paso físico (mm) no es
        # entero en px y truncarlo desfasaría las líneas hacia el final.
        for i, line_img in enumerate(rendered_lines):
            y_cursor = options.margin_top_px + round(i * spacing)
            if line_img:
                # R3: jitter vertical correlacionado (E5) y margen con deriva (E2)
                paste_y = max(0, y_cursor + self._next_line_y_jitter())
                x = options.margin_left_px + self._next_margin_offset(options)
                if paste_y + line_img.height <= total_h:
                    ink.paste(line_img, (x, paste_y), line_img)
                else:
                    ink.paste(line_img, (x, max(0, total_h - line_img.height)), line_img)

        return self._compose_page(ink, options, spacing, total_h)

    def render_pages(
        self, text: str, options: RenderOptions, page_height: "int | None" = None
    ) -> list:
        """Renderiza texto dividido en páginas de papel físico (carta por default).

        page_height=None usa la altura del papel de options (carta a 150 DPI =
        1650 px). El avance vertical por renglón es EXACTAMENTE
        options.line_height_px (line_spacing_mm en px): la línea base del
        renglón k cae en margin_top + k·line_spacing, alineada a los renglones
        preimpresos de la hoja. Retorna lista de imágenes RGB.
        """
        if not PIL_OK:
            return []
        options = self.apply_style(options)
        ss = max(1, int(getattr(options, "supersample", 1)))
        if ss > 1:
            big = self._scaled_options(options, ss)
            big_h = None if page_height is None else page_height * ss
            return [self._downscale(p, ss)
                    for p in self.render_pages(text, big, big_h)]
        self._begin_render(options)
        options = self._apply_background_style(options)
        if page_height is None:
            page_height = options.page_height_px
        usable_width = options.usable_width_px
        # BUG-06: wrap antes de renderizar para que párrafos largos no se trunquen
        lines = self._soft_wrap_text(text, options, usable_width)
        line_height_px = options.line_height_px

        # SNAP A LIBRETA también para texto plano: si el fondo tiene renglones
        # horizontales, delega en el flujo con snap (mismo que render_document) para
        # que cada renglón caiga sobre una raya. Sin renglones se mantiene el camino
        # clásico de abajo (sin cambios de comportamiento donde no aplica).
        style_def = BACKGROUND_STYLES.get(options.background_style, {})
        if options.draw_lines and not style_def.get("draw_grid"):
            boff = self._line_baseline_offset(options.font_size)
            items = [
                _BlockLine(
                    img=self._render_line(line, options, usable_width),
                    x=options.margin_left_px,
                    line_height=line_height_px,
                    gap_before=0,
                    baseline_offset=boff,
                )
                for line in lines
            ]
            return self._flow_blocklines_to_pages(items, options, page_height, line_height_px)

        # Renderizar todas las líneas de texto
        rendered_lines = [self._render_line(line, options, usable_width) for line in lines]

        # Calcular cuántos renglones físicos caben por página (paso flotante:
        # con el paso redondeado se acumularía desfase al final de la hoja).
        spacing = options.line_spacing_px
        usable_height = page_height - options.margin_top_px - options.margin_bottom_px
        lines_per_page = max(1, int(usable_height // spacing))

        # Anclaje por LÍNEA BASE: la base del renglón k (1-indexado) cae en
        # margin_top + round(k·spacing), sin importar el font_size. El lienzo
        # de cada renglón se pega restando su baseline_offset; así el avance
        # físico es exacto y no se va desfasando de los renglones de la hoja.
        boff = self._line_baseline_offset(options.font_size)

        pages = []
        for page_start in range(0, len(rendered_lines), lines_per_page):
            page_lines = rendered_lines[page_start:page_start + lines_per_page]
            # R6 (I2): capa de tinta transparente; el papel se aplica al final.
            ink = Image.new("RGBA", (options.page_width, page_height), (0, 0, 0, 0))

            for k, line_img in enumerate(page_lines, start=1):
                if line_img:
                    # R3: jitter correlacionado (E5) + margen con deriva (E2);
                    # con jitter_px=0 el anclaje al renglón físico es exacto.
                    y_cursor = options.margin_top_px + round(k * spacing) - boff
                    paste_y = max(0, min(page_height - line_img.height,
                                         y_cursor + self._next_line_y_jitter()))
                    x = options.margin_left_px + self._next_margin_offset(options)
                    if paste_y + line_img.height <= page_height:
                        ink.paste(line_img, (x, paste_y), line_img)

            pages.append(self._compose_page(ink, options, spacing, page_height))

        return pages if pages else [Image.new("RGB", (options.page_width, page_height), "#FFFFFF")]

    def iter_pages(self, text: str, options: RenderOptions, page_height: "int | None" = None):
        """Generador de páginas PEREZOSO: produce y entrega una página a la vez.

        Para 36+ páginas, materializar la lista entera (render_pages) acumula en RAM
        tanto las imágenes de renglón como las de página. Acá se trocea el texto por
        cantidad de renglones que entran en una página y se renderiza CADA trozo por
        separado reutilizando render_pages — así sólo viven en memoria los renglones
        y la página del trozo en curso. El consumidor (exportador PDF) escribe y
        libera cada página antes de pedir la siguiente → pico de RAM plano.

        Reutiliza render_pages para NO duplicar la lógica de snap a libreta ni la
        paginación (regla: no reescribir lo que funciona). La memoria de variantes y
        el snap se reinician por página, lo cual es natural en un salto de página.
        """
        if not PIL_OK:
            return
        # apply_style por adelantado para medir el wrap con las opciones finales.
        probe = self.apply_style(options)
        if page_height is None:
            page_height = probe.page_height_px
        usable_width = probe.usable_width_px
        lines = self._soft_wrap_text(text, probe, usable_width)
        usable_height = page_height - probe.margin_top_px - probe.margin_bottom_px
        lines_per_page = max(1, int(usable_height // probe.line_spacing_px))
        if not lines:
            yield Image.new("RGB", (probe.page_width, page_height), probe.background_color)
            return
        for i in range(0, len(lines), lines_per_page):
            chunk = "\n".join(lines[i:i + lines_per_page])
            yield from self.render_pages(chunk, options, page_height)

    def render_document(self, doc, options: RenderOptions, page_height: "int | None" = None) -> list:
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
        ss = max(1, int(getattr(options, "supersample", 1)))
        if ss > 1:
            big = self._scaled_options(options, ss)
            big_h = None if page_height is None else page_height * ss
            return [self._downscale(p, ss)
                    for p in self.render_document(doc, big, big_h)]
        self._begin_render(options)
        options = self._apply_background_style(options)
        if page_height is None:
            page_height = options.page_height_px

        blocks = [b for page in getattr(doc, "pages", []) for b in page.blocks]
        if not blocks:
            text = doc.plain_text() if hasattr(doc, "plain_text") else str(doc)
            return self.render_pages(text, options, page_height)

        base_font = options.font_size
        usable_width = options.usable_width_px
        # Paso de grilla = el renglón FÍSICO de la hoja (mm), no font_size: el
        # cuerpo avanza un renglón real por línea y los encabezados reservan
        # los renglones que ocupan vía el span del flujo.
        base_line_h = options.line_height_px

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
            # Cuerpo: avance = un renglón físico. Encabezados (letra mayor):
            # avance proporcional a su font_size; el snap reserva los renglones
            # de grilla que cubren, así no se enciman con la línea siguiente.
            line_h = base_line_h if fs == base_font else int(fs * options.line_height)
            boff = self._line_baseline_offset(fs)
            block_usable = max(1, usable_width - indent)
            # Offset POR BLOQUE (no por letra), acotado: natural pero no caótico.
            bjx = self._rng.randint(-4, 4)
            bjy = self._rng.randint(-3, 3)

            wrapped = self._soft_wrap_text(prefix + text, bopts, block_usable)
            for i, ln in enumerate(wrapped):
                img = self._render_line(ln, bopts, block_usable)
                # Micro-rotación de renglón (±0.5°): expand=False conserva el tamaño
                # para no descuadrar el offset ni encimar renglones vecinos.
                if img is not None:
                    angle = self._rng.uniform(-0.5, 0.5)
                    img = img.rotate(angle, expand=False, resample=Image.BICUBIC)
                items.append(_BlockLine(
                    img=img,
                    x=options.margin_left_px + indent + bjx
                      + self._next_margin_offset(options),
                    line_height=line_h,
                    # el hueco de bloque + el jitter Y sólo en el primer renglón
                    gap_before=(gap_extra + bjy) if i == 0 else 0,
                    baseline_offset=boff,
                ))

        return self._flow_blocklines_to_pages(items, options, page_height, base_line_h)

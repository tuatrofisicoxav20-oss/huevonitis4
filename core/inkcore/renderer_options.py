"""Opciones y geometría física del render (extraído de renderer.py en R2).

RenderOptions ancla todo el layout a MILÍMETROS de papel real (carta) y los
convierte a px al DPI canónico. Vive aparte para mantener renderer.py bajo
~420 líneas; renderer.py re-exporta estos nombres para no romper imports
(`from core.inkcore.renderer import RenderOptions` sigue funcionando).
"""
from dataclasses import dataclass

# DPI canónico del render. Todo el layout se ancla a MILÍMETROS y se convierte
# a píxeles con este DPI, así el PDF impreso a tamaño real coincide con el
# papel físico (el usuario imprime sobre hoja de carpeta con renglones reales).
RENDER_DPI = 150

# Tamaños de papel en mm (ancho, alto). "letter" = carta US, el papel de
# carpeta común en México. A4 queda disponible como opción futura.
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "letter": (215.9, 279.4),
    "a4": (210.0, 297.0),
}


def mm_to_px(mm: float, dpi: int = RENDER_DPI) -> int:
    """Convierte milímetros a píxeles al DPI de render."""
    return round(mm / 25.4 * dpi)


@dataclass
class RenderOptions:
    # font_size = alto del EM/RENGLÓN en px al DPI de render (R2). Cada glifo
    # se escala por su fracción natural nat_h/em — NUNCA se normaliza la letra
    # al font_size (eso era R-BUG-01: la 'i' tan alta como la 'l'). 0 (default)
    # = derivarlo de line_spacing_mm para que la letra llene el renglón físico.
    # Un valor explícito se respeta (encabezados, tests), pero entonces el
    # texto puede descuadrarse de los renglones reales.
    font_size: int = 0
    jitter_px: int = 3
    size_variation: float = 0.12
    letter_spacing: float = 1.1
    line_height: float = 1.6
    rotation_range: float = 4.0
    # Variación de "presión": el alpha de cada glifo se multiplica por un factor
    # al azar en [min, max]. Floor más alto que antes (0.80) para que ninguna
    # letra salga desteñida, manteniendo variación entre letras como un bolígrafo.
    ink_alpha_min: float = 0.86
    ink_alpha_max: float = 1.0
    # ink_boost: gamma (<1) sobre el alpha de cada glifo. Sube los píxeles de
    # borde (semi-transparentes por el anti-aliasing) hacia opaco, así el trazo
    # se ve SÓLIDO y oscuro como tinta de bolígrafo y no fino/gris como lápiz.
    # 1.0 = sin efecto.
    ink_boost: float = 0.7
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
    # Fase 6.5 — inclinación BASE por renglón (macro): además del jitter por glifo,
    # cada línea recibe un ángulo base al azar en ±line_slant_deg, coherente dentro
    # de la línea. La mano no mantiene el mismo ángulo línea a línea. 0 = apagado.
    line_slant_deg: float = 1.4
    # Color de tinta. Los glifos del extractor son blancos (forma en alpha) para
    # verse sobre la UI oscura; sin recolorear serían INVISIBLES sobre el papel
    # claro. Un azul-negro de bolígrafo se ve más natural que el negro puro.
    ink_color: str = "#1A1A2E"
    # Semilla opcional para reproducir un render idéntico (debug / regenerar).
    # None = aleatorio cada vez.
    seed: "int | None" = None
    style: str = "Limpio"
    mode: str = "PNG"
    # page_width en px. 0 (default) = derivarlo del papel al DPI de render
    # (carta a 150 DPI = 1275 px). Un valor explícito se respeta (diagramas
    # con coordenadas en px, tests legacy).
    page_width: int = 0
    # page_margin queda como campo LEGACY: lo usan rutas no ancladas a papel
    # (render_transparent). El layout de páginas usa los márgenes físicos en mm.
    page_margin: int = 80
    background_color: str = "#FAFAFA"
    line_color: str = "#C8D8E8"
    draw_lines: bool = False
    # Estilo de fondo: "" | "hoja_blanca" | "libreta" | "hoja_cuadricula"
    background_style: str = ""
    # ── Geometría FÍSICA (mm) ─────────────────────────────────────────────
    # El render se ancla a una hoja real: papel carta y separación de
    # renglones configurable para igualar la hoja de carpeta del usuario
    # (≈7-8 mm según la marca). El margen superior deja espacio al encabezado
    # de la hoja (nombre/fecha).
    paper: str = "letter"
    render_dpi: int = RENDER_DPI
    line_spacing_mm: float = 7.5
    margin_top_mm: float = 25.0
    margin_left_mm: float = 20.0
    margin_right_mm: float = 12.0
    margin_bottom_mm: float = 15.0

    def __post_init__(self):
        if self.page_width <= 0:
            self.page_width = self.paper_size_px[0]
        if self.font_size <= 0:
            # R2: font_size = el renglón físico completo (em). Antes se
            # despejaba de una x-height objetivo; ahora la x-height resulta de
            # la fracción natural nat_h/em de los glifos del banco.
            self.font_size = max(1, round(self.line_spacing_px))

    @property
    def paper_size_px(self) -> tuple[int, int]:
        w_mm, h_mm = PAPER_SIZES_MM.get(self.paper, PAPER_SIZES_MM["letter"])
        return mm_to_px(w_mm, self.render_dpi), mm_to_px(h_mm, self.render_dpi)

    @property
    def page_height_px(self) -> int:
        return self.paper_size_px[1]

    @property
    def line_height_px(self) -> int:
        """Avance vertical por renglón redondeado a px (para spans/estimaciones)."""
        return max(1, mm_to_px(self.line_spacing_mm, self.render_dpi))

    @property
    def line_spacing_px(self) -> float:
        """Paso del renglón en px SIN redondear. Las posiciones de grilla se
        calculan como round(k * line_spacing_px): redondear el paso (44.29→44 a
        150 DPI) acumularía ~1.5 mm de desfase al final de la página, y el
        texto se saldría de los renglones físicos de la hoja."""
        return max(1.0, self.line_spacing_mm / 25.4 * self.render_dpi)

    @property
    def margin_top_px(self) -> int:
        return mm_to_px(self.margin_top_mm, self.render_dpi)

    @property
    def margin_left_px(self) -> int:
        return mm_to_px(self.margin_left_mm, self.render_dpi)

    @property
    def margin_right_px(self) -> int:
        return mm_to_px(self.margin_right_mm, self.render_dpi)

    @property
    def margin_bottom_px(self) -> int:
        return mm_to_px(self.margin_bottom_mm, self.render_dpi)

    @property
    def usable_width_px(self) -> int:
        return max(1, self.page_width - self.margin_left_px - self.margin_right_px)



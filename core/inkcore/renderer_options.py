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
    # DEPRECADO (R5/C7): el fade de alpha POR LETRA era el tell #5 — letras
    # enteras más claras al azar no pasan en tinta real. Defaults en 1.0 (sin
    # efecto); la variación de tinta vive DENTRO del trazo desde R6. Los
    # campos quedan por compat con presets/params guardados.
    ink_alpha_min: float = 1.0
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
    # R3/R5: 3.0 px (~0.5 mm a 150 DPI) — con menos, la señal del vaivén queda
    # debajo del ruido de forma y el baseline parece regla (tell #9).
    baseline_drift: float = 3.0
    kerning_jitter: float = 0.5
    slant_deg: float = 0.0
    # Fase 6.5/R3 — inclinación BASE por renglón (macro): cada línea hereda el
    # ángulo de la anterior y deriva (proceso OU acotado a ±line_slant_deg).
    # La mano no mantiene el mismo ángulo línea a línea, pero tampoco salta.
    # 0 = apagado.
    line_slant_deg: float = 1.4
    # R3 — espaciado humano:
    #   margin_walk_px: excursión máx (px) del random walk del margen izquierdo
    #     por renglón (E2) — el margen de una mano no es láser. 0 = apagado.
    #   margin_drift_per_line: px/línea de deriva LENTA hacia adentro conforme
    #     baja la página (acotada a 10 px), encima del walk.
    margin_walk_px: float = 6.0
    margin_drift_per_line: float = 0.2
    # R3/H8 — fallback de FUENTE DE SISTEMA: apagado por default. Un carácter
    # sin glifo se OMITE y se reporta (coverage_report / last_missing_chars);
    # la UI avisa antes de exportar. True = placeholder rojo (sólo preview).
    allow_font_fallback: bool = False
    # R4 — espaciado calibrable desde la página patrón del usuario (los σ
    # dejan de ser números mágicos; ver from_calibration):
    #   word_space_frac: espacio de palabra medio como fracción de font_size.
    #   word_space_cv:   su coeficiente de variación (E1).
    #   letter_gap_frac: hueco base entre letras como fracción de font_size.
    word_space_frac: float = 0.4
    word_space_cv: float = 0.18
    letter_gap_frac: float = 0.08
    # R5 — variación por instancia:
    #   warp_strength: amplitud del warp elástico por glifo (fracción del
    #     alto, malla 4×4 con BORDE anclado sobre el PNG de captura). 0.08
    #     rompe el hash perceptual de 16×16 incluso en una página llena de
    #     texto repetido, sin verse deformado a tamaño de lectura y sin mover
    #     el contorno (baseline/alturas estables).
    #   glyph_slant_drift_deg: amplitud de la deriva OU del slant por glifo
    #     a lo largo del renglón (C1), encima del slant global y de línea.
    warp_strength: float = 0.08
    glyph_slant_drift_deg: float = 1.0
    # R6 — pase de tinta:
    #   supersample: el render compone a N× y reduce LANCZOS al final (I1):
    #     bordes de rotación/shear limpios. Se aplica POR PÁGINA (memoria).
    #   ink_texture_strength: profundidad del value-noise que modula el alpha
    #     DENTRO del trazo (D2): alpha ∈ [1-strength, 1]. 0 = apagado.
    #   ink_bleed: σ (px finales) del blur del alpha antes de componer (D8) —
    #     sangrado sutil de tinta en papel.
    #   ink_hsv_jitter: (ΔS, ΔV) máximos del micro-color por glifo (D1).
    supersample: int = 2
    ink_texture_strength: float = 0.12
    ink_bleed: float = 0.4
    ink_hsv_jitter: tuple = (0.04, 0.03)
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



    @classmethod
    def from_calibration(cls, profile_dir, **overrides) -> "RenderOptions":
        """Opciones afinadas con la calibración del perfil (R4 — C2/H9).

        Lee ``{profile_dir}/calibration.json`` (lo escribe
        tools/calibrate_profile.py desde una página manuscrita REAL) y mapea
        sus estadísticas a las opciones de render. Los CLAMPS son deliberados:
        un mal escaneo (línea cortada, sombra) no debe producir un render
        loco; fuera de rango se recorta al borde plausible.

        Las medidas en px de la página real se normalizan por su altura media
        de letra (height_mu); en render se reconvierten con la aproximación
        altura_media ≈ 0.5·font_size (mezcla típica x-height/ascendentes).
        Sin calibration.json devuelve RenderOptions(**overrides) tal cual.
        """
        import json
        from pathlib import Path

        opts = cls(**overrides)
        path = Path(profile_dir) / "calibration.json"
        if not path.exists():
            return opts
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            m = data.get("metrics", {})
        except Exception:
            return opts

        def _clamp(v, lo, hi):
            return min(hi, max(lo, float(v)))

        # Conversión px-reales → px-render: las longitudes de la página se
        # normalizan por SU altura media de letra (height_mu) y se reconvierten
        # con la proporción empírica altura_media ≈ 0.40·font_size (texto
        # español: mezcla de x-height/ascendentes medida en el golden).
        h_mu = float(m.get("height_mu", 0.0))
        h_render = opts.font_size * 0.40
        if h_mu > 1:
            g_norm = float(m.get("word_gap_mu", 0.0)) / h_mu
            l_norm = float(m.get("letter_gap_mu", 0.0)) / h_mu
            if l_norm > 0:
                opts.letter_gap_frac = _clamp(l_norm * h_render / opts.font_size,
                                              0.02, 0.20)
            if g_norm > 0:
                # El gap MEDIDO es borde-a-borde: incluye el gap base entre
                # letras; el word_space del render se coloca ENCIMA de él.
                frac = (g_norm - max(0.0, l_norm)) * h_render / opts.font_size
                opts.word_space_frac = _clamp(frac, 0.20, 0.70)
                if m.get("word_gap_cv", 0) > 0:
                    # cv borde-a-borde → cv del word_space puro (la media
                    # medida es mayor que el word_space: σ igual, cv menor).
                    factor = g_norm / max(1e-6, g_norm - max(0.0, l_norm))
                    opts.word_space_cv = _clamp(m["word_gap_cv"] * factor,
                                                0.08, 0.35)
            if m.get("baseline_sigma", 0) > 0:
                px = (m["baseline_sigma"] / h_mu) * h_render
                opts.baseline_drift = _clamp(px, 1.0, 6.0)
            if m.get("left_margin_sigma", 0) > 0:
                px = (m["left_margin_sigma"] / h_mu) * h_render
                opts.margin_walk_px = _clamp(px, 2.0, 14.0)
        elif m.get("word_gap_cv", 0) > 0:
            opts.word_space_cv = _clamp(m["word_gap_cv"], 0.08, 0.35)
        if m.get("height_cv", 0) > 0:
            # Parte del CV de alturas es entre-clases (asc vs x), no variación
            # por instancia: sólo una fracción va a size_variation.
            opts.size_variation = _clamp(m["height_cv"] * 0.45, 0.04, 0.25)
        if "slant_mean" in m:
            opts.slant_deg = _clamp(m["slant_mean"], -8.0, 8.0)
        if m.get("slant_std", 0) > 0:
            opts.rotation_range = _clamp(m["slant_std"] * 0.5, 0.5, 5.0)
            opts.line_slant_deg = _clamp(m["slant_std"] * 0.4, 0.3, 3.0)
        return opts

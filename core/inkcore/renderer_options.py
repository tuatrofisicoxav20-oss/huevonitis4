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
    # R15: default 0.7 → 0.92. Forzar la opacidad al máximo UNIFORME era una
    # causa del look impreso (slab plano): con la densidad variable en espacio
    # de trazo, el gamma agresivo ya no hace falta y aplana la textura nueva.
    # Rollback exacto a R12/R14: ink_boost=0.7 + ink_stroke_space=False.
    ink_boost: float = 0.92
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
    # R14 (H5-C2) — el walk pasa a ser un OU REAL calibrado por sus perillas:
    #   margin_walk_rho: correlación lag-1 del proceso (memoria de la mano
    #     entre renglones). La σ por paso se DERIVA de amplitud y ρ
    #     (σ = 0.45·amp·√(1−ρ²)) para que la excursión estacionaria llene la
    #     amplitud a cualquier supersampling; antes la σ iba fija en 2 px y el
    #     margen quedaba en ±2 px finales — de regla (autocorr ≈ 0 medida).
    #     Aplica también al camino snap (fondos rayados), que pegaba x FIJO.
    margin_walk_px: float = 6.0
    margin_walk_rho: float = 0.9
    margin_drift_per_line: float = 0.2
    # R14 (H5-C2) — párrafo humano en el CAMINO PLANO de prosa (párrafo =
    # línea EN BLANCO en la entrada; jamás toca writer_structure/detección):
    #   para_indent_frac: sangría media de la primera línea de cada párrafo,
    #     como fracción de font_size. Cada sangría se sortea con gauss
    #     truncada (σ=0.35·μ, acotada a [0.45, 1.7]·μ): una mano no sangra
    #     dos veces igual. La primera línea del documento también sangra.
    #     0 = apagado (comportamiento previo). La línea sangrada puede apurar
    #     el margen derecho unos px (el wrap mide a ancho completo) — igual
    #     que una mano que no replanifica el renglón por la sangría.
    para_indent_frac: float = 0.85
    #   para_breath_px: respiración inter-párrafo — desplazamiento vertical
    #     acotado (gauss truncada, ±para_breath_px) de la PRIMERA línea de
    #     cada párrafo, NO acumulativo (el cuerpo regresa al renglón físico).
    #     Sólo en el camino clásico: con fondos rayados (snap) el texto se
    #     apoya en renglones REALES y la mano no flota entre rayas.
    #     0 = apagado.
    para_breath_px: float = 4.0
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
    # R10 (G3) — semi-cursiva básica: probabilidad de usar una LIGADURA del
    # banco ("qu", "ll", "de"…) cuando el par aparece en el texto. Una mano
    # liga unas veces sí y otras no; 0 = nunca (banco sin pares no se afecta).
    ligature_prob: float = 0.6
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
    ink_bleed: float = 0.5
    ink_hsv_jitter: tuple = (0.04, 0.03)
    # R11 — TEXTURA DE TINTA v2 (intra-trazo). Patch modular sobre apply_paper;
    # NO toca banco/extracción/variación/métricas. El value-noise de R6
    # (ink_texture_strength) modula por ZONA de página (cell ∝ font_size×1.2),
    # así que cada trazo salía de opacidad plana. v2 añade frecuencia FINA
    # (escala de trazo), bordes irregulares y apozamiento de tinta.
    #   ink_texture_v2: master switch. False = apply_paper corre EXACTO como en
    #     R6 (comparación antes/después y rollback con un solo flag).
    #   ink_texture_fine_strength: profundidad del value-noise de ALTA frecuencia
    #     que modula la OSCURIDAD del trazo a lo largo (densidad de depósito: el
    #     color, no el ancho — modular alpha sobre trazos finos solo los aclara).
    #   ink_texture_fine_cell_frac: celda del ruido fino como fracción de
    #     font_size (~0.15 → la tinta respira a lo largo del trazo, no por zona).
    #   ink_edge_irregularity: 0..1, modula el halo de sangrado con ruido para
    #     que el borde feathee desigual (0 = sangrado uniforme de R6).
    #   ink_pooling: 0..1, oscurece el COLOR de tinta donde el coverage local es
    #     alto (cruces, vueltas, trazo grueso) — apozamiento real de tinta.
    #   ink_width_jitter: 0..1, dilatación ligera modulada por ruido de baja
    #     frecuencia (engrosa/adelgaza el trazo a lo largo). 0 = apagado (riesgo
    #     de legibilidad; subir con cuidado).
    # NOTA R12: con la reconstrucción de borde (abajo) como protagonista del look
    # manuscrito, la textura INTERIOR se baja a un papel de apoyo (no es la causa
    # del look de impresión — el borde sí). No subir estos sin razón.
    ink_texture_v2: bool = True
    ink_texture_fine_strength: float = 0.20
    ink_texture_fine_cell_frac: float = 0.15
    ink_edge_irregularity: float = 0.72
    ink_pooling: float = 0.15
    ink_width_jitter: float = 0.0
    # R12 — RECONSTRUCCIÓN DE BORDE (textura por FRONTERA, no por interior). Es la
    # causa #1 del look de impresión: el alpha binarizado tiene un borde duro y
    # regular. Se aplica POR GLIFO en _load_glyph (alpha individual, a resolución
    # supersampleada) reconstruyendo el contorno con ruido 1D de baja frecuencia
    # a lo largo del perímetro + feather variable. NO cambia tamaño ni baseline.
    #   edge_reconstruct: master switch (False = sin paso de borde, vuelve a R11).
    #   edge_strength: amplitud del desplazamiento del perímetro como FRACCIÓN de
    #     font_size (el helper la acota a 0.28·dim_menor del glifo → protege
    #     trazos finos y puntuación de romperse).
    #   edge_cell_frac: longitud de onda del ruido 1D como fracción de font_size
    #     (↑ = ondas más largas/suaves; baja frecuencia = orgánico, no dentado).
    #   edge_feather: sigma máx del feather variable como fracción de font_size.
    #   edge_feather_amount: 0..1, cuánto del borde "corrido" (blur) se mezcla.
    #   edge_outward_bias: 0..1, cuánto del desplazamiento es hacia AFUERA (la
    #     tinta sangra al papel) vs. simétrico. Alto = engrosa el trazo y oscurece
    #     (pero un engrose CONSTANTE comprimiría el CV de alturas → toca
    #     proporciones); bajo ≈ media-preservante (solo ondula el borde). Default
    #     conservador para NO alterar las métricas de proporción del render.
    edge_reconstruct: bool = True
    edge_strength: float = 0.028
    edge_cell_frac: float = 0.47
    edge_feather: float = 0.025
    edge_feather_amount: float = 0.55
    edge_outward_bias: float = 0.3
    # R13 — margen derecho irregular: amplitud (fracción de font_size) del ancho
    # de corte por renglón. 0 = borde recto (wrap actual). ~0.5 = borde orgánico
    # sin salirse del margen físico derecho. Acótalo por debajo del margen físico
    # derecho para no invadir el borde de la hoja.
    wrap_margin_jitter: float = 0.0
    # R13 — jitter I.I.D. (px) del inicio de cada renglón: rompe la apariencia de
    # "regla" del margen izquierdo con variación independiente por línea (encima
    # del walk correlacionado). 0 = sin cambio. ~10 px (~1.7 mm) se ve natural.
    margin_line_jitter_px: float = 0.0
    # R14 (Track A) — ESTADO LATENTE DE LA MANO e(t). Tell que ataca: la
    # variación por glifo era casi toda i.i.d.; la escritura real varía LENTO
    # y CORRELACIONADO (la mano que viene cansada/rápida sigue así unas
    # líneas). Un único proceso OU por página (mismo estilo que line_slant)
    # avanza un paso por renglón y se interpola dentro del renglón; su valor
    # acopla a la vez tamaño, slant (línea y glifo COMPARTEN el latente),
    # presión→oscuridad y ritmo de espaciado de palabra. NUNCA toca el wrap
    # ni la geometría anclada a mm (solo modula procesos ya existentes).
    #   hand_energy_sigma: amplitud del latente en unidades adimensionales
    #     (0..1.5, clamp). 0 = apagado: CERO draws de RNG, byte-idéntico.
    #   hand_energy_corr_lines: longitud de correlación en RENGLONES (ρ =
    #     exp(-1/corr)); ~3 = el estado sobrevive unas 3 líneas.
    #   pressure_darkness_coupling: 0..0.4 — cuánto empuja e(t) el gamma del
    #     alpha (ink_boost efectivo): presión alta = trazo más oscuro y un
    #     pelo más ancho; mano liviana = más claro. Riesgo de legibilidad
    #     bajo (gamma acotado a [0.25, 2.5] en _load_glyph).
    #   line_end_cramp: 0..0.3 — compresión progresiva de gaps/espacios (y
    #     una pizca de tamaño) en el ÚLTIMO ~18% del renglón: una mano
    #     aprieta las letras cuando ve venir el margen. Riesgo: >0.3 pega
    #     letras al final del renglón (clamp duro).
    #   session_shift_prob: probabilidad por renglón de un SALTO del latente
    #     (pausa, re-carga de tinta): el estado brinca a un valor fresco en
    #     vez de derivar. 0..0.1 (clamp).
    # R17c — deriva de presión SUBIDA (juez: "tinta uniforme a lo largo de toda
    # la página = tóner de impresora"). Una pluma real carga/descarga: unas
    # zonas oscuras, otras pálidas. hand_energy_sigma 0.6→0.95 + coupling
    # 0.15→0.30 + session_shift 0.02→0.05 dan variación LENTA visible por
    # párrafo. Los goldens apagan hand_energy_sigma=0 (byte-idéntico).
    hand_energy_sigma: float = 0.95
    hand_energy_corr_lines: float = 3.0
    pressure_darkness_coupling: float = 0.30
    line_end_cramp: float = 0.12
    session_shift_prob: float = 0.05
    # R17 (Track A2) — jitter I.I.D. de presión POR GLIFO. El latente e(t) es
    # LENTO/correlacionado (misma energía ~3 renglones); pero la letra real
    # tiene además variación RÁPIDA e independiente: una letra sale pálida y la
    # siguiente oscura sin relación (micro-contacto de la punta, no cansancio de
    # muñeca). Se ve clarísimo en las plantillas del usuario (una 'l' pálida al
    # lado de una 'k' densa). Suma un término i.i.d. al `pressure` que va al
    # gamma del alpha en _load_glyph — presión alta = trazo más oscuro/grueso.
    # Gauss truncada a ±2.2σ. 0 = apagado: CERO draws de RNG (byte-idéntico).
    # Riesgo de legibilidad acotado: el gamma efectivo queda en [0.25, 2.5].
    glyph_pressure_jitter: float = 0.26
    # R14 (Track B) — física de bolígrafo. Defaults en 0 (opt-in, subir con
    # cuidado): son los efectos con más riesgo de legibilidad del R14.
    #   pen_skip_prob: probabilidad POR GLIFO (0..0.05, clamp) de un
    #     micro-skip: una bolita sin tinta sobre la cresta del trazo (el
    #     bolígrafo patina). Protegido por tamaño (imita a edge_reconstruct):
    #     nunca corre en puntuación diminuta ni en trazos con semiancho
    #     < ~1.6 px — un skip ahí CORTA el trazo en vez de despintarlo.
    #     RNG propio sembrado del contenido (patrón del borde R12): el flag
    #     on/off no corre el stream de variación del layout.
    #   connector_prob: probabilidad (0..0.7, clamp) de unir dos glifos
    #     CONTIGUOS de la misma palabra con un trazo fino de entrada/salida
    #     sobre la línea base (extiende la semi-cursiva de las ligaduras
    #     R10 a pares que no están capturados como par). Sólo une si los
    #     puntos de anclaje existen y el hueco es chico (2 px..0.4·em);
    #     riesgo de legibilidad bajo (el conector va con alpha parcial).
    #   connector_width_frac: grosor del conector como fracción de
    #     font_size (~0.04 = trazo de salida fino, más fino que el cuerpo).
    # R15: el skip pasa a ON por default (0.01): ya corre sobre la cresta del
    # distance transform con tamaño ∝ ancho local (lo que pide R15) y sus
    # clamps de legibilidad están medidos (Δ OCR ≈ 0 con 0.03 en r14_eval).
    pen_skip_prob: float = 0.03
    # R17b — bolitas de tinta en los EXTREMOS del trazo (pen-down/pen-up):
    # el charco redondeado que deja la punta del bolígrafo al apoyarse. 0..0.6
    # (clamp). Detecta extremos por esqueleto y SUMA alpha (nunca corta el
    # trazo). RNG propio sembrado del contenido → byte-idéntico con 0.
    ink_blob_strength: float = 0.30
    connector_prob: float = 0.0
    connector_width_frac: float = 0.04
    # R15 — TINTA EN ESPACIO DE TRAZO. Tell que ataca: el look "impreso" del
    # relleno — densidad uniforme, ancho constante y textura ISOTRÓPICA en
    # espacio de pantalla (los campos 2D de R11 modulan un blob plano). La
    # tinta de pluma varía A LO LARGO del trazo y su textura fina es
    # ANISOTRÓPICA (riel alineado a la dirección). El campo de orientación
    # sale del gradiente del distanceTransform del alpha (sin skeleton
    # externo); las coordenadas de trazo (a lo largo / cruzando) muestrean
    # ruido con longitudes de onda distintas por eje. Corre POR GLIFO en
    # _load_glyph con RNG propio sembrado del contenido (patrón del borde
    # R12): on/off no corre el stream de variación del layout.
    #   ink_stroke_space: master. False = pipeline R12/R14 EXACTO (con
    #     ink_boost=0.7 y pen_skip_prob=0, byte-idéntico; rollback total).
    #   ink_along_darkness: 0..0.4 — shading de DENSIDAD a lo largo (modula
    #     el color, no el ancho): la pluma deposita más en unos tramos.
    #   ink_width_along: 0..0.25 — thick/thin a lo largo (thin en trazos
    #     rápidos, grueso en lentos), SIMÉTRICO al centro. Clamp fuerte por
    #     dt: cero erosión donde el semiancho local < ~2.2 px (no rompe
    #     finos ni puntuación). Se aplica ANTES del borde R12 (el borde
    #     re-decora la silueta nueva).
    #   ink_streak_strength: 0..0.4 — textura "riel": fino CRUZANDO el
    #     trazo, lento A LO LARGO, orientada por la tangente.
    #   ink_streak_aniso: 1..8 — relación largo/cruce del riel (4 ≈ fibras
    #     de depósito de bolígrafo).
    #   ink_pool_boost: 0..0.4 — oscurece donde dt es alto (cruces, vueltas,
    #     núcleo grueso); complementa el ink_pooling 2D de R11 pero en
    #     espacio de trazo. (Las "puntas" quedan cubiertas parcialmente por
    #     el dt bajo de los extremos; el modelado explícito de endpoints se
    #     evaluó y se dejó fuera: requiere skeleton.)
    #   ink_hue_by_density: 0..0.3 — donde denso el color vira al azul de
    #     carga (más saturado); donde tenue, a gris (desaturado): la tinta
    #     rala pierde cuerpo de color antes que luminancia.
    #   ink_paper_showthrough: 0..0.2 — cuánto grano de papel se ve BAJO la
    #     tinta (cap del alpha efectivo en apply_paper): la tinta real nunca
    #     es 100% opaca sobre fibra.
    ink_stroke_space: bool = True
    # R17 — defaults de tinta subidos (jurado adversarial: "trazo de ancho
    # uniforme, sin física de bolígrafo, sin pooling ni skips"). Todos siguen
    # en su rango clampeado y sólo tocan RGB/textura-de-alpha, no la geometría;
    # el costo de legibilidad medido es ≈0 (OCR 82→81.5%). Rollback R15: los
    # valores previos eran 0.18/0.10/0.15/0.15/0.10.
    ink_along_darkness: float = 0.38
    ink_width_along: float = 0.16
    ink_streak_strength: float = 0.28
    ink_streak_aniso: float = 4.0
    ink_pool_boost: float = 0.34
    ink_hue_by_density: float = 0.12
    ink_paper_showthrough: float = 0.11
    # R7 — pase de papel:
    #   paper_texture: nombre de PNG en tipografia/{perfil}/papers/ (scans del
    #     usuario) o assets/papers/ (procedurales). None = papel liso. Los
    #     BACKGROUND_STYLES traen su textura; esto permite forzar otra.
    #   scan_skew: rotación global sub-grado (±1.2°) de la página final con
    #     esquinas del color del papel — nadie alinea la hoja perfecto (F3).
    paper_texture: "str | None" = None
    scan_skew: bool = False
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

"""Decoraciones de fondo (libreta, cuadrícula, margen) y presets de estilo.

Se separa de renderer.py para mantener cada módulo bajo ~420 líneas. El
HandwritingRenderer hereda de BackgroundMixin. Los dicts BACKGROUND_STYLES y
STYLE_PRESETS se re-exportan desde renderer.py para no romper imports previos.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

    from core.inkcore.renderer import RenderOptions

try:
    from PIL import ImageDraw
    PIL_OK = True
except ImportError:
    PIL_OK = False


# R7 (F1): cada estilo trae su textura de papel (PNG en assets/papers/,
# generadas proceduralmente por tools/gen_paper_textures.py; el usuario puede
# meter scans propios en tipografia/{perfil}/papers/ con el mismo nombre y
# tienen prioridad). texture=None ⇒ papel liso (color sólido, cero costo).
BACKGROUND_STYLES: dict[str, dict] = {
    "hoja_blanca": {
        "bg": "#FFFFFF",
        "draw_lines": False,
        "margin_color": None,
        "texture": "papel_fibra.png",
    },
    # Para IMPRESIÓN: blanco PURO sin textura de papel. La textura de fibra se
    # ve "realista" en pantalla pero al imprimir sale como un tinte/patrón gris
    # sobre el papel real (efecto fotocopia). Sin textura, la impresora deja el
    # fondo en blanco y SOLO deposita la tinta → natural sobre el papel físico.
    "blanco_liso": {
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
        "texture": "papel_crema.png",
    },
    "hoja_cuadricula": {
        "bg": "#F0F4FF",
        "draw_lines": True,
        "line_color": "#C5D5F0",
        "draw_grid": True,
        "grid_size": 28,
        "texture": "papel_fibra.png",
    },
}


# R3 (I7): rotation_range ya NO es ruido blanco por letra sino la AMPLITUD del
# proceso OU de rotación a lo largo del renglón — la misma sensación visual
# necesita amplitudes menores que el ruido blanco de antes.
# R7 (I7): "Escolar"/"Examen" anclan a libreta (E10: el texto se APOYA en los
# renglones impresos); "Limpio" es hoja blanca sin skew de escaneo.
STYLE_PRESETS: dict[str, dict] = {
    "Limpio": {"jitter_px": 2, "size_variation": 0.08, "rotation_range": 1.2,
               "background_style": "hoja_blanca", "scan_skew": False},
    "Escolar": {"jitter_px": 4, "size_variation": 0.14, "rotation_range": 2.8,
                "draw_lines": True, "background_style": "libreta"},
    "Universitario": {"jitter_px": 2, "size_variation": 0.10, "rotation_range": 1.6},
    "Relajado": {"jitter_px": 6, "size_variation": 0.20, "rotation_range": 4.0},
    "Examen": {"jitter_px": 3, "size_variation": 0.10, "rotation_range": 1.8,
               "draw_lines": True, "background_style": "libreta"},
    # Bolígrafo (R7/P2): trazo de tinta azul-negra sólido como una pluma de
    # bolígrafo real, con variación de carga de tinta a lo largo del texto
    # (ink_texture) y micro-variación de color por glifo (ink_hsv_jitter). El
    # ink_boost más agresivo (gamma menor) empuja el antialiasing a opaco para
    # que el trazo no se vea gris/lápiz tras el downscale del supersampling.
    "Bolígrafo": {"jitter_px": 3, "size_variation": 0.17, "rotation_range": 3.2,
                  "background_style": "blanco_liso", "scan_skew": False,
                  "baseline_drift": 4.0, "kerning_jitter": 0.55,
                  "warp_strength": 0.18, "glyph_slant_drift_deg": 2.2,
                  "ink_color": "#0B1A52", "ink_boost": 0.15,
                  "ink_texture_strength": 0.10, "ink_bleed": 1.8,
                  "ink_hsv_jitter": (0.04, 0.05)},
}


class BackgroundMixin:
    """Aplica el estilo de fondo a las opciones y dibuja sus decoraciones."""

    def _apply_background_style(self, options) -> RenderOptions:
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
        # R7 (F1): el estilo trae su textura de papel; solo si el caller no
        # forzó una propia (paper_texture explícito gana al estilo).
        if options.paper_texture is None and "texture" in style_def:
            options.paper_texture = style_def["texture"]
        return options

    def _draw_background_decorations(
        self,
        canvas: Image.Image,
        options,
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
            x = options.margin_left_px
            while x < options.page_width - options.margin_right_px:
                draw.line([(x, 0), (x, canvas_h)], fill=line_col, width=1)
                x += grid_size
            y = options.margin_top_px
            while y < canvas_h - options.margin_bottom_px:
                draw.line([(0, y), (options.page_width, y)], fill=line_col, width=1)
                y += grid_size
        elif options.draw_lines:
            # Líneas horizontales en los RENGLONES FÍSICOS de la hoja: la línea
            # base del renglón k cae en margin_top + round(k*paso) (así pega el
            # renderer, tanto la ruta clásica como el snap del flujo; el paso
            # puede ser FLOTANTE — mm a px — y se redondea por renglón para no
            # acumular desfase). Las rayas se dibujan en esas MISMAS y, así las
            # letras se apoyan en ellas y el preview coincide con la hoja real.
            k = 1
            while True:
                y = options.margin_top_px + round(k * line_height_px)
                if y >= canvas_h - options.margin_bottom_px:
                    break
                draw.line(
                    [(options.margin_left_px, y), (options.page_width - options.margin_right_px, y)],
                    fill=options.line_color, width=1,
                )
                k += 1

        # Línea de margen roja (solo libreta)
        if style_def.get("margin_color"):
            margin_x = style_def.get("margin_x", 80)
            draw.line([(margin_x, 0), (margin_x, canvas_h)],
                      fill=style_def["margin_color"], width=2)

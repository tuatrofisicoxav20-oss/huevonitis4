"""Design system "Caos Orbital" (U2).

Identidad: espacio profundo (azules casi negros) + UN acento primario ámbar
y cian como secundario informativo. Verde/rojo quedan SOLO semánticos
(éxito/peligro). Cero arcoíris por sección: todas las vistas usan ámbar.

Todos los nombres públicos pre-U2 se conservan como alias para no tocar 45
archivos de golpe:

  • ACCENT_BLUE   → alias del ámbar primario (acciones primarias)
  • ACCENT_ORANGE → alias del ámbar primario
  • ACCENT_CYAN   → secundario informativo (nuevo nombre canónico)
  • ACCENT_GREEN / ACCENT_RED → semánticos (éxito / peligro)

apply_theme() intercambia los globals del módulo entre _DARK y _LIGHT; los
acentos también se intercambian (el ámbar claro #C77800 mantiene contraste AA
sobre fondos crema). Tokens de espaciado/radios/duración: SPACE, RADIUS, DUR.
"""

# ── Palettes ─────────────────────────────────────────────────────────────────
# Each palette is a dict of the mutable colour tokens.
# apply_theme() swaps module-level globals to the chosen palette.

_DARK: dict = {
    # Orbital: espacio profundo, jerarquía por elevación
    "BG_PRIMARY":   "#06070B",
    "BG_SECONDARY": "#0D1117",
    "BG_TERTIARY":  "#141A26",
    "CARD_BG":       "#10151F",
    "CARD_BG_HOVER": "#18202E",
    "GRADIENT_START": "#101725",
    "GRADIENT_END":   "#06070B",
    "SHADOW":          "#030409",
    "CARD_BORDER":        "#222B3A",
    "BADGE_BG_GREEN":  "#0E3A20",
    "BADGE_BG_ORANGE": "#3A2604",
    "BADGE_BG_BLUE":   "#0E3340",
    "BADGE_BG_RED":    "#450A0A",
    "BADGE_BG_PURPLE": "#2E1065",
    "TEXT_PRIMARY":   "#F0F6FC",
    "TEXT_SECONDARY": "#94A3B8",
    "TEXT_MUTED":     "#4B5563",
    "BORDER":        "#222B3A",
    "BORDER_LIGHT":  "#2E3A4E",
    # Acento primario ámbar + secundario cian (Orbital)
    "ACCENT_PRIMARY":       "#FFAE42",
    "ACCENT_PRIMARY_HOVER": "#FF9D1F",
    "ACCENT_PRIMARY_SOFT":  "#FFC97A",
    # Texto sobre ámbar (el ámbar es claro: texto oscuro para AA)
    "ACCENT_TEXT_ON":       "#241500",
    # Fondo tintado del acento (fila activa del sidebar, hovers suaves)
    "ACCENT_BG":            "#2A1C04",
    "ACCENT_CYAN":        "#4FE3FF",
    "ACCENT_CYAN_HOVER":  "#22D3EE",
    "ACCENT_CYAN_BG":     "#0A2A33",
    "TIER_BG": {
        "Bronze": "#241606",
        "Silver": "#1A212C",
        "Gold":   "#241B02",
    },
}

_LIGHT: dict = {
    # Crema-fríos derivados de los mismos tokens (no paleta paralela)
    "BG_PRIMARY":   "#F6F6F2",
    "BG_SECONDARY": "#ECECE6",
    "BG_TERTIARY":  "#DFE0D8",
    "CARD_BG":       "#F1F1EB",
    "CARD_BG_HOVER": "#E6E6DE",
    "GRADIENT_START": "#E8E8E0",
    "GRADIENT_END":   "#F6F6F2",
    "SHADOW":          "#B9BCB3",
    "CARD_BORDER":        "#CDCFC4",
    "BADGE_BG_GREEN":  "#DCFCE7",
    "BADGE_BG_ORANGE": "#FBEFD4",
    "BADGE_BG_BLUE":   "#D7F2FA",
    "BADGE_BG_RED":    "#FEE2E2",
    "BADGE_BG_PURPLE": "#EDE9FE",
    "TEXT_PRIMARY":   "#15130C",
    "TEXT_SECONDARY": "#4A4A40",
    "TEXT_MUTED":     "#8C8C80",
    "BORDER":        "#CDCFC4",
    "BORDER_LIGHT":  "#DBDCD2",
    # Ámbar oscurecido para contraste AA sobre crema
    "ACCENT_PRIMARY":       "#C77800",
    "ACCENT_PRIMARY_HOVER": "#A86400",
    "ACCENT_PRIMARY_SOFT":  "#E09A2E",
    "ACCENT_TEXT_ON":       "#FFFFFF",
    "ACCENT_BG":            "#F2E2C4",
    "ACCENT_CYAN":        "#0E7490",
    "ACCENT_CYAN_HOVER":  "#155E75",
    "ACCENT_CYAN_BG":     "#D7F2FA",
    "TIER_BG": {
        "Bronze": "#F5EBDD",
        "Silver": "#EDEFF2",
        "Gold":   "#F8F0D8",
    },
}

# ── Backgrounds ─────────────────────────────────────────────────────────────
BG_PRIMARY   = _DARK["BG_PRIMARY"]
BG_SECONDARY = _DARK["BG_SECONDARY"]
BG_TERTIARY  = _DARK["BG_TERTIARY"]

CARD_BG       = _DARK["CARD_BG"]
CARD_BG_HOVER = _DARK["CARD_BG_HOVER"]

GRADIENT_START = _DARK["GRADIENT_START"]
GRADIENT_END   = _DARK["GRADIENT_END"]

# ── Accent colours ───────────────────────────────────────────────────────────
# Primario ámbar — ACCENT_BLUE/ACCENT_ORANGE son ALIAS históricos del primario
# (45 archivos los usan como "acción primaria"); el nombre canónico nuevo es
# ACCENT_PRIMARY. El cian es el secundario informativo (links/info/estados).
ACCENT_PRIMARY       = _DARK["ACCENT_PRIMARY"]
ACCENT_PRIMARY_HOVER = _DARK["ACCENT_PRIMARY_HOVER"]
ACCENT_PRIMARY_SOFT  = _DARK["ACCENT_PRIMARY_SOFT"]
ACCENT_TEXT_ON       = _DARK["ACCENT_TEXT_ON"]
ACCENT_BG            = _DARK["ACCENT_BG"]

ACCENT_CYAN       = _DARK["ACCENT_CYAN"]
ACCENT_CYAN_HOVER = _DARK["ACCENT_CYAN_HOVER"]
ACCENT_CYAN_BG    = _DARK["ACCENT_CYAN_BG"]

ACCENT_BLUE        = ACCENT_PRIMARY
ACCENT_BLUE_HOVER  = ACCENT_PRIMARY_HOVER
ACCENT_BLUE_LIGHT  = ACCENT_PRIMARY_SOFT

ACCENT_ORANGE       = ACCENT_PRIMARY
ACCENT_ORANGE_HOVER = ACCENT_PRIMARY_HOVER
ACCENT_ORANGE_LIGHT = ACCENT_PRIMARY_SOFT

# Semánticos: SOLO éxito / peligro / advertencia
ACCENT_GREEN        = "#22C55E"
ACCENT_GREEN_HOVER  = "#16A34A"
ACCENT_GREEN_LIGHT  = "#4ADE80"
ACCENT_GREEN_MUTED  = "#14532D"

ACCENT_RED        = "#EF4444"
ACCENT_RED_HOVER  = "#DC2626"

ACCENT_YELLOW        = "#EAB308"
ACCENT_YELLOW_HOVER  = "#CA8A04"

ACCENT_PURPLE        = "#8B5CF6"
ACCENT_PURPLE_HOVER  = "#7C3AED"

# ── Shadow / glow hints ──────────────────────────────────────────────────────
SHADOW = _DARK["SHADOW"]

# ── Card decoration ──────────────────────────────────────────────────────────
CARD_BORDER        = _DARK["CARD_BORDER"]
CARD_BORDER_ACTIVE = _DARK["ACCENT_PRIMARY"]

BADGE_BG_GREEN  = _DARK["BADGE_BG_GREEN"]
BADGE_BG_ORANGE = _DARK["BADGE_BG_ORANGE"]
BADGE_BG_BLUE   = _DARK["BADGE_BG_BLUE"]
BADGE_BG_RED    = _DARK["BADGE_BG_RED"]
BADGE_BG_PURPLE = _DARK["BADGE_BG_PURPLE"]

# ── Text ─────────────────────────────────────────────────────────────────────
TEXT_PRIMARY   = _DARK["TEXT_PRIMARY"]
TEXT_SECONDARY = _DARK["TEXT_SECONDARY"]
TEXT_MUTED     = _DARK["TEXT_MUTED"]

# ── Borders ──────────────────────────────────────────────────────────────────
BORDER        = _DARK["BORDER"]
BORDER_LIGHT  = _DARK["BORDER_LIGHT"]
BORDER_ACTIVE = _DARK["ACCENT_PRIMARY"]

# ── Layout tokens (U2) ───────────────────────────────────────────────────────
# Espaciado, radios y duraciones canónicos — adiós números mágicos.
SPACE  = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}
RADIUS = {"s": 4, "m": 8, "l": 12, "xl": 16}
DUR    = {"fast": 120, "base": 180, "slow": 250}  # ms — techo 250 (regla dura)

# ── Status / tier colours ─────────────────────────────────────────────────────
STATUS_COLORS = {
    "Borrador":    "#6B7280",
    "Cotizado":    "#4FE3FF",
    "Aceptado":    "#8B5CF6",
    "En Progreso": "#FFAE42",
    "Revisión":    "#EAB308",
    "Entregado":   "#22C55E",
    "Pagado":      "#15803D",
    "Cancelado":   "#EF4444",
}

TIER_COLORS = {
    "Bronze": "#CD7F32",
    "Silver": "#C0C0C0",
    "Gold":   "#FFD700",
}

TIER_BG = dict(_DARK["TIER_BG"])

# ── Content tokens ───────────────────────────────────────────────────────────
# Colores que representan CONTENIDO (papel del canvas, marcas externas,
# bloques de documento) — no cambian con el tema porque modelan el material,
# no el chrome de la UI.
CANVAS_PAPER_OUTLINE       = "#888888"
CANVAS_MARGIN              = "#E8E8E8"
CANVAS_ELEMENT_BG          = "#FFFFFF"
CANVAS_ELEMENT_SELECTED_BG = "#EEF4FF"
CANVAS_ELEMENT_OUTLINE     = "#AAAAAA"
CANVAS_IMAGE_FILL          = "#CCCCCC"
CANVAS_IMAGE_OUTLINE       = "#999999"
# Fondo del thumb de glifo (tinta clara sobre negro, en ambos temas)
GLYPH_PREVIEW_BG = "#000000"

BRAND_WHATSAPP       = "#25D366"
BRAND_WHATSAPP_HOVER = "#128C7E"

# Bloques de documento en Estudio: (color_texto, color_fondo) por tipo
DOC_BLOCK_COLORS = {
    "heading":   ("#d4a017", "#7a5500"),  # dorado
    "list_item": ("#2a7fbf", "#1a4a7a"),  # azul
    "code":      ("#3a8a4a", "#1a4a2a"),  # verde
    "caption":   ("#8a6a3a", "#5a3a10"),  # marrón
    "paragraph": ("#555555", "#2a2a2a"),  # gris neutro
    "unknown":   ("#444444", "#222222"),
}

# Badges por tipo de archivo en el import de Estudio
FILE_BADGE_COLORS = {
    "text_pdf": "#2d6a4f",
    "scan_pdf": "#7b4f00",
    "mixed_pdf": "#5a4a00",
    "docx": "#1a4a7a",
    "image": "#5a2a6a",
    "folder": "#1a5a6a",
}

# ── Typography ────────────────────────────────────────────────────────────────
# Sin "Segoe UI" (no existe en Fedora): familias reales de Linux primero.
_UI_FONT_CANDIDATES = ["Inter", "Cantarell", "DejaVu Sans", "Liberation Sans",
                       "Noto Sans", "Helvetica", "TkDefaultFont"]
_MONO_CANDIDATES = ["JetBrains Mono", "Maple Mono", "Fira Mono",
                    "DejaVu Sans Mono", "Liberation Mono", "TkFixedFont"]

UI_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"


def get_font(weight: str = "normal", size: int = 11) -> tuple:
    """Devuelve una tupla (family, size, weight) usando el mejor UI font disponible.

    weight: "normal" | "bold". UI_FONT debe resolverse con init_fonts() antes
    de cualquier llamada (típicamente después de crear el Tk root).
    """
    return (UI_FONT, size, "bold" if weight == "bold" else "normal")


def get_mono(size: int = 10) -> tuple:
    """Tupla de fuente monoespaciada (atajos, métricas, código)."""
    return (MONO_FONT, size)


def init_fonts() -> None:
    """Resolve UI_FONT and MONO_FONT to best available; call after Tk root exists."""
    global UI_FONT, MONO_FONT, FONT_TITLE, FONT_HEADING, FONT_SUBHEADING
    global FONT_BODY, FONT_SMALL, FONT_MONO, FONT_SIDEBAR
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
        for name in _UI_FONT_CANDIDATES:
            if name in available or name.startswith("Tk"):
                UI_FONT = name
                break
        for name in _MONO_CANDIDATES:
            if name in available or name.startswith("Tk"):
                MONO_FONT = name
                break
    except Exception:
        pass
    FONT_TITLE      = (UI_FONT, 22, "bold")
    FONT_HEADING    = (UI_FONT, 16, "bold")
    FONT_SUBHEADING = (UI_FONT, 13, "bold")
    FONT_BODY       = (UI_FONT, 11)
    FONT_SMALL      = (UI_FONT, 9)
    FONT_MONO       = (MONO_FONT, 10)
    FONT_SIDEBAR    = (UI_FONT, 12)


FONT_TITLE      = (UI_FONT, 22, "bold")
FONT_HEADING    = (UI_FONT, 16, "bold")
FONT_SUBHEADING = (UI_FONT, 13, "bold")
FONT_BODY       = (UI_FONT, 11)
FONT_SMALL      = (UI_FONT, 9)
FONT_MONO       = (MONO_FONT, 10)
FONT_SIDEBAR    = (UI_FONT, 12)

# ── Navigation items ──────────────────────────────────────────────────────────
# U3: el segundo campo es el NOMBRE DE ICONO de ui/icons.py (ya no emoji).
NAV_ITEMS = [
    ("dashboard", "home",      "Dashboard"),
    ("projects",  "folder",    "Proyectos"),
    ("study",     "book",      "Estudio"),
    ("inkcore",   "pen",       "Mi Letra"),
    ("business",  "briefcase", "Negocio"),
    ("settings",  "gear",      "Config"),
]

# U2: fin del arcoíris por sección — TODAS las vistas usan el ámbar primario.
# El dict se conserva (y se re-popula en apply_theme) porque sidebar/app lo
# consultan por view_id.
NAV_ACCENT = {vid: ACCENT_PRIMARY for vid, _i, _l in NAV_ITEMS}


# ── Theme switching ───────────────────────────────────────────────────────────

_SCALAR_KEYS = [
    "BG_PRIMARY", "BG_SECONDARY", "BG_TERTIARY",
    "CARD_BG", "CARD_BG_HOVER",
    "GRADIENT_START", "GRADIENT_END",
    "SHADOW", "CARD_BORDER",
    "BADGE_BG_GREEN", "BADGE_BG_ORANGE", "BADGE_BG_BLUE",
    "BADGE_BG_RED", "BADGE_BG_PURPLE",
    "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED",
    "BORDER", "BORDER_LIGHT",
    "ACCENT_PRIMARY", "ACCENT_PRIMARY_HOVER", "ACCENT_PRIMARY_SOFT",
    "ACCENT_TEXT_ON", "ACCENT_BG",
    "ACCENT_CYAN", "ACCENT_CYAN_HOVER", "ACCENT_CYAN_BG",
]


def apply_theme(mode: str) -> None:
    """Swap colour globals to the selected palette.

    Must be called BEFORE any UI widget is constructed.
    mode: "dark" | "light"
    """
    import sys
    _module = sys.modules[__name__]
    palette = _LIGHT if mode == "light" else _DARK
    for key in _SCALAR_KEYS:
        setattr(_module, key, palette[key])
    _module.TIER_BG = dict(palette["TIER_BG"])
    # Alias históricos + derivados del acento (siguen al primario del tema)
    _module.ACCENT_BLUE = palette["ACCENT_PRIMARY"]
    _module.ACCENT_BLUE_HOVER = palette["ACCENT_PRIMARY_HOVER"]
    _module.ACCENT_BLUE_LIGHT = palette["ACCENT_PRIMARY_SOFT"]
    _module.ACCENT_ORANGE = palette["ACCENT_PRIMARY"]
    _module.ACCENT_ORANGE_HOVER = palette["ACCENT_PRIMARY_HOVER"]
    _module.ACCENT_ORANGE_LIGHT = palette["ACCENT_PRIMARY_SOFT"]
    _module.CARD_BORDER_ACTIVE = palette["ACCENT_PRIMARY"]
    _module.BORDER_ACTIVE = palette["ACCENT_PRIMARY"]
    _module.NAV_ACCENT = {vid: palette["ACCENT_PRIMARY"] for vid, _i, _l in NAV_ITEMS}

# ── Palettes ─────────────────────────────────────────────────────────────────
# Each palette is a dict of the mutable colour tokens.
# apply_theme() swaps module-level globals to the chosen palette.

_DARK: dict = {
    "BG_PRIMARY":   "#0D1117",
    "BG_SECONDARY": "#111827",
    "BG_TERTIARY":  "#1E2A38",
    "CARD_BG":       "#162032",
    "CARD_BG_HOVER": "#1D2D45",
    "GRADIENT_START": "#1C2840",
    "GRADIENT_END":   "#0D1117",
    "SHADOW":          "#060A10",
    "CARD_BORDER":        "#2A3A50",
    "BADGE_BG_GREEN":  "#14532D",
    "BADGE_BG_ORANGE": "#431407",
    "BADGE_BG_BLUE":   "#1E3A5F",
    "BADGE_BG_RED":    "#450A0A",
    "BADGE_BG_PURPLE": "#2E1065",
    "TEXT_PRIMARY":   "#F0F6FC",
    "TEXT_SECONDARY": "#94A3B8",
    "TEXT_MUTED":     "#4B5563",
    "BORDER":        "#2A3A50",
    "BORDER_LIGHT":  "#3D4F66",
    "TIER_BG": {
        "Bronze": "#2A1A08",
        "Silver": "#1E2530",
        "Gold":   "#2D2000",
    },
}

_LIGHT: dict = {
    "BG_PRIMARY":   "#F5F7FA",
    "BG_SECONDARY": "#EAEEF4",
    "BG_TERTIARY":  "#D9E1ED",
    "CARD_BG":       "#EFF3FA",
    "CARD_BG_HOVER": "#E1E9F5",
    "GRADIENT_START": "#DDE6F2",
    "GRADIENT_END":   "#F5F7FA",
    "SHADOW":          "#B0BCC8",
    "CARD_BORDER":        "#C1CDD9",
    "BADGE_BG_GREEN":  "#DCFCE7",
    "BADGE_BG_ORANGE": "#FEF3C7",
    "BADGE_BG_BLUE":   "#DBEAFE",
    "BADGE_BG_RED":    "#FEE2E2",
    "BADGE_BG_PURPLE": "#EDE9FE",
    "TEXT_PRIMARY":   "#0D1117",
    "TEXT_SECONDARY": "#374151",
    "TEXT_MUTED":     "#9CA3AF",
    "BORDER":        "#C1CDD9",
    "BORDER_LIGHT":  "#D3DCE6",
    "TIER_BG": {
        "Bronze": "#FDF4E7",
        "Silver": "#F0F3F9",
        "Gold":   "#FFFBEB",
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
ACCENT_BLUE        = "#2563EB"
ACCENT_BLUE_HOVER  = "#1D4ED8"
ACCENT_BLUE_LIGHT  = "#3B82F6"

ACCENT_ORANGE       = "#F97316"
ACCENT_ORANGE_HOVER = "#EA6010"
ACCENT_ORANGE_LIGHT = "#FB923C"

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
CARD_BORDER_ACTIVE = "#2563EB"

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
BORDER_ACTIVE = "#2563EB"

# ── Status / tier colours ─────────────────────────────────────────────────────
STATUS_COLORS = {
    "Borrador":    "#6B7280",
    "Cotizado":    "#3B82F6",
    "Aceptado":    "#8B5CF6",
    "En Progreso": "#F97316",
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

# ── Typography ────────────────────────────────────────────────────────────────
_UI_FONT_CANDIDATES = ["Segoe UI", "Inter", "DejaVu Sans", "Liberation Sans",
                       "Helvetica", "TkDefaultFont"]
_MONO_CANDIDATES = ["Consolas", "Fira Mono", "DejaVu Sans Mono",
                    "Liberation Mono", "Courier New", "TkFixedFont"]

UI_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"


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
NAV_ITEMS = [
    ("dashboard", "🏠", "Dashboard"),
    ("projects",  "📁", "Proyectos"),
    ("study",     "📖", "Estudio"),
    ("inkcore",   "✍️", "Mi Letra"),
    ("business",  "💼", "Negocio"),
    ("settings",  "⚙️", "Config"),
]

NAV_ACCENT = {
    "dashboard": ACCENT_BLUE,
    "projects":  ACCENT_GREEN,
    "study":     ACCENT_PURPLE,
    "inkcore":   ACCENT_ORANGE,
    "business":  ACCENT_YELLOW,
    "settings":  "#64748B",
}


# ── Theme switching ───────────────────────────────────────────────────────────

def apply_theme(mode: str) -> None:
    """Swap colour globals to the selected palette.

    Must be called BEFORE any UI widget is constructed.
    mode: "dark" | "light"
    """
    import sys
    _module = sys.modules[__name__]
    palette = _LIGHT if mode == "light" else _DARK
    scalar_keys = [
        "BG_PRIMARY", "BG_SECONDARY", "BG_TERTIARY",
        "CARD_BG", "CARD_BG_HOVER",
        "GRADIENT_START", "GRADIENT_END",
        "SHADOW", "CARD_BORDER",
        "BADGE_BG_GREEN", "BADGE_BG_ORANGE", "BADGE_BG_BLUE",
        "BADGE_BG_RED", "BADGE_BG_PURPLE",
        "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED",
        "BORDER", "BORDER_LIGHT",
    ]
    for key in scalar_keys:
        setattr(_module, key, palette[key])
    _module.TIER_BG = dict(palette["TIER_BG"])

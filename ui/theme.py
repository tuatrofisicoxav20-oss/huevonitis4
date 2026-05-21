# ── Backgrounds ─────────────────────────────────────────────────────────────
BG_PRIMARY   = "#0D1117"
BG_SECONDARY = "#111827"   # slight blue-tint — not flat grey
BG_TERTIARY  = "#1E2A38"   # visible depth against secondary

CARD_BG       = "#162032"   # cards have their own blue-ink tint
CARD_BG_HOVER = "#1D2D45"

# Gradient hints (used where solid fallbacks are needed)
GRADIENT_START = "#1C2840"
GRADIENT_END   = "#0D1117"

# ── Accent colours ───────────────────────────────────────────────────────────
ACCENT_BLUE        = "#2563EB"
ACCENT_BLUE_HOVER  = "#1D4ED8"
ACCENT_BLUE_LIGHT  = "#3B82F6"

ACCENT_ORANGE       = "#F97316"
ACCENT_ORANGE_HOVER = "#EA6010"
ACCENT_ORANGE_LIGHT = "#FB923C"   # softer highlight / badge bg

ACCENT_GREEN        = "#22C55E"
ACCENT_GREEN_HOVER  = "#16A34A"
ACCENT_GREEN_LIGHT  = "#4ADE80"   # lighter for icons / badges
ACCENT_GREEN_MUTED  = "#14532D"   # dark bg behind green elements

ACCENT_RED        = "#EF4444"
ACCENT_RED_HOVER  = "#DC2626"

ACCENT_YELLOW        = "#EAB308"
ACCENT_YELLOW_HOVER  = "#CA8A04"

ACCENT_PURPLE        = "#8B5CF6"
ACCENT_PURPLE_HOVER  = "#7C3AED"

# ── Shadow / glow hints ──────────────────────────────────────────────────────
SHADOW = "#060A10"

# ── Card decoration ──────────────────────────────────────────────────────────
CARD_BORDER        = "#2A3A50"   # default card border (more visible than plain grey)
CARD_BORDER_ACTIVE = "#2563EB"   # highlighted / selected card  (alias kept for explicit API)

BADGE_BG_GREEN  = "#14532D"
BADGE_BG_ORANGE = "#431407"
BADGE_BG_BLUE   = "#1E3A5F"
BADGE_BG_RED    = "#450A0A"
BADGE_BG_PURPLE = "#2E1065"   # dark pill behind purple badge

# ── Text ─────────────────────────────────────────────────────────────────────
TEXT_PRIMARY   = "#F0F6FC"
TEXT_SECONDARY = "#94A3B8"   # slightly blue-tinted secondary
TEXT_MUTED     = "#4B5563"

# ── Borders ──────────────────────────────────────────────────────────────────
BORDER        = "#2A3A50"
BORDER_LIGHT  = "#3D4F66"
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

# Tier accent backgrounds (dark pill behind tier badge)
TIER_BG = {
    "Bronze": "#2A1A08",
    "Silver": "#1E2530",
    "Gold":   "#2D2000",
}

# ── Typography ────────────────────────────────────────────────────────────────
FONT_TITLE      = ("Segoe UI", 22, "bold")
FONT_HEADING    = ("Segoe UI", 16, "bold")
FONT_SUBHEADING = ("Segoe UI", 13, "bold")
FONT_BODY       = ("Segoe UI", 11)
FONT_SMALL      = ("Segoe UI", 9)
FONT_MONO       = ("Consolas", 10)
FONT_SIDEBAR    = ("Segoe UI", 12)   # slightly larger than before

# ── Navigation items ──────────────────────────────────────────────────────────
NAV_ITEMS = [
    ("dashboard", "🏠", "Dashboard"),
    ("projects",  "📁", "Proyectos"),
    ("study",     "📖", "Estudio"),
    ("inkcore",   "✍️", "Mi Letra"),
    ("business",  "💼", "Negocio"),
    ("settings",  "⚙️", "Config"),
]

# Colour associated with each nav section (used for active indicator + hover)
NAV_ACCENT = {
    "dashboard": ACCENT_BLUE,
    "projects":  ACCENT_GREEN,
    "study":     ACCENT_PURPLE,
    "inkcore":   ACCENT_ORANGE,
    "business":  ACCENT_YELLOW,
    "settings":  "#64748B",
}

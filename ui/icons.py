"""Sistema de iconos vectoriales propio (U3) — adiós emojis en controles.

Cada icono se dibuja con PIL.ImageDraw a 4× y se reduce con LANCZOS
(anti-alias), estilo outline ~2 px con esquinas suaves, monocromático y
recoloreable. get_icon() devuelve CTkImage cacheado por (name, size, color);
el color default sigue a theme.TEXT_SECONDARY en el momento de la llamada.

Uso:  ctk.CTkButton(..., image=icons.get_icon("save", 16), compound="left")
"""
from __future__ import annotations

import logging
import math

from ui import theme

logger = logging.getLogger(__name__)

try:
    import customtkinter as ctk
    from PIL import Image, ImageDraw
    _OK = True
except ImportError:  # pragma: no cover - PIL/ctk siempre presentes en la app
    _OK = False

_SS = 4  # supersampling
_cache: dict[tuple, object] = {}


def _stroke(size: int) -> int:
    """Grosor del trazo a escala 4× (≈2 px al tamaño final)."""
    return max(3, round(size * _SS * 0.115))


# ── Primitivas de dibujo (coordenadas normalizadas 0..1) ─────────────────────

def _pts(s: float, coords):
    return [(x * s, y * s) for x, y in coords]


def _line(d, s, w, color, coords):
    d.line(_pts(s, coords), fill=color, width=w, joint="curve")
    # Puntas redondeadas
    r = w / 2 - 0.5
    for x, y in (_pts(s, [coords[0], coords[-1]])):
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _circle(d, s, w, color, cx, cy, r):
    d.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s],
              outline=color, width=w)


def _rrect(d, s, w, color, x0, y0, x1, y1, rad=0.08):
    d.rounded_rectangle([x0 * s, y0 * s, x1 * s, y1 * s],
                        radius=rad * s, outline=color, width=w)


def _dot(d, s, color, cx, cy, r):
    d.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s],
              fill=color)


def _arc(d, s, w, color, x0, y0, x1, y1, start, end):
    d.arc([x0 * s, y0 * s, x1 * s, y1 * s], start, end, fill=color, width=w)


# ── Catálogo ─────────────────────────────────────────────────────────────────

def _i_home(d, s, w, c):
    _line(d, s, w, c, [(0.15, 0.52), (0.5, 0.18), (0.85, 0.52)])
    _line(d, s, w, c, [(0.24, 0.46), (0.24, 0.84), (0.76, 0.84), (0.76, 0.46)])


def _i_folder(d, s, w, c):
    _line(d, s, w, c, [(0.12, 0.78), (0.12, 0.26), (0.42, 0.26), (0.5, 0.36),
                       (0.88, 0.36), (0.88, 0.78), (0.12, 0.78)])


def _i_book(d, s, w, c):
    _line(d, s, w, c, [(0.5, 0.26), (0.42, 0.2), (0.14, 0.2), (0.14, 0.76),
                       (0.42, 0.76), (0.5, 0.82)])
    _line(d, s, w, c, [(0.5, 0.26), (0.58, 0.2), (0.86, 0.2), (0.86, 0.76),
                       (0.58, 0.76), (0.5, 0.82)])
    _line(d, s, w, c, [(0.5, 0.27), (0.5, 0.8)])


def _i_pen(d, s, w, c):
    # Plumilla: cuerpo diagonal + punta
    _line(d, s, w, c, [(0.7, 0.14), (0.86, 0.3), (0.34, 0.82), (0.14, 0.86),
                       (0.18, 0.66), (0.7, 0.14)])
    _line(d, s, w, c, [(0.6, 0.26), (0.74, 0.4)])


def _i_briefcase(d, s, w, c):
    _rrect(d, s, w, c, 0.12, 0.34, 0.88, 0.8, rad=0.06)
    _line(d, s, w, c, [(0.36, 0.34), (0.36, 0.22), (0.64, 0.22), (0.64, 0.34)])
    _line(d, s, w, c, [(0.12, 0.52), (0.88, 0.52)])


def _i_gear(d, s, w, c):
    _circle(d, s, w, c, 0.5, 0.5, 0.16)
    for k in range(8):
        a = math.tau * k / 8
        x0 = 0.5 + 0.26 * math.cos(a)
        y0 = 0.5 + 0.26 * math.sin(a)
        x1 = 0.5 + 0.38 * math.cos(a)
        y1 = 0.5 + 0.38 * math.sin(a)
        _line(d, s, w, c, [(x0, y0), (x1, y1)])


def _i_search(d, s, w, c):
    _circle(d, s, w, c, 0.44, 0.44, 0.24)
    _line(d, s, w, c, [(0.63, 0.63), (0.84, 0.84)])


def _i_plus(d, s, w, c):
    _line(d, s, w, c, [(0.5, 0.18), (0.5, 0.82)])
    _line(d, s, w, c, [(0.18, 0.5), (0.82, 0.5)])


def _i_trash(d, s, w, c):
    _line(d, s, w, c, [(0.16, 0.28), (0.84, 0.28)])
    _line(d, s, w, c, [(0.38, 0.28), (0.38, 0.18), (0.62, 0.18), (0.62, 0.28)])
    _line(d, s, w, c, [(0.24, 0.28), (0.28, 0.84), (0.72, 0.84), (0.76, 0.28)])
    _line(d, s, w, c, [(0.42, 0.4), (0.42, 0.7)])
    _line(d, s, w, c, [(0.58, 0.4), (0.58, 0.7)])


def _i_save(d, s, w, c):
    _rrect(d, s, w, c, 0.16, 0.16, 0.84, 0.84, rad=0.08)
    _line(d, s, w, c, [(0.32, 0.16), (0.32, 0.38), (0.68, 0.38), (0.68, 0.16)])
    _line(d, s, w, c, [(0.3, 0.6), (0.3, 0.84)])
    _line(d, s, w, c, [(0.7, 0.6), (0.7, 0.84)])


def _i_export(d, s, w, c):
    _line(d, s, w, c, [(0.5, 0.6), (0.5, 0.14)])
    _line(d, s, w, c, [(0.32, 0.3), (0.5, 0.13), (0.68, 0.3)])
    _line(d, s, w, c, [(0.16, 0.6), (0.16, 0.84), (0.84, 0.84), (0.84, 0.6)])


def _i_image(d, s, w, c):
    _rrect(d, s, w, c, 0.14, 0.18, 0.86, 0.82, rad=0.08)
    _dot(d, s, c, 0.36, 0.38, 0.05)
    _line(d, s, w, c, [(0.2, 0.72), (0.44, 0.5), (0.6, 0.64), (0.72, 0.54),
                       (0.82, 0.62)])


def _i_refresh(d, s, w, c):
    _arc(d, s, w, c, 0.18, 0.18, 0.82, 0.82, -45, 200)
    _line(d, s, w, c, [(0.86, 0.22), (0.86, 0.44), (0.64, 0.44)])


def _i_check(d, s, w, c):
    _line(d, s, w, c, [(0.18, 0.54), (0.42, 0.78), (0.84, 0.26)])


def _i_x(d, s, w, c):
    _line(d, s, w, c, [(0.24, 0.24), (0.76, 0.76)])
    _line(d, s, w, c, [(0.76, 0.24), (0.24, 0.76)])


def _i_warning(d, s, w, c):
    _line(d, s, w, c, [(0.5, 0.14), (0.88, 0.82), (0.12, 0.82), (0.5, 0.14)])
    _line(d, s, w, c, [(0.5, 0.42), (0.5, 0.6)])
    _dot(d, s, c, 0.5, 0.72, 0.035)


def _i_info(d, s, w, c):
    _circle(d, s, w, c, 0.5, 0.5, 0.36)
    _dot(d, s, c, 0.5, 0.34, 0.04)
    _line(d, s, w, c, [(0.5, 0.46), (0.5, 0.68)])


def _i_chevron_l(d, s, w, c):
    _line(d, s, w, c, [(0.62, 0.2), (0.34, 0.5), (0.62, 0.8)])


def _i_chevron_r(d, s, w, c):
    _line(d, s, w, c, [(0.38, 0.2), (0.66, 0.5), (0.38, 0.8)])


def _i_chevron_d(d, s, w, c):
    _line(d, s, w, c, [(0.2, 0.38), (0.5, 0.66), (0.8, 0.38)])


def _i_chevron_u(d, s, w, c):
    _line(d, s, w, c, [(0.2, 0.62), (0.5, 0.34), (0.8, 0.62)])


def _i_layers(d, s, w, c):
    _line(d, s, w, c, [(0.5, 0.14), (0.86, 0.34), (0.5, 0.54), (0.14, 0.34),
                       (0.5, 0.14)])
    _line(d, s, w, c, [(0.14, 0.54), (0.5, 0.74), (0.86, 0.54)])
    _line(d, s, w, c, [(0.14, 0.68), (0.5, 0.88), (0.86, 0.68)])


def _i_grid(d, s, w, c):
    for x0, y0 in ((0.14, 0.14), (0.54, 0.14), (0.14, 0.54), (0.54, 0.54)):
        _rrect(d, s, w, c, x0, y0, x0 + 0.32, y0 + 0.32, rad=0.05)


def _i_eye(d, s, w, c):
    _arc(d, s, w, c, 0.1, 0.18, 0.9, 0.82, 20, 160)
    _arc(d, s, w, c, 0.1, 0.18, 0.9, 0.82, 200, 340)
    _circle(d, s, w, c, 0.5, 0.5, 0.11)


def _i_play(d, s, w, c):
    _line(d, s, w, c, [(0.32, 0.18), (0.78, 0.5), (0.32, 0.82), (0.32, 0.18)])


def _i_palette(d, s, w, c):
    _arc(d, s, w, c, 0.12, 0.12, 0.88, 0.88, 60, 330)
    _line(d, s, w, c, [(0.72, 0.72), (0.56, 0.6), (0.66, 0.5)])
    _dot(d, s, c, 0.34, 0.36, 0.05)
    _dot(d, s, c, 0.52, 0.28, 0.05)
    _dot(d, s, c, 0.68, 0.36, 0.05)


def _i_undo(d, s, w, c):
    _arc(d, s, w, c, 0.2, 0.24, 0.84, 0.84, 90, 320)
    _line(d, s, w, c, [(0.16, 0.34), (0.22, 0.56), (0.44, 0.5)])


def _i_doc(d, s, w, c):
    _line(d, s, w, c, [(0.22, 0.86), (0.22, 0.14), (0.62, 0.14), (0.78, 0.3),
                       (0.78, 0.86), (0.22, 0.86)])
    _line(d, s, w, c, [(0.62, 0.14), (0.62, 0.3), (0.78, 0.3)])
    _line(d, s, w, c, [(0.34, 0.5), (0.66, 0.5)])
    _line(d, s, w, c, [(0.34, 0.66), (0.6, 0.66)])


def _i_puzzle(d, s, w, c):
    _line(d, s, w, c, [(0.16, 0.36), (0.36, 0.36), (0.36, 0.3)])
    _circle(d, s, w, c, 0.42, 0.26, 0.08)
    _line(d, s, w, c, [(0.48, 0.3), (0.48, 0.36), (0.68, 0.36)])
    _line(d, s, w, c, [(0.68, 0.36), (0.68, 0.56), (0.74, 0.56)])
    _circle(d, s, w, c, 0.78, 0.62, 0.08)
    _line(d, s, w, c, [(0.74, 0.68), (0.68, 0.68), (0.68, 0.84), (0.16, 0.84),
                       (0.16, 0.36)])


def _i_camera(d, s, w, c):
    _rrect(d, s, w, c, 0.12, 0.3, 0.88, 0.8, rad=0.07)
    _line(d, s, w, c, [(0.34, 0.3), (0.4, 0.18), (0.6, 0.18), (0.66, 0.3)])
    _circle(d, s, w, c, 0.5, 0.55, 0.14)


_ICONS = {
    "home": _i_home, "folder": _i_folder, "book": _i_book, "pen": _i_pen,
    "briefcase": _i_briefcase, "gear": _i_gear, "search": _i_search,
    "plus": _i_plus, "trash": _i_trash, "save": _i_save, "export": _i_export,
    "image": _i_image, "refresh": _i_refresh, "check": _i_check, "x": _i_x,
    "warning": _i_warning, "info": _i_info, "chevron-l": _i_chevron_l,
    "chevron-r": _i_chevron_r, "chevron-d": _i_chevron_d,
    "chevron-u": _i_chevron_u, "layers": _i_layers, "grid": _i_grid,
    "eye": _i_eye, "play": _i_play, "palette": _i_palette, "undo": _i_undo,
    "doc": _i_doc, "puzzle": _i_puzzle, "camera": _i_camera,
}

ICON_NAMES = tuple(_ICONS)


def render_icon_pil(name: str, size: int = 18, color: str | None = None):
    """Dibuja el icono y devuelve el PIL.Image RGBA (sin pasar por CTk)."""
    if not _OK:
        return None
    fn = _ICONS.get(name)
    if fn is None:
        logger.warning("icons: icono desconocido %r", name)
        fn = _i_info
    color = color or theme.TEXT_SECONDARY
    s = size * _SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fn(d, s, _stroke(size), color)
    return img.resize((size, size), Image.LANCZOS)


def get_icon(name: str, size: int = 18, color: str | None = None):
    """CTkImage del icono, cacheado por (name, size, color)."""
    if not _OK:
        return None
    color = color or theme.TEXT_SECONDARY
    key = (name, size, color)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    pil = render_icon_pil(name, size, color)
    if pil is None:
        return None
    img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))
    _cache[key] = img
    return img


def get_logo(size: int = 40, mini: bool = False):
    """Logo orbital: pastilla ámbar con anillo orbital fino y su satélite.

    mini=True → variante compacta para el sidebar colapsado.
    """
    if not _OK:
        return None
    key = ("__logo__", size, mini, theme.ACCENT_PRIMARY)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    s = size * _SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    amber = theme.ACCENT_PRIMARY
    cyan = theme.ACCENT_CYAN
    # Núcleo: pastilla ámbar
    pad = 0.28 if not mini else 0.3
    d.rounded_rectangle([pad * s, pad * s, (1 - pad) * s, (1 - pad) * s],
                        radius=0.13 * s, fill=amber)
    # Anillo orbital inclinado (elipse fina) + satélite cian
    w = max(2, round(size * _SS * 0.05))
    ellipse = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    de = ImageDraw.Draw(ellipse)
    de.ellipse([0.06 * s, 0.34 * s, 0.94 * s, 0.66 * s], outline=amber, width=w)
    ellipse = ellipse.rotate(-24, resample=Image.BICUBIC)
    img.alpha_composite(ellipse)
    # Satélite en la órbita
    sat_r = 0.06 * s
    sx, sy = 0.16 * s, 0.36 * s
    d = ImageDraw.Draw(img)
    d.ellipse([sx - sat_r, sy - sat_r, sx + sat_r, sy + sat_r], fill=cyan)
    pil = img.resize((size, size), Image.LANCZOS)
    out = ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))
    _cache[key] = out
    return out


def clear_cache() -> None:
    """Vacía el cache (al cambiar de tema, los defaults cambian de color)."""
    _cache.clear()

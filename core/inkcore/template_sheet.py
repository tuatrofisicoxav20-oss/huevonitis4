"""Plantilla de captura por grilla — una casilla por letra (Fase plantilla).

En vez de adivinar dónde empieza y termina cada letra en un renglón (lo que
falla con letra ligada/pegada y produce recortes y etiquetas corridas), se
imprime una hoja con UNA casilla rotulada por letra. El usuario escribe una
letra por casilla, le saca foto, y el extractor recorta cada casilla CONOCIDA:
no hay segmentación, alineación ni clasificación por posición.

Este módulo define:
  - `TemplateLayout`: la geometría canónica (compartida con template_extract).
  - `build_template_sheet`: genera la hoja imprimible (PIL.Image RGB).

La geometría es canónica (A4 @150dpi). El extractor rectifica la foto a este
mismo tamaño usando los 4 marcadores de esquina, así las casillas caen siempre
en las mismas coordenadas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# Conjuntos de caracteres seleccionables para la plantilla. El charset de un
# TemplateLayout se arma combinando los que el usuario elija (ver UI). El orden
# acá es el orden canónico de las casillas.
MINUSCULAS = "abcdefghijklmnñopqrstuvwxyz"          # ñ en la posición 14
MAYUSCULAS = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
DIGITOS = "0123456789"
PUNTUACION = ".,;:¿?¡!()-\"'"
VOCALES_ACENTUADAS = "áéíóúÁÉÍÓÚ"
# R10 (G3) — pares frecuentes del español capturados como LIGADURAS: se
# escriben juntos en una casilla y el banco/renderer los tratan como un
# "carácter" de 2 letras (lookup de par antes que de char suelto). Atajo
# barato a la semi-cursiva sin conectores Bézier.
PARES_FRECUENTES: tuple[str, ...] = ("qu", "ll", "rr", "ch", "de", "en", "la", "es")

# Compat: el alfabeto español base (las 27 minúsculas) sigue siendo el default.
SPANISH_ALPHABET = MINUSCULAS

# El registro de presets (TEMPLATE_PRESETS) se puebla al final del módulo, tras
# definir TemplateLayout. Ver _PRESET_SPECS y TEMPLATE_PRESETS más abajo.


@dataclass
class TemplateLayout:
    """Geometría canónica de la plantilla. Misma para generar y para extraer."""
    width: int = 1240
    height: int = 1754
    margin: int = 70
    fiducial: int = 56          # lado del cuadrado marcador de esquina
    label_strip: int = 30       # alto de la franja del rótulo (arriba de la casilla)
    inset: int = 10             # margen interno al recortar (evita bordes/rótulo)
    # Caracteres rotulados (uno por grupo de `repeats` casillas). Puede ser
    # str (un char por casilla) o LISTA de tokens donde un token de 2 letras
    # es una ligadura (R10): "qu" se escribe junta en una sola casilla.
    charset: str | list[str] = SPANISH_ALPHABET
    repeats: int = 1            # muestras por letra (casillas consecutivas con la misma letra)
    cols: int = 0              # 0 = auto en __post_init__ según charset/repeats

    # Derivados en __post_init__ (no pasar a mano)
    rows: int = field(default=0)
    grid_x0: int = field(default=0)
    grid_y0: int = field(default=0)
    grid_x1: int = field(default=0)
    grid_y1: int = field(default=0)

    def __post_init__(self):
        # repeats=1 con el alfabeto base conserva el diseño original (4×7 = 28
        # casillas); con más muestras o un charset grande la grilla se densifica
        # para acomodar len(charset)*repeats en una sola página A4.
        if self.repeats < 1:
            self.repeats = 1
        n_needed = len(self.charset) * self.repeats
        if self.cols <= 0:
            if self.repeats == 1 and len(self.charset) <= 28:
                self.cols = 4
            else:
                self.cols = 6
            # Charset/repeats grandes: agregar columnas (hasta 10) para que las
            # casillas no se vuelvan ilegibles ni se desborde la hoja. Con 10
            # columnas y ~18 filas entran ~180 casillas con área de escritura
            # todavía usable (>20px de alto).
            while self.cols < 10 and math.ceil(n_needed / self.cols) > 16:
                self.cols += 1
        self.rows = max(1, math.ceil(n_needed / self.cols))
        self.grid_x0 = self.margin + 50
        self.grid_y0 = self.margin + 110   # deja lugar para el título arriba
        self.grid_x1 = self.width - self.margin - 50
        self.grid_y1 = self.height - self.margin - 50

    # ── Geometría ────────────────────────────────────────────────
    @property
    def letters(self) -> str:
        """Alias histórico de `charset` (compat con código/tests previos)."""
        return self.charset

    @property
    def n_cells(self) -> int:
        return self.cols * self.rows

    def cell_letter(self, index: int) -> str | None:
        """Carácter rotulado en la casilla `index`, o None si es casilla libre.

        Con repeats>1 las casillas consecutivas comparten carácter: índices
        0..repeats-1 → primer carácter, etc. Las casillas más allá de
        len(charset)*repeats quedan sin rótulo (sobrantes de la grilla).
        """
        li = index // self.repeats
        if 0 <= li < len(self.charset):
            return self.charset[li]
        return None

    @property
    def cell_w(self) -> float:
        return (self.grid_x1 - self.grid_x0) / self.cols

    @property
    def cell_h(self) -> float:
        return (self.grid_y1 - self.grid_y0) / self.rows

    def fiducial_centers(self) -> list[tuple[int, int]]:
        """Centros de los 4 marcadores: TL, TR, BL, BR (orden fijo)."""
        m = self.margin
        return [
            (m, m), (self.width - m, m),
            (m, self.height - m), (self.width - m, self.height - m),
        ]

    def cell_rect(self, index: int) -> tuple[int, int, int, int]:
        """Rectángulo (x, y, w, h) de la casilla completa (con borde y rótulo)."""
        r, c = divmod(index, self.cols)
        x = int(self.grid_x0 + c * self.cell_w)
        y = int(self.grid_y0 + r * self.cell_h)
        return x, y, int(self.cell_w), int(self.cell_h)

    def writing_rect(self, index: int) -> tuple[int, int, int, int]:
        """Área de escritura recortable (sin borde ni franja de rótulo)."""
        x, y, w, h = self.cell_rect(index)
        ins = self.inset
        wx = x + ins
        wy = y + self.label_strip + ins
        ww = w - 2 * ins
        wh = h - self.label_strip - 2 * ins
        return wx, wy, max(1, ww), max(1, wh)


def _load_font(size: int):
    for path in (
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_template_sheet(layout: TemplateLayout | None = None) -> Image.Image | None:
    """Genera la hoja imprimible (PIL RGB). None si falta PIL."""
    if not _PIL_OK:
        return None
    lay = layout or TemplateLayout()
    img = Image.new("RGB", (lay.width, lay.height), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    # Marcadores de esquina (cuadrados negros sólidos) para rectificar la foto.
    half = lay.fiducial // 2
    for (cx, cy) in lay.fiducial_centers():
        draw.rectangle((cx - half, cy - half, cx + half, cy + half), fill="#000000")

    # Título e instrucciones.
    title_font = _load_font(34)
    sub_font = _load_font(20)
    draw.text((lay.margin + 50, lay.margin - 6), "Plantilla de letra — Huevonitis",
              fill="#1A1A2E", font=title_font)
    draw.text((lay.margin + 50, lay.margin + 38),
              "Escribí una letra por casilla, centrada y sin tocar los bordes. "
              "Tinta oscura, buena luz. Luego sacale una foto derecha.",
              fill="#555555", font=sub_font)
    if lay.repeats > 1:
        draw.text((lay.margin + 50, lay.margin + 62),
                  f"Cada letra tiene {lay.repeats} casillas: escribila {lay.repeats} "
                  "veces (tu variación natural mejora el banco).",
                  fill="#777777", font=sub_font)

    # Casillas. Con la grilla densa (repeats altos) el rótulo se achica para
    # no comerse el área de escritura.
    label_font = _load_font(22 if lay.rows <= 8 else 16)
    free_font = sub_font if lay.rows <= 8 else _load_font(13)
    for i in range(lay.n_cells):
        x, y, w, h = lay.cell_rect(i)
        # Borde de la casilla (gris claro, fino: fácil de quitar al extraer).
        draw.rectangle((x, y, x + w, y + h), outline="#B8B8B8", width=2)
        # Franja de rótulo separada del área de escritura por una línea.
        draw.line((x, y + lay.label_strip, x + w, y + lay.label_strip),
                  fill="#D8D8D8", width=1)
        ch = lay.cell_letter(i)
        if ch is not None:
            draw.text((x + 8, y + 4), ch, fill="#9AA0A6", font=label_font)
        else:
            draw.text((x + 8, y + 4), "(libre)", fill="#C8C8C8", font=free_font)
    return img


# ── Registro de presets (E3) ─────────────────────────────────────────
# Presets de plantilla conocidos. La detección de layout por página prueba
# estos candidatos por SCORING estructural barato; cols/rows salen solos de
# TemplateLayout.__post_init__. Los charsets de las hojas densas (×8/×12) se
# midieron por diff de píxeles contra las plantillas reales del usuario (las
# "Tandas"), con diff 1.5-2.0 sobre 255 → coincidencia exacta de la grilla.
#
# Cuando dos presets comparten geometría (varias hojas de minúsculas parciales
# caen en 6×16), el scoring estructural empata y el desempate lo hace el acuerdo
# CNN casilla↔letra (todas son a-z). Las hojas de acentos/dígitos tienen
# geometría única, así que no necesitan ese desempate.
_PRESET_SPECS: dict[str, tuple[str, int]] = {
    # Las que genera la UI hoy (checkbox minúsculas × reps 1-3).
    "minusculas_x1": (MINUSCULAS, 1),       # 4×7 — el abecedario completo
    "minusculas_x2": (MINUSCULAS, 2),       # 6×9
    "minusculas_x3": (MINUSCULAS, 3),       # 6×14
    # Hojas densas reales del usuario (charsets medidos contra los PDF).
    "acentuadas_x12": ("áéíóúñ", 12),                # 6×12 — vocales acentuadas + ñ
    "digitos_signos_x8": (DIGITOS + "¿?¡!:;-", 8),   # 9×16 — números y signos
    "comunes_aeiosnr_x12": ("aeiosnr.", 12),         # 6×16 — comunes A
    "comunes_ltcdmp_x12": ("ltcdmp.,", 12),          # 6×16 — comunes B
    "resto_letras_x8": ("bfghjkqvwxyz", 8),          # 6×16 — resto de letras
    "mayusculas_frec_x12": ("EACVSDLPMT", 12),       # 8×15 — mayúsculas frecuentes
}

TEMPLATE_PRESETS: dict[str, TemplateLayout] = {
    name: TemplateLayout(charset=cs, repeats=reps)
    for name, (cs, reps) in _PRESET_SPECS.items()
}


# Piso de legibilidad (px) del área de escritura de una casilla. Por debajo, la
# casilla es demasiado chica para escribir cómodo. Es > 20 a propósito: el test
# `test_charset_grande_entra_en_una_pagina_legible` ya codifica que ×2 del combo
# completo (casilla mínima ~30px) entra en UNA hoja, así que el piso debe dejar
# pasar ese caso y sólo paginar cuando la casilla caería de verdad ilegible
# (combo completo ×3 da ~3px → se reparte en varias hojas).
MIN_WRITE_PX = 22


def paginate_layouts(
    charset: str | list[str], repeats: int = 1, *, min_write: int = MIN_WRITE_PX,
) -> list[TemplateLayout]:
    """Reparte `charset` en una o varias hojas A4 con casillas LEGIBLES.

    Una sola hoja A4 sólo acomoda tantas casillas antes de que el área de
    escritura caiga por debajo de `min_write` (combo completo ×3 → ~3px,
    ilegible). En vez de apretujar todo en una hoja (lo que rompía "bien
    acomodadas"), se corta el charset en frontera de carácter: cada página es un
    `TemplateLayout` autónomo con su propio slice, su grilla y sus casillas
    legibles. La última página, parcial, arma su layout del slice real (cols/rows
    salen solos de `__post_init__`), así nunca queda una hoja casi vacía mal
    proporcionada.

    Devuelve la lista de layouts (una entrada = una hoja). Las páginas comparten
    `repeats`; la extracción identifica cada hoja por su geometría/charset.
    """
    repeats = max(1, repeats)
    n = len(charset)
    if n == 0:
        return [TemplateLayout(charset=charset, repeats=repeats)]

    def _legible(k: int) -> bool:
        lay = TemplateLayout(charset=charset[:k], repeats=repeats)
        _wx, _wy, ww, wh = lay.writing_rect(0)   # grilla uniforme: la casilla 0 representa a todas
        return ww >= min_write and wh >= min_write

    if _legible(n):
        return [TemplateLayout(charset=charset, repeats=repeats)]
    # Mayor nº de caracteres por hoja que sigue legible (barrido lineal: los
    # saltos de columna de __post_init__ rompen la monotonía estricta y un
    # binary search podría saltarse el límite real).
    k = n
    while k > 1 and not _legible(k):
        k -= 1
    k_max = max(1, k)
    n_pages = math.ceil(n / k_max)
    per_page = math.ceil(n / n_pages)   # repartir parejo (no 80/7 sino p. ej. 44/43)
    return [TemplateLayout(charset=charset[s:s + per_page], repeats=repeats)
            for s in range(0, n, per_page)]


def save_template_sheet(out_path: str, layout: TemplateLayout | None = None) -> str:
    """Genera y guarda UNA hoja de plantilla (PNG o PDF según extensión).

    Compat: una sola hoja con el layout dado tal cual (sin paginar). El flujo de
    la UI usa `save_template_sheets`, que pagina los combos grandes.
    """
    img = build_template_sheet(layout)
    if img is None:
        raise RuntimeError("PIL no disponible: no se puede generar la plantilla")
    from pathlib import Path
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() == ".pdf":
        img.save(p, "PDF", resolution=150.0)
    else:
        img.save(p)
    return str(p)


def save_template_sheets(out_path: str, layouts: list[TemplateLayout]) -> list[str]:
    """Guarda una o varias hojas. PDF → multipágina; PNG → una por archivo.

    Devuelve la lista de rutas escritas. Para `.pdf` se escribe un único PDF con
    todas las páginas (`save_all=True`); para imágenes (no multipágina) cada hoja
    va a `nombre_p1.png`, `nombre_p2.png`, … salvo que sea una sola.
    """
    if not layouts:
        raise RuntimeError("save_template_sheets: lista de layouts vacía")
    from pathlib import Path
    imgs = [build_template_sheet(lay) for lay in layouts]
    imgs = [im for im in imgs if im is not None]
    if not imgs:
        raise RuntimeError("PIL no disponible: no se puede generar la plantilla")
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() == ".pdf":
        imgs[0].save(p, "PDF", resolution=150.0, save_all=True,
                     append_images=imgs[1:])
        return [str(p)]
    if len(imgs) == 1:
        imgs[0].save(p)
        return [str(p)]
    out_paths = []
    for i, im in enumerate(imgs, start=1):
        pp = p.with_name(f"{p.stem}_p{i}{p.suffix}")
        im.save(pp)
        out_paths.append(str(pp))
    return out_paths

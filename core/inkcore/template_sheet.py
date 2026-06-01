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

from dataclasses import dataclass, field

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# Alfabeto español, ñ en la posición 14 (igual que el resto del proyecto).
SPANISH_ALPHABET = "abcdefghijklmnñopqrstuvwxyz"


@dataclass
class TemplateLayout:
    """Geometría canónica de la plantilla. Misma para generar y para extraer."""
    width: int = 1240
    height: int = 1754
    margin: int = 70
    fiducial: int = 56          # lado del cuadrado marcador de esquina
    cols: int = 4
    rows: int = 7               # 4×7 = 28 casillas (27 letras + 1 sobrante)
    label_strip: int = 30       # alto de la franja del rótulo (arriba de la casilla)
    inset: int = 10             # margen interno al recortar (evita bordes/rótulo)
    letters: str = SPANISH_ALPHABET

    # Área de grilla (entre los marcadores), calculada en __post_init__
    grid_x0: int = field(default=0)
    grid_y0: int = field(default=0)
    grid_x1: int = field(default=0)
    grid_y1: int = field(default=0)

    def __post_init__(self):
        self.grid_x0 = self.margin + 50
        self.grid_y0 = self.margin + 110   # deja lugar para el título arriba
        self.grid_x1 = self.width - self.margin - 50
        self.grid_y1 = self.height - self.margin - 50

    # ── Geometría ────────────────────────────────────────────────
    @property
    def n_cells(self) -> int:
        return self.cols * self.rows

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


def build_template_sheet(layout: TemplateLayout | None = None) -> "Image.Image | None":
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
              "Escribí UNA letra por casilla, centrada y sin tocar los bordes. "
              "Tinta oscura, buena luz. Luego sacale una foto derecha.",
              fill="#555555", font=sub_font)

    # Casillas.
    label_font = _load_font(22)
    for i in range(lay.n_cells):
        x, y, w, h = lay.cell_rect(i)
        # Borde de la casilla (gris claro, fino: fácil de quitar al extraer).
        draw.rectangle((x, y, x + w, y + h), outline="#B8B8B8", width=2)
        # Franja de rótulo separada del área de escritura por una línea.
        draw.line((x, y + lay.label_strip, x + w, y + lay.label_strip),
                  fill="#D8D8D8", width=1)
        if i < len(lay.letters):
            ch = lay.letters[i]
            draw.text((x + 8, y + 4), ch, fill="#9AA0A6", font=label_font)
        else:
            draw.text((x + 8, y + 4), "(libre)", fill="#C8C8C8", font=sub_font)
    return img


def save_template_sheet(out_path: str, layout: TemplateLayout | None = None) -> str:
    """Genera y guarda la plantilla (PNG o PDF según extensión)."""
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

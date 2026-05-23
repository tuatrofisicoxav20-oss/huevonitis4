from core.inkcore.glyph_labelers.base import GlyphLabeler
from core.inkcore.glyph_labelers.tesseract_labeler import TesseractLabeler
from core.inkcore.glyph_labelers.trocr_labeler import TrOCRLabeler

REGISTRY: dict[str, type[GlyphLabeler]] = {
    TesseractLabeler.name: TesseractLabeler,
    TrOCRLabeler.name: TrOCRLabeler,
}


def get_available() -> dict[str, bool]:
    """Devuelve {nombre_etiquetador: disponible} para todos los etiquetadores registrados."""
    return {name: cls.available for name, cls in REGISTRY.items()}


def get_labeler(name: str) -> GlyphLabeler:
    """Instancia el etiquetador pedido; cae a TesseractLabeler si no existe."""
    cls = REGISTRY.get(name, TesseractLabeler)
    return cls()

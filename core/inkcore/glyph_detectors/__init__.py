from core.inkcore.glyph_detectors.base import GlyphDetector
from core.inkcore.glyph_detectors.classic_cv import ClassicCVDetector

REGISTRY: dict[str, type[GlyphDetector]] = {
    ClassicCVDetector.name: ClassicCVDetector,
}


def get_available() -> dict[str, bool]:
    """Devuelve {nombre_detector: disponible} para todos los detectores registrados."""
    return {name: cls.available for name, cls in REGISTRY.items()}


def get_detector(name: str) -> GlyphDetector:
    """Instancia el detector pedido; cae a ClassicCVDetector si no existe."""
    cls = REGISTRY.get(name, ClassicCVDetector)
    return cls()

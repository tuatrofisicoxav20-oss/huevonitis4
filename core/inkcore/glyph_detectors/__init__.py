from core.inkcore.glyph_detectors.base import GlyphDetector
from core.inkcore.glyph_detectors.classic_cv import ClassicCVDetector
from core.inkcore.glyph_detectors.craft import CRAFTDetector
from core.inkcore.glyph_detectors.easyocr_det import EasyOCRDetector
from core.inkcore.glyph_detectors.paddle_det import PaddleDetector

REGISTRY: dict[str, type[GlyphDetector]] = {
    ClassicCVDetector.name: ClassicCVDetector,
    CRAFTDetector.name: CRAFTDetector,
    EasyOCRDetector.name: EasyOCRDetector,
    PaddleDetector.name: PaddleDetector,
}


def get_available() -> dict[str, bool]:
    """Devuelve {nombre_detector: disponible} para todos los detectores registrados."""
    return {name: cls.available for name, cls in REGISTRY.items()}


def get_detector(name: str) -> GlyphDetector:
    """Instancia el detector pedido; cae a ClassicCVDetector si no existe."""
    cls = REGISTRY.get(name, ClassicCVDetector)
    return cls()

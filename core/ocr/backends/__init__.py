from core.ocr.backends.tesseract import TesseractBackend
from core.ocr.backends.paddleocr import PaddleOCRBackend
from core.ocr.backends.doctr import DoctrBackend
from core.ocr.backends.easyocr import EasyOCRBackend
from core.ocr.base import OCRBackend

REGISTRY: dict[str, type[OCRBackend]] = {
    TesseractBackend.name: TesseractBackend,
    PaddleOCRBackend.name: PaddleOCRBackend,
    DoctrBackend.name: DoctrBackend,
    EasyOCRBackend.name: EasyOCRBackend,
}


def get_available() -> dict[str, bool]:
    """Devuelve {nombre_backend: disponible} para todos los backends registrados."""
    return {name: cls.available for name, cls in REGISTRY.items()}


def get_backend(name: str) -> OCRBackend:
    """Instancia el backend pedido; cae a TesseractBackend si no existe."""
    cls = REGISTRY.get(name, TesseractBackend)
    return cls()

"""
Lector de PDFs con detección automática: texto extraíble → pdfplumber,
PDF escaneado → rasterizar + backend OCR activo.
"""
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER_OK = True
except ImportError:
    _PDFPLUMBER_OK = False

try:
    from pdf2image import convert_from_path as _convert_from_path
    _PDF2IMAGE_OK = True
except ImportError:
    _PDF2IMAGE_OK = False


def _has_extractable_text(pdf_path: str) -> bool:
    """Devuelve True si el PDF tiene texto seleccionable (no es imagen pura)."""
    if not _PDFPLUMBER_OK:
        return False
    try:
        with _pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:3]:
                text = page.extract_text()
                if text and text.strip():
                    return True
    except Exception:
        pass
    return False


def read_pdf(pdf_path: str, ocr_backend=None) -> str:
    """
    Lee un PDF y devuelve su texto.

    Ruta 1 (PDF con texto): usa pdfplumber directamente, sin OCR.
    Ruta 2 (PDF escaneado): rasteriza páginas con pdf2image y aplica ocr_backend.
    """
    path = Path(pdf_path)
    if not path.exists():
        return f"Error: archivo no encontrado: {pdf_path}"

    if not _PDFPLUMBER_OK and not _PDF2IMAGE_OK:
        return (
            "No hay lector de PDF disponible. Instalar con:\n"
            "pip install pdfplumber pdf2image\n"
            "sudo dnf install poppler-utils"
        )

    if _PDFPLUMBER_OK and _has_extractable_text(pdf_path):
        try:
            with _pdfplumber.open(pdf_path) as pdf:
                pages_text = [
                    page.extract_text()
                    for page in pdf.pages
                    if page.extract_text()
                ]
            return "\n\n".join(pages_text).strip()
        except Exception as e:
            logger.error(f"pdfplumber error: {e}")
            # Caer al modo OCR si pdfplumber falla

    if not _PDF2IMAGE_OK:
        return (
            "PDF escaneado detectado pero pdf2image no está instalado.\n"
            "pip install pdf2image\n"
            "sudo dnf install poppler-utils"
        )
    if ocr_backend is None:
        return (
            "PDF escaneado detectado pero no hay backend OCR configurado.\n"
            "Selecciona un backend OCR en Configuración."
        )

    try:
        images = _convert_from_path(pdf_path, dpi=200)
        all_text = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, img in enumerate(images):
                img_path = str(Path(tmpdir) / f"page_{i:04d}.png")
                img.save(img_path, "PNG")
                page_text = ocr_backend.extract_text(img_path)
                all_text.append(page_text)
        return "\n\n".join(all_text).strip()
    except Exception as e:
        logger.error(f"PDF OCR rasterize error: {e}")
        return f"Error al procesar PDF escaneado: {e}"

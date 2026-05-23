"""
Clasificador de PDFs: determina si un PDF tiene texto seleccionable,
es un escaneado puro, o es mixto (algunas páginas con texto, otras sin él).

Devuelve "text" | "scan" | "mixed"
"""
import logging

logger = logging.getLogger(__name__)

try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER_OK = True
except ImportError:
    _PDFPLUMBER_OK = False

# Caracteres mínimos (sin espacios) para considerar una página como "con texto"
_MIN_CHARS_PER_PAGE = 50
# Proporción de páginas con texto para clasificar como "text" (vs "mixed")
_TEXT_PAGE_RATIO = 0.80


def _page_has_extractable_text(page) -> bool:
    """
    Determina si una página tiene texto seleccionable suficiente.
    Criterio: >50 caracteres no-blancos extraíbles.
    """
    try:
        text = page.extract_text() or ""
        chars = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
        return chars >= _MIN_CHARS_PER_PAGE
    except Exception:
        return False


def classify_pdf(pdf_path: str) -> str:
    """
    Clasifica un PDF.
    Retorna "text", "scan" o "mixed".

    - text:  ≥80% de páginas tienen texto extraíble (>50 chars sin blancos)
    - scan:  ≤20% — escaneo puro, requiere OCR completo
    - mixed: caso intermedio

    Si pdfplumber no está disponible, asume "scan".
    """
    if not _PDFPLUMBER_OK:
        return "scan"

    try:
        with _pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            if total == 0:
                return "scan"

            text_pages = sum(
                1 for page in pdf.pages
                if _page_has_extractable_text(page)
            )

            ratio = text_pages / total
            if ratio >= _TEXT_PAGE_RATIO:
                return "text"
            if ratio <= (1.0 - _TEXT_PAGE_RATIO):
                return "scan"
            return "mixed"
    except Exception as exc:
        logger.warning("classify_pdf: error leyendo '%s': %s", pdf_path, exc)
        return "scan"

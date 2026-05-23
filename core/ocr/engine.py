"""
OCREngine — wrapper público de OCR.

Mantiene la misma firma pública de todas las versiones anteriores.
Delega internamente al backend configurado en config.OCR_BACKEND.
Default: Tesseract (sin dependencias nuevas).
"""
import logging

import config

logger = logging.getLogger(__name__)


class OCREngine:

    def __init__(self):
        from core.ocr import backends as _backends
        self._backend = _backends.get_backend(config.OCR_BACKEND)
        logger.debug(f"OCREngine usando backend: {self._backend.name}")

    def extract_text(self, image_path: str) -> str:
        """Extrae texto de una imagen usando el backend activo."""
        return self._backend.extract_text(image_path)

    def extract_text_with_boxes(self, image_path: str) -> list[dict]:
        """Extrae texto con bounding boxes."""
        return self._backend.extract_text_with_boxes(image_path)

    def read_docx(self, docx_path: str) -> str:
        """Lee el texto de un documento .docx."""
        from core.ocr.document_readers.docx_reader import read_docx
        return read_docx(docx_path)

    def read_pdf(self, pdf_path: str) -> str:
        """Lee el texto de un PDF (con texto o escaneado)."""
        from core.ocr.document_readers.pdf_reader import read_pdf
        return read_pdf(pdf_path, self._backend)

    def ingest_document(
        self,
        source_path: str,
        options=None,
        progress_cb=None,
        cancel_event=None,
    ):
        """
        Ingesta un documento (PDF, DOCX, imagen, carpeta) y devuelve un Document
        estructurado con TextBlocks tipados.

        Args:
            source_path: Ruta al archivo o carpeta.
            options: OCROptions (None = defaults).
            progress_cb: callable(fracción 0-1, mensaje).
            cancel_event: threading.Event para cancelar procesamiento largo.
        Returns:
            core.ocr.document_model.Document
        """
        from core.ocr.ingestion import DocumentIngestion
        from core.ocr.options import OCROptions
        if options is None:
            options = OCROptions()
        ingestion = DocumentIngestion(self._backend, options)
        return ingestion.ingest(source_path, progress_cb=progress_cb, cancel_event=cancel_event)

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def switch_backend(self, name: str) -> None:
        """Cambia el backend en tiempo de ejecución (sin reiniciar la app)."""
        from core.ocr import backends as _backends
        self._backend = _backends.get_backend(name)
        logger.info(f"OCREngine cambiado a backend: {self._backend.name}")

    @staticmethod
    def available_backends() -> dict[str, bool]:
        """Devuelve {nombre_backend: disponible} para la UI."""
        from core.ocr import backends as _backends
        return _backends.get_available()

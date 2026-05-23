"""
Lector de imágenes individuales → Document.
Acepta cualquier formato soportado por Pillow/OpenCV.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from core.ocr.document_model import BlockType, Document, DocumentPage, TextBlock

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}


def read_image(
    image_path: str,
    ocr_backend,
    lang: str = "spa",
    progress_cb: Callable[[float, str], None] | None = None,
    detect_handwriting: bool = False,
) -> Document:
    """
    Extrae texto de una imagen individual y lo devuelve como Document.

    Args:
        image_path: Ruta a la imagen.
        ocr_backend: Instancia de OCRBackend.
        lang: Idioma OCR.
        progress_cb: callback(fracción 0-1, mensaje).
        detect_handwriting: Si True, usa extract_text_with_boxes y marca is_handwritten.
    """
    path = Path(image_path)
    doc = Document(source_path=str(path), source_type="image")

    if not path.exists():
        logger.error("read_image: archivo no encontrado: %s", image_path)
        return doc

    if progress_cb:
        progress_cb(0.1, f"Procesando {path.name}…")

    page_doc = DocumentPage(page_number=1, source_path=str(path))

    if detect_handwriting and hasattr(ocr_backend, "extract_text_with_boxes"):
        try:
            boxes = ocr_backend.extract_text_with_boxes(str(path), lang=lang)
        except Exception as exc:
            logger.error("read_image: boxes error en '%s': %s", image_path, exc)
            boxes = []
        for box in boxes:
            text = str(box.get("text", "")).strip()
            if text:
                page_doc.blocks.append(TextBlock(
                    text=text,
                    block_type=BlockType.PARAGRAPH,
                    confidence=float(box.get("conf", 1.0)),
                    bbox=box.get("bbox"),
                    is_handwritten=box.get("is_handwritten"),
                ))
    else:
        try:
            raw_text = ocr_backend.extract_text(str(path), lang=lang)
        except Exception as exc:
            logger.error("read_image: OCR error en '%s': %s", image_path, exc)
            raw_text = ""
        for line in raw_text.splitlines():
            line = line.strip()
            if line:
                page_doc.blocks.append(TextBlock(text=line, block_type=BlockType.PARAGRAPH))

    doc.pages.append(page_doc)

    if progress_cb:
        progress_cb(1.0, "Listo")

    return doc

"""
Lector de carpetas de imágenes → Document concatenado.
Las imágenes se procesan en orden alfabético (natural sort por nombre).
"""
from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path

from core.ocr.document_model import Document, DocumentPage
from core.ocr.document_readers.image_reader import SUPPORTED_EXTS

logger = logging.getLogger(__name__)


def _natural_key(path: Path) -> list:
    """Clave de ordenamiento natural (e.g. page2 < page10)."""
    parts = re.split(r"(\d+)", path.stem)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def read_folder(
    folder_path: str,
    ocr_backend,
    lang: str = "spa",
    progress_cb: Callable[[float, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Document:
    """
    Lee todas las imágenes de `folder_path` y las combina en un Document.
    Cada imagen se convierte en una DocumentPage separada.

    Args:
        folder_path: Ruta a la carpeta.
        ocr_backend: Instancia de OCRBackend.
        lang: Idioma OCR.
        progress_cb: callback(fracción 0-1, mensaje).
        cancel_event: Event de cancelación.
    """
    folder = Path(folder_path)
    doc = Document(source_path=str(folder), source_type="folder")

    if not folder.is_dir():
        logger.error("read_folder: no es una carpeta: %s", folder_path)
        return doc

    images = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED_EXTS],
        key=_natural_key,
    )

    if not images:
        logger.warning("read_folder: sin imágenes en '%s'", folder_path)
        return doc

    total = len(images)

    for i, img_path in enumerate(images):
        if cancel_event and cancel_event.is_set():
            logger.info("read_folder: cancelado en imagen %d/%d", i + 1, total)
            break

        if progress_cb:
            progress_cb(i / total, f"Imagen {i + 1}/{total}: {img_path.name}")

        try:
            raw = ocr_backend.extract_text(str(img_path), lang=lang)
        except Exception as exc:
            logger.error("read_folder: OCR error '%s': %s", img_path.name, exc)
            raw = ""

        page_doc = DocumentPage(page_number=i + 1, source_path=str(img_path))
        from core.ocr.document_model import BlockType, TextBlock
        for line in raw.splitlines():
            line = line.strip()
            if line:
                page_doc.blocks.append(
                    TextBlock(text=line, block_type=BlockType.PARAGRAPH)
                )
        doc.pages.append(page_doc)

    if progress_cb:
        progress_cb(1.0, "Listo")

    return doc

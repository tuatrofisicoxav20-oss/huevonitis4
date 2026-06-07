"""
Lector de PDFs mixtos: páginas con texto se leen con pdfplumber,
páginas sin texto se rasterizancn OCR en batches de 4 para limitar RAM.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from core.ocr.document_model import BlockType, Document, DocumentPage, TextBlock

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

_MIN_WORDS_TEXT_PAGE = 20
_BATCH_SIZE = 4  # páginas OCR por tanda


def read_pdf_mixed(
    pdf_path: str,
    ocr_backend,
    dpi: int = 200,
    lang: str = "spa",
    pdf_pages: list[int] | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Document:
    """
    Procesa un PDF mixto página a página.
    Cada página se trata como texto o escaneado según su contenido.
    Las páginas que requieren OCR se rasterizancn en batches de 4.
    """
    path = Path(pdf_path)
    doc = Document(source_path=str(path), source_type="mixed_pdf")

    if not _PDFPLUMBER_OK:
        from core.ocr.document_readers.pdf_scan_reader import read_pdf_scan
        result = read_pdf_scan(
            pdf_path, ocr_backend, dpi=dpi, lang=lang,
            pdf_pages=pdf_pages, progress_cb=progress_cb, cancel_event=cancel_event,
        )
        result.source_type = "mixed_pdf"
        return result

    try:
        with _pdfplumber.open(str(path)) as pdf:
            total_pages = len(pdf.pages)
            indices = pdf_pages if pdf_pages is not None else list(range(total_pages))
            total = len(indices)

            # Clasificar cada página: texto directo o escaneada
            page_texts: dict[int, str] = {}
            scan_indices: list[int] = []

            for idx in indices:
                if idx < 0 or idx >= total_pages:
                    continue
                text = pdf.pages[idx].extract_text() or ""
                if len(text.split()) >= _MIN_WORDS_TEXT_PAGE:
                    page_texts[idx] = text
                else:
                    scan_indices.append(idx)

            # Rasterizar páginas escaneadas en batches de 4
            # scan_images: idx → ruta PNG temporal
            scan_images: dict[int, str] = {}
            if scan_indices and _PDF2IMAGE_OK and ocr_backend is not None:
                with tempfile.TemporaryDirectory() as tmpdir:
                    for batch_start in range(0, len(scan_indices), _BATCH_SIZE):
                        batch = scan_indices[batch_start:batch_start + _BATCH_SIZE]
                        first = min(batch) + 1   # pdf2image es base-1
                        last = max(batch) + 1
                        try:
                            imgs = _convert_from_path(
                                str(path), dpi=dpi, first_page=first, last_page=last
                            )
                        except Exception as exc:
                            logger.error(
                                "pdf_mixed: rasterización fallida pp %d-%d: %s",
                                first, last, exc
                            )
                            continue
                        page_set = set(batch)
                        for local_i, img in enumerate(imgs):
                            real_idx = (first - 1) + local_i  # base-0
                            if real_idx not in page_set:
                                img.close()
                                del img
                                continue
                            out_path = str(Path(tmpdir) / f"scan_{real_idx:04d}.png")
                            img.save(out_path, "PNG")
                            img.close()
                            del img
                            scan_images[real_idx] = out_path
                        del imgs

                    # Procesar las páginas en orden
                    for i, idx in enumerate(indices):
                        if cancel_event and cancel_event.is_set():
                            break
                        if progress_cb:
                            progress_cb(i / total, f"Página {idx + 1}/{total_pages}…")
                        page_doc = DocumentPage(page_number=idx + 1, source_path=str(path))

                        if idx in page_texts:
                            for line in page_texts[idx].splitlines():
                                line = line.strip()
                                if line:
                                    page_doc.blocks.append(
                                        TextBlock(text=line, block_type=BlockType.PARAGRAPH)
                                    )
                        elif idx in scan_images:
                            try:
                                raw = ocr_backend.extract_text(scan_images[idx], lang=lang)
                            except Exception as exc:
                                logger.error("OCR mixto página %d: %s", idx + 1, exc)
                                raw = ""
                            for line in raw.splitlines():
                                line = line.strip()
                                if line:
                                    page_doc.blocks.append(
                                        TextBlock(text=line, block_type=BlockType.PARAGRAPH)
                                    )

                        doc.pages.append(page_doc)
            else:
                # Sin páginas OCR o sin dependencias: solo páginas de texto
                for i, idx in enumerate(indices):
                    if cancel_event and cancel_event.is_set():
                        break
                    if progress_cb:
                        progress_cb(i / total, f"Página {idx + 1}/{total_pages}…")
                    page_doc = DocumentPage(page_number=idx + 1, source_path=str(path))
                    if idx in page_texts:
                        for line in page_texts[idx].splitlines():
                            line = line.strip()
                            if line:
                                page_doc.blocks.append(
                                    TextBlock(text=line, block_type=BlockType.PARAGRAPH)
                                )
                    doc.pages.append(page_doc)

    except Exception as exc:
        logger.error("pdf_mixed_reader: error en '%s': %s", pdf_path, exc, exc_info=True)

    if progress_cb:
        progress_cb(1.0, "Listo")

    return doc

"""
Lector de PDFs escaneados (imagen pura).
Rasteriza en batches de BATCH_SIZE páginas para limitar uso de RAM.
Soporta cancelación mediante threading.Event y progreso por callback.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.ocr.document_model import BlockType, Document, DocumentPage, TextBlock

logger = logging.getLogger(__name__)

try:
    from pdf2image import convert_from_path as _convert_from_path
    from pdf2image import pdfinfo_from_path as _pdfinfo_from_path
    _PDF2IMAGE_OK = True
except ImportError:
    _PDF2IMAGE_OK = False

_BATCH_SIZE = 4  # páginas por tanda (límite de RAM)


def _get_total_pages(pdf_path: str) -> int | None:
    """Devuelve el número total de páginas del PDF, o None si no se puede leer."""
    try:
        info = _pdfinfo_from_path(str(pdf_path))
        return int(info["Pages"])
    except Exception:
        return None


def read_pdf_scan(
    pdf_path: str,
    ocr_backend,
    dpi: int = 200,
    lang: str = "spa",
    pdf_pages: list[int] | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
    cancel_event: threading.Event | None = None,
    detect_handwriting: bool = False,
) -> Document:
    """
    Rasteriza un PDF escaneado y extrae texto mediante OCR.
    Las páginas se convierten en batches de 4 para no acumular imágenes en RAM.

    Args:
        pdf_path: Ruta al PDF.
        ocr_backend: Instancia de OCRBackend a usar.
        dpi: Resolución de rasterizado.
        lang: Idioma OCR.
        pdf_pages: Índices de páginas (base-0). None = todas.
        progress_cb: callback(fracción 0-1, mensaje).
        cancel_event: Event que, si se activa, interrumpe el procesamiento.
        detect_handwriting: Si True, extrae bboxes con indicador de escritura manual.
    """
    path = Path(pdf_path)
    doc = Document(source_path=str(path), source_type="scan_pdf")

    if not _PDF2IMAGE_OK:
        logger.error("pdf2image no instalado — no se puede leer PDF escaneado")
        return doc

    if ocr_backend is None:
        logger.error("read_pdf_scan: se requiere un backend OCR")
        return doc

    try:
        # Determinar páginas a procesar en formato 1-based para pdf2image
        if pdf_pages is not None:
            pages_1b = sorted(set(p + 1 for p in pdf_pages if p >= 0))
        else:
            total = _get_total_pages(str(path))
            if total is None:
                # Fallback: convertir todo de una vez (PDF sin info de páginas)
                pages_1b = None
            else:
                pages_1b = list(range(1, total + 1))

        with tempfile.TemporaryDirectory() as tmpdir:
            if pages_1b is None:
                # Fallback path: convertir todo de una vez
                images = _convert_from_path(str(path), dpi=dpi)
                _process_images(images, doc, ocr_backend, path, tmpdir,
                                lang, detect_handwriting, progress_cb, cancel_event)
            else:
                total = len(pages_1b)
                processed = 0
                for batch_start in range(0, total, _BATCH_SIZE):
                    if cancel_event and cancel_event.is_set():
                        logger.info("read_pdf_scan: cancelado en página %d/%d",
                                    processed + 1, total)
                        break

                    batch = pages_1b[batch_start:batch_start + _BATCH_SIZE]
                    first, last = min(batch), max(batch)
                    try:
                        imgs = _convert_from_path(
                            str(path), dpi=dpi, first_page=first, last_page=last
                        )
                    except Exception as exc:
                        logger.error("pdf_scan: rasterización fallida pp %d-%d: %s",
                                     first, last, exc)
                        processed += len(batch)
                        continue

                    # Guardar todas las páginas del batch a disco primero,
                    # luego correr OCR en paralelo (4 threads, tantos como
                    # páginas hay en el batch). El backend OCR libera el GIL
                    # en sus llamadas C, así que la paralelización es real.
                    page_set = set(batch)
                    saved_pages: list[tuple[int, str]] = []  # (real_page_1b, path)
                    for local_i, img in enumerate(imgs):
                        real_page_1b = first + local_i
                        if real_page_1b not in page_set:
                            img.close()
                            continue
                        if cancel_event and cancel_event.is_set():
                            img.close()
                            break
                        img_path_str = str(
                            Path(tmpdir) / f"page_{real_page_1b:04d}.png"
                        )
                        img.save(img_path_str, "PNG")
                        img.close()
                        saved_pages.append((real_page_1b, img_path_str))
                    del imgs

                    if not saved_pages:
                        continue

                    progress_lock = threading.Lock()
                    page_results: list[DocumentPage] = [None] * len(saved_pages)

                    def _ocr_one(idx_page, page_results=page_results,
                                 progress_lock=progress_lock):
                        idx, (real_page_1b, img_path_str) = idx_page
                        if cancel_event and cancel_event.is_set():
                            return
                        page_doc = DocumentPage(
                            page_number=real_page_1b, source_path=str(path),
                        )
                        _ocr_page(page_doc, img_path_str, ocr_backend, lang,
                                  detect_handwriting)
                        page_results[idx] = page_doc
                        if progress_cb:
                            with progress_lock:
                                nonlocal processed
                                processed += 1
                                progress_cb(processed / total,
                                            f"OCR página {real_page_1b}…")

                    with ThreadPoolExecutor(max_workers=len(saved_pages)) as ex:
                        list(ex.map(_ocr_one, enumerate(saved_pages)))

                    for page_doc in page_results:
                        if page_doc is not None:
                            doc.pages.append(page_doc)

    except Exception as exc:
        logger.error("pdf_scan_reader: error en '%s': %s", pdf_path, exc,
                     exc_info=True)

    if progress_cb:
        progress_cb(1.0, "Listo")

    return doc


def _ocr_page(page_doc: DocumentPage, img_path: str, ocr_backend,
              lang: str, detect_handwriting: bool) -> None:
    """Aplica OCR a una página y añade los bloques al DocumentPage."""
    if detect_handwriting and hasattr(ocr_backend, "extract_text_with_boxes"):
        try:
            boxes = ocr_backend.extract_text_with_boxes(img_path, lang=lang)
        except Exception as exc:
            logger.error("OCR boxes en página %d: %s", page_doc.page_number, exc)
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
            raw_text = ocr_backend.extract_text(img_path, lang=lang)
        except Exception as exc:
            logger.error("OCR error en página %d: %s", page_doc.page_number, exc)
            raw_text = ""
        for line in raw_text.splitlines():
            line = line.strip()
            if line:
                page_doc.blocks.append(
                    TextBlock(text=line, block_type=BlockType.PARAGRAPH)
                )


def _process_images(images, doc: Document, ocr_backend, path: Path,
                    tmpdir: str, lang: str, detect_handwriting: bool,
                    progress_cb, cancel_event) -> None:
    """Procesa una lista ya cargada de imágenes PIL (fallback cuando no hay pdfinfo)."""
    total = len(images)
    for i, img in enumerate(images):
        if cancel_event and cancel_event.is_set():
            break
        if progress_cb:
            progress_cb(i / total, f"OCR página {i + 1}…")
        img_path_str = str(Path(tmpdir) / f"page_{i:04d}.png")
        img.save(img_path_str, "PNG")
        page_doc = DocumentPage(page_number=i + 1, source_path=str(path))
        _ocr_page(page_doc, img_path_str, ocr_backend, lang, detect_handwriting)
        doc.pages.append(page_doc)
        del img

"""
DocumentIngestion — router principal de ingestión de documentos.

Determina el tipo de fuente (PDF, DOCX, imagen, carpeta) y delega al
lector adecuado. Integra la caché de resultados OCR.
"""
from __future__ import annotations

import logging
import time
import threading
from pathlib import Path
from typing import Callable

from core.ocr.document_model import Document
from core.ocr.options import OCROptions

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}


class DocumentIngestion:
    """
    Router de ingestión. Se instancia con un backend OCR y opciones opcionales.
    """

    def __init__(self, ocr_backend, options: OCROptions | None = None):
        self._backend = ocr_backend
        self._options = options or OCROptions()
        self._cache = None
        if self._options.use_cache:
            try:
                from core.ocr.result_cache import OCRResultCache
                self._cache = OCRResultCache()
            except Exception as exc:
                logger.warning("DocumentIngestion: caché no disponible: %s", exc)

    def ingest(
        self,
        source_path: str,
        progress_cb: Callable[[float, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Document:
        """
        Ingesta un documento desde `source_path`.

        Args:
            source_path: Ruta a un PDF, DOCX, imagen o carpeta.
            progress_cb: callback(fracción 0-1, mensaje).
            cancel_event: threading.Event para cancelar procesamiento largo.
        Returns:
            Document estructurado.
        """
        path = Path(source_path)

        # Verificar caché
        _backend_name = getattr(self._backend, "name", "")
        _opts_sig = self._options.signature()
        if self._cache and self._options.use_cache:
            cached = self._cache.get(str(path), _backend_name, _opts_sig)
            if cached is not None:
                logger.debug("DocumentIngestion: caché hit para '%s'", source_path)
                if progress_cb:
                    progress_cb(1.0, "Cargado desde caché")
                return cached

        opts = self._options
        t0 = time.perf_counter()
        doc = self._route(str(path), progress_cb, cancel_event, opts)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        # Enriquecer metadatos del documento
        doc.extraction_time_ms = elapsed_ms
        if doc.source_type not in ("text_pdf", "docx"):
            doc.ocr_backend_used = getattr(self._backend, "name", None)

        # Logging y telemetría
        logger.info(
            "Ingesta: %s → tipo=%s backend=%s páginas=%d bloques=%d tiempo=%dms",
            path.name,
            doc.source_type,
            doc.ocr_backend_used,
            len(doc.pages),
            sum(len(p.blocks) for p in doc.pages),
            elapsed_ms,
        )
        try:
            from core.diagnostics import diagnostics
            diagnostics.log_event("ocr", "ingest", {
                "source_type": doc.source_type,
                "backend": doc.ocr_backend_used,
                "pages": len(doc.pages),
                "ms": elapsed_ms,
            })
        except Exception:
            pass

        # Guardar en caché si no fue cancelado
        if self._cache and self._options.use_cache:
            if cancel_event is None or not cancel_event.is_set():
                self._cache.put(str(path), doc, _backend_name, _opts_sig)

        return doc

    def _route(
        self,
        source_path: str,
        progress_cb: Callable[[float, str], None] | None,
        cancel_event: threading.Event | None,
        opts: OCROptions,
    ) -> Document:
        path = Path(source_path)

        if path.is_dir():
            return self._read_folder(source_path, opts, progress_cb, cancel_event)

        ext = path.suffix.lower()

        if ext == ".pdf":
            return self._read_pdf(source_path, opts, progress_cb, cancel_event)

        if ext == ".docx":
            return self._read_docx(source_path)

        if ext == ".doc":
            from core.ocr.document_model import Document, DocumentPage, TextBlock
            doc = Document(source_path=source_path, source_type="unsupported")
            page = DocumentPage(page_number=1, source_path=source_path)
            page.blocks.append(TextBlock(
                text="El formato .doc (Word 97-2003) no es compatible. "
                     "Convierte el archivo a .docx con LibreOffice o Microsoft Word.",
                block_type="paragraph",
            ))
            doc.pages.append(page)
            return doc

        if ext in _IMAGE_EXTS:
            return self._read_image(source_path, opts, progress_cb)

        # Tipo desconocido — intentar como texto plano
        logger.warning("DocumentIngestion: tipo no reconocido '%s', leyendo como texto", ext)
        return self._read_plain_text(source_path)

    def _read_pdf(
        self,
        pdf_path: str,
        opts: OCROptions,
        progress_cb: Callable | None,
        cancel_event: threading.Event | None,
    ) -> Document:
        from core.ocr.document_readers.pdf_classifier import classify_pdf

        if progress_cb:
            progress_cb(0.02, "Analizando PDF…")

        pdf_type = classify_pdf(pdf_path)
        logger.info("DocumentIngestion: PDF '%s' clasificado como '%s'", pdf_path, pdf_type)

        if progress_cb:
            type_label = {"text": "texto digital", "scan": "escaneado", "mixed": "mixto"}
            progress_cb(0.05, f"PDF {type_label.get(pdf_type, pdf_type)} detectado…")

        if pdf_type == "text":
            from core.ocr.document_readers.pdf_text_reader import read_pdf_text
            return read_pdf_text(
                pdf_path,
                pdf_pages=opts.pdf_pages,
                progress_cb=progress_cb,
            )

        if pdf_type == "scan":
            from core.ocr.document_readers.pdf_scan_reader import read_pdf_scan
            return read_pdf_scan(
                pdf_path,
                ocr_backend=self._backend,
                dpi=opts.pdf_dpi,
                lang=opts.lang,
                pdf_pages=opts.pdf_pages,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
                detect_handwriting=opts.detect_handwriting,
            )

        # mixed
        from core.ocr.document_readers.pdf_mixed_reader import read_pdf_mixed
        return read_pdf_mixed(
            pdf_path,
            ocr_backend=self._backend,
            dpi=opts.pdf_dpi,
            lang=opts.lang,
            pdf_pages=opts.pdf_pages,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    def _read_docx(self, docx_path: str) -> Document:
        from core.ocr.document_readers.docx_reader import read_docx_document
        return read_docx_document(docx_path)

    def _read_image(
        self,
        image_path: str,
        opts: OCROptions,
        progress_cb: Callable | None,
    ) -> Document:
        from core.ocr.document_readers.image_reader import read_image
        return read_image(
            image_path, self._backend,
            lang=opts.lang,
            progress_cb=progress_cb,
            detect_handwriting=opts.detect_handwriting,
        )

    def _read_folder(
        self,
        folder_path: str,
        opts: OCROptions,
        progress_cb: Callable | None,
        cancel_event: threading.Event | None,
    ) -> Document:
        from core.ocr.document_readers.folder_reader import read_folder
        return read_folder(
            folder_path,
            self._backend,
            lang=opts.lang,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    def _read_plain_text(self, path: str) -> Document:
        from core.ocr.document_model import BlockType, DocumentPage, TextBlock
        doc = Document(source_path=path, source_type="plain_text")
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            page = DocumentPage(page_number=1, source_path=path)
            for line in text.splitlines():
                if line.strip():
                    page.blocks.append(TextBlock(text=line.strip(), block_type=BlockType.PARAGRAPH))
            doc.pages.append(page)
        except Exception as exc:
            logger.error("_read_plain_text: '%s': %s", path, exc)
        return doc

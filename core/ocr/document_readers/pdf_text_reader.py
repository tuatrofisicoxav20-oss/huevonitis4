"""
Lector de PDFs con texto seleccionable (pdfplumber).
Detecta encabezados por tamaño de fuente y estructura el resultado
en un Document con TextBlocks tipados.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from core.ocr.document_model import BlockType, Document, DocumentPage, TextBlock

logger = logging.getLogger(__name__)

try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER_OK = True
except ImportError:
    _PDFPLUMBER_OK = False

# Tamaño de fuente mínimo para ser considerado encabezado (heurístico)
_HEADING_SIZE_THRESHOLD = 14.0


def _detect_block_type(char_sizes: list[float]) -> tuple[BlockType, int]:
    """
    Infiere si un bloque es encabezado o párrafo normal basándose en
    el tamaño promedio de sus caracteres.
    Devuelve (BlockType, heading_level).
    """
    if not char_sizes:
        return BlockType.PARAGRAPH, 1
    avg = sum(char_sizes) / len(char_sizes)
    if avg >= _HEADING_SIZE_THRESHOLD + 8:
        return BlockType.HEADING, 1
    if avg >= _HEADING_SIZE_THRESHOLD + 4:
        return BlockType.HEADING, 2
    if avg >= _HEADING_SIZE_THRESHOLD:
        return BlockType.HEADING, 3
    return BlockType.PARAGRAPH, 1


def read_pdf_text(
    pdf_path: str,
    pdf_pages: list[int] | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
) -> Document:
    """
    Lee un PDF con texto seleccionable usando pdfplumber.

    Args:
        pdf_path: Ruta al PDF.
        pdf_pages: Lista de índices (base-0) de páginas a leer. None = todas.
        progress_cb: callback(fracción 0-1, mensaje).
    """
    path = Path(pdf_path)
    doc = Document(source_path=str(path), source_type="text_pdf")

    if not _PDFPLUMBER_OK:
        logger.warning("pdfplumber no disponible; usando fallback de texto plano")
        return doc

    try:
        with _pdfplumber.open(str(path)) as pdf:
            all_pages = pdf.pages
            total = len(all_pages)
            indices = pdf_pages if pdf_pages is not None else list(range(total))

            for i, idx in enumerate(indices):
                if idx < 0 or idx >= total:
                    continue

                page = all_pages[idx]
                if progress_cb:
                    progress_cb(i / len(indices), f"Leyendo página {idx + 1}/{total}…")

                page_doc = DocumentPage(page_number=idx + 1, source_path=str(path))

                # Extraer palabras con metadatos de tamaño para detectar encabezados
                words = page.extract_words(
                    extra_attrs=["size"],
                    keep_blank_chars=False,
                )

                # Agrupa palabras en líneas por proximidad vertical (±5px)
                if not words:
                    raw_text = page.extract_text() or ""
                    for line in raw_text.splitlines():
                        line = line.strip()
                        if line:
                            page_doc.blocks.append(
                                TextBlock(text=line, block_type=BlockType.PARAGRAPH)
                            )
                else:
                    lines: list[list[dict]] = []
                    current_line: list[dict] = []
                    prev_top: float | None = None

                    for w in words:
                        top = w.get("top", 0)
                        if prev_top is None or abs(top - prev_top) <= 5:
                            current_line.append(w)
                        else:
                            if current_line:
                                lines.append(current_line)
                            current_line = [w]
                        prev_top = top
                    if current_line:
                        lines.append(current_line)

                    for line_words in lines:
                        text = " ".join(w["text"] for w in line_words).strip()
                        if not text:
                            continue
                        sizes = [w.get("size", 12) for w in line_words if w.get("size")]
                        avg_size = sum(sizes) / len(sizes) if sizes else None
                        btype, hlevel = _detect_block_type(sizes)
                        # Heurístico: líneas que empiezan con "- " o "• "
                        if text.startswith(("- ", "• ", "* ")):
                            btype = BlockType.LIST_ITEM
                            text = text[2:]
                        page_doc.blocks.append(
                            TextBlock(
                                text=text,
                                block_type=btype,
                                heading_level=hlevel,
                                font_size_hint=avg_size,
                            )
                        )

                doc.pages.append(page_doc)

    except Exception as exc:
        logger.error("pdf_text_reader: error en '%s': %s", pdf_path, exc, exc_info=True)

    if progress_cb:
        progress_cb(1.0, "Listo")

    return doc

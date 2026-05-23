"""
Modelo estructurado de documento para el pipeline de ingestión OCR.

Jerarquía: TextBlock → DocumentPage → Document
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CODE = "code"
    CAPTION = "caption"
    UNKNOWN = "unknown"


@dataclass
class TextBlock:
    text: str
    block_type: BlockType = BlockType.PARAGRAPH
    confidence: float = 1.0
    # Bounding box en píxeles: (x, y, w, h) — None si no aplica
    bbox: tuple[int, int, int, int] | None = None
    # Nivel de encabezado (1-6). Solo aplica cuando block_type == HEADING
    heading_level: int = 1
    # Tamaño de fuente en px si el backend lo provee (pdfplumber, etc.)
    font_size_hint: float | None = None
    # True si el backend detecta escritura a mano; None si no puede determinarlo
    is_handwritten: bool | None = None

    def to_markdown(self) -> str:
        if self.block_type == BlockType.HEADING:
            prefix = "#" * max(1, min(6, self.heading_level))
            return f"{prefix} {self.text}"
        if self.block_type == BlockType.LIST_ITEM:
            return f"- {self.text}"
        if self.block_type == BlockType.CODE:
            return f"```\n{self.text}\n```"
        return self.text


@dataclass
class DocumentPage:
    page_number: int
    blocks: list[TextBlock] = field(default_factory=list)
    # Ruta del archivo de origen de esta página (PDF, imagen, docx…)
    source_path: str = ""
    # Dimensiones en píxeles (0 si no se conocen)
    width: int = 0
    height: int = 0

    def plain_text(self, separator: str = "\n\n") -> str:
        """Texto plano — bloques en el orden en que el lector los produzca."""
        return separator.join(b.text for b in self.blocks)

    def full_text(self) -> str:
        """Alias de plain_text con separador simple (compat con callers anteriores)."""
        return "\n".join(b.text for b in self.blocks)

    def to_markdown(self) -> str:
        return "\n\n".join(b.to_markdown() for b in self.blocks)


@dataclass
class Document:
    """Resultado estructurado de la ingestión de un documento."""
    source_path: str
    # "text_pdf", "scan_pdf", "mixed_pdf", "docx", "image", "folder"
    source_type: str = "unknown"
    pages: list[DocumentPage] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    # None cuando no se usó OCR (e.g. PDF con texto, DOCX)
    ocr_backend_used: str | None = None
    extraction_time_ms: int = 0

    def plain_text(self) -> str:
        """Texto plano de todas las páginas separadas por línea doble."""
        return "\n\n".join(p.plain_text() for p in self.pages)

    def full_text(self) -> str:
        """Alias de plain_text (compat con callers anteriores)."""
        return "\n\n".join(p.full_text() for p in self.pages)

    def to_markdown(self) -> str:
        parts = []
        for page in self.pages:
            md = page.to_markdown()
            if md.strip():
                parts.append(md)
        return "\n\n---\n\n".join(parts)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def word_count(self) -> int:
        return sum(len(b.text.split()) for p in self.pages for b in p.blocks)

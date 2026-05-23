"""
Opciones de ingestión de documentos OCR.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OCROptions:
    lang: str = "spa"
    detect_handwriting: bool = False
    preserve_layout: bool = True
    pdf_dpi: int = 200
    # None = todas las páginas; lista de índices base-0 para selección parcial
    pdf_pages: list[int] | None = None
    # Número de páginas a procesar en paralelo (1 = secuencial)
    parallel_pages: int = 1
    # Si True, usa la caché en disco para evitar re-procesar archivos iguales
    use_cache: bool = True

    def signature(self) -> str:
        """Cadena determinística de los campos que afectan el resultado OCR.
        NO incluye use_cache ni parallel_pages (no afectan el contenido extraído)."""
        pages_str = str(sorted(self.pdf_pages)) if self.pdf_pages is not None else "all"
        return "|".join([
            self.lang,
            str(self.pdf_dpi),
            str(int(self.detect_handwriting)),
            pages_str,
            str(int(self.preserve_layout)),
        ])

"""
Interfaz base para etiquetadores de glifos.
"""
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class GlyphLabeler(ABC):
    """
    Recibe un crop de glifo (imagen PIL RGBA/RGB) y devuelve el carácter
    más probable. Útil para auto-clasificar el banco de glifos.
    """

    name: str = "base"
    available: bool = False

    @abstractmethod
    def label(self, glyph_image: "Image.Image") -> tuple[str, float]:
        """Devuelve (texto_completo_predicho, confianza_0_a_1)."""
        ...

    def label_batch(self, glyph_images: list) -> list[tuple[str, float]]:
        """Etiqueta una lista de imágenes.

        Implementación por defecto: itera label() uno por uno.
        Subclases ML deben sobrescribir con inferencia batched real.
        """
        return [self.label(img) for img in glyph_images]

    def install_hint(self) -> str:
        return f"Etiquetador '{self.name}' no disponible."

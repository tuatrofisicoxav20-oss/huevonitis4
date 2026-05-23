"""
Interfaz base para todos los backends de OCR de Huevonitis.
"""
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class OCRBackend(ABC):
    """Backend de OCR intercambiable. Subclases implementan la lógica concreta."""

    name: str = "base"
    available: bool = False

    @abstractmethod
    def extract_text(self, image_path: str, lang: str = "spa") -> str:
        """Extrae texto de una imagen y lo devuelve como string."""
        ...

    @abstractmethod
    def extract_text_with_boxes(
        self, image_path: str, lang: str = "spa"
    ) -> list[dict]:
        """Devuelve [{"text": str, "bbox": (x,y,w,h), "conf": float}, ...]"""
        ...

    def install_hint(self) -> str:
        """Mensaje de ayuda para instalar este backend."""
        return f"Backend '{self.name}' no disponible."

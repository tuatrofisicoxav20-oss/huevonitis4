"""
Interfaz base para detectores de glifos a nivel de carácter.
"""
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class GlyphDetector(ABC):
    """Detector de bounding boxes a nivel CARÁCTER, no a nivel palabra."""

    name: str = "base"
    available: bool = False

    @abstractmethod
    def detect(self, image_bgr: "np.ndarray") -> list:
        """
        Detecta caracteres en una imagen BGR.

        Parámetro:
            image_bgr: imagen BGR (numpy array, como la devuelve cv2.imread)

        Retorna:
            Lista de BBox ordenada de izquierda a derecha, arriba a abajo.
        """
        ...

    def install_hint(self) -> str:
        return f"Detector '{self.name}' no disponible."

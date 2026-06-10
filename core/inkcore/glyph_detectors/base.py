"""
Interfaz base para detectores de glifos a nivel de carácter.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


class BBox:
    """Bounding box a nivel carácter (x, y, w, h en píxeles).

    Reubicado desde ``extractor.py`` en la limpieza v4.2 (el extractor viejo se
    eliminó; este es el tipo geométrico que producen los detectores de glifos).
    """

    __slots__ = ("h", "w", "x", "y")

    def __init__(self, x: int, y: int, w: int, h: int):
        self.x = int(x)
        self.y = int(y)
        self.w = int(max(1, w))
        self.h = int(max(1, h))

    @property
    def x2(self) -> int: return self.x + self.w
    @property
    def y2(self) -> int: return self.y + self.h

    def area(self) -> int: return self.w * self.h
    def cx(self) -> float: return self.x + self.w / 2
    def cy(self) -> float: return self.y + self.h / 2


class GlyphDetector(ABC):
    """Detector de bounding boxes a nivel CARÁCTER, no a nivel palabra."""

    name: str = "base"
    available: bool = False

    @abstractmethod
    def detect(self, image_bgr: np.ndarray) -> list:
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

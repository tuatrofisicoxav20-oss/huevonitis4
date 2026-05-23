"""
Backend de OCR usando EasyOCR. Opcional — fallback ligero.
"""
import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)

try:
    import easyocr as _easyocr
    _EASYOCR_OK = True
except ImportError:
    _EASYOCR_OK = False

from core.ocr.base import OCRBackend


class EasyOCRBackend(OCRBackend):
    """Backend EasyOCR — ligero, buen soporte español."""

    name = "easyocr"
    available = _EASYOCR_OK

    def __init__(self):
        self._reader = None  # lazy

    def _get_reader(self):
        if self._reader is None:
            if not _EASYOCR_OK:
                return None
            models_dir = config.MODELS_DIR
            models_dir.mkdir(parents=True, exist_ok=True)
            from core.inkcore.model_cache import ModelCache
            self._reader = ModelCache.get(
                "easyocr_es",
                lambda: _easyocr.Reader(
                    ["es"],
                    gpu=False,
                    model_storage_directory=str(models_dir),
                ),
            )
        return self._reader

    def extract_text(self, image_path: str, lang: str = "spa") -> str:
        if not _EASYOCR_OK:
            return (
                "EasyOCR no instalado. Instalar con:\n"
                "pip install easyocr"
            )
        path = Path(image_path)
        if not path.exists():
            return f"Error: archivo no encontrado: {image_path}"
        try:
            reader = self._get_reader()
            results = reader.readtext(str(path))
            lines = [text for _, text, _ in results]
            return "\n".join(lines).strip()
        except Exception as e:
            logger.error(f"EasyOCR error: {e}")
            return f"Error en EasyOCR: {e}"

    def extract_text_with_boxes(
        self, image_path: str, lang: str = "spa"
    ) -> list[dict]:
        if not _EASYOCR_OK:
            return []
        path = Path(image_path)
        if not path.exists():
            return []
        try:
            reader = self._get_reader()
            results = reader.readtext(str(path))
            boxes = []
            for pts, text, conf in results:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                x = int(min(xs))
                y = int(min(ys))
                w = int(max(xs) - x)
                h = int(max(ys) - y)
                boxes.append({
                    "text": text,
                    "bbox": (x, y, w, h),
                    "conf": float(conf),
                })
            return boxes
        except Exception as e:
            logger.error(f"EasyOCR boxes error: {e}")
            return []

    def install_hint(self) -> str:
        return (
            "EasyOCR no instalado.\n"
            "pip install easyocr"
        )

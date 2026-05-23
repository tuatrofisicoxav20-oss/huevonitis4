"""
Backend de OCR usando docTR (python-doctr). Opcional.
"""
import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)

try:
    from doctr.io import DocumentFile as _DocFile
    from doctr.models import ocr_predictor as _ocr_predictor
    _DOCTR_OK = True
except ImportError:
    _DOCTR_OK = False

from core.ocr.base import OCRBackend


class DoctrBackend(OCRBackend):
    """Backend docTR — bueno para texto impreso; handwriting mejorable."""

    name = "doctr"
    available = _DOCTR_OK

    def __init__(self):
        self._model = None  # lazy

    def _get_model(self):
        if self._model is None:
            if not _DOCTR_OK:
                return None
            config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
            from core.inkcore.model_cache import ModelCache
            self._model = ModelCache.get(
                "doctr_db_crnn",
                lambda: _ocr_predictor(pretrained=True),
            )
        return self._model

    def extract_text(self, image_path: str, lang: str = "spa") -> str:
        if not _DOCTR_OK:
            return (
                "docTR no instalado. Instalar con:\n"
                "pip install python-doctr[torch]"
            )
        path = Path(image_path)
        if not path.exists():
            return f"Error: archivo no encontrado: {image_path}"
        try:
            model = self._get_model()
            doc = _DocFile.from_images(str(path))
            result = model(doc)
            lines = []
            for page in result.pages:
                for block in page.blocks:
                    for line in block.lines:
                        words = [w.value for w in line.words]
                        lines.append(" ".join(words))
            return "\n".join(lines).strip()
        except Exception as e:
            logger.error(f"docTR error: {e}")
            return f"Error en docTR: {e}"

    def extract_text_with_boxes(
        self, image_path: str, lang: str = "spa"
    ) -> list[dict]:
        if not _DOCTR_OK:
            return []
        path = Path(image_path)
        if not path.exists():
            return []
        try:
            from PIL import Image as PILImage
            model = self._get_model()
            doc = _DocFile.from_images(str(path))
            result = model(doc)
            img = PILImage.open(path)
            img_w, img_h = img.size
            boxes = []
            for page in result.pages:
                for block in page.blocks:
                    for line in block.lines:
                        for word in line.words:
                            text = word.value
                            conf = float(word.confidence)
                            # docTR usa coordenadas relativas [0,1]
                            (x0, y0), (x1, y1) = word.geometry
                            x = int(x0 * img_w)
                            y = int(y0 * img_h)
                            w = int((x1 - x0) * img_w)
                            h = int((y1 - y0) * img_h)
                            boxes.append({
                                "text": text,
                                "bbox": (x, y, w, h),
                                "conf": conf,
                            })
            return boxes
        except Exception as e:
            logger.error(f"docTR boxes error: {e}")
            return []

    def install_hint(self) -> str:
        return (
            "docTR no instalado.\n"
            "pip install python-doctr[torch]"
        )

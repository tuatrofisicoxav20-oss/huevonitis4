"""
Backend de OCR usando PaddleOCR PP-OCRv5. Opcional.
Compatible con PaddleOCR 2.x (use_gpu, show_log) y 3.x (device).
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from paddleocr import PaddleOCR as _PaddleOCR
    _PADDLE_OK = True
except ImportError:
    _PADDLE_OK = False

from core.ocr.base import OCRBackend


def _paddle_kwargs(lang: str = "es") -> dict:
    """Construye kwargs compatibles con la versión de PaddleOCR instalada."""
    try:
        import paddleocr
        ver = tuple(int(x) for x in paddleocr.__version__.split(".")[:2])
        if ver >= (3, 0):
            return {"lang": lang, "device": "cpu"}
        return {"lang": lang, "use_gpu": False, "show_log": False}
    except Exception:
        return {"lang": lang, "use_gpu": False, "show_log": False}


class PaddleOCRBackend(OCRBackend):
    """Backend PaddleOCR con soporte nativo de español (PP-OCRv5)."""

    name = "paddleocr"
    available = _PADDLE_OK

    def __init__(self):
        self._ocr = None  # lazy: primera llamada descarga el modelo

    def _get_ocr(self):
        if self._ocr is None:
            if not _PADDLE_OK:
                return None
            from core.inkcore.model_cache import ModelCache
            kwargs = _paddle_kwargs("es")
            self._ocr = ModelCache.get(
                "paddleocr_full_es",
                lambda: _PaddleOCR(use_angle_cls=True, **kwargs),
            )
        return self._ocr

    def _call_ocr(self, path_or_arr, cls: bool = True):
        """Llama al OCR intentando primero la API 3.0, luego 2.x."""
        ocr = self._get_ocr()
        try:
            return ocr.predict(path_or_arr)
        except (AttributeError, TypeError):
            return ocr.ocr(path_or_arr, cls=cls)

    def extract_text(self, image_path: str, lang: str = "spa") -> str:
        if not _PADDLE_OK:
            return (
                "PaddleOCR no instalado. Instalar con:\n"
                "pip install paddleocr paddlepaddle"
            )
        path = Path(image_path)
        if not path.exists():
            return f"Error: archivo no encontrado: {image_path}"
        try:
            result = self._call_ocr(str(path))
            if not result or not result[0]:
                return ""
            lines = []
            for line in result[0]:
                if line and len(line) >= 2:
                    lines.append(str(line[1][0]))
            return "\n".join(lines).strip()
        except Exception as e:
            logger.error(f"PaddleOCR error: {e}")
            return f"Error en PaddleOCR: {e}"

    def extract_text_with_boxes(
        self, image_path: str, lang: str = "spa"
    ) -> list[dict]:
        if not _PADDLE_OK:
            return []
        path = Path(image_path)
        if not path.exists():
            return []
        try:
            result = self._call_ocr(str(path))
            if not result or not result[0]:
                return []
            boxes = []
            for line in result[0]:
                if not line or len(line) < 2:
                    continue
                pts = line[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                text = str(line[1][0])
                conf = float(line[1][1])
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                x = int(min(xs))
                y = int(min(ys))
                w = int(max(xs) - x)
                h = int(max(ys) - y)
                aspect = w / h if h > 0 else 1.0
                is_hw = conf < 0.85 and (aspect > 10.0 or aspect < 0.15 or conf < 0.65)
                boxes.append({
                    "text": text, "bbox": (x, y, w, h),
                    "conf": conf, "is_handwritten": is_hw,
                })
            return boxes
        except Exception as e:
            logger.error(f"PaddleOCR boxes error: {e}")
            return []

    def install_hint(self) -> str:
        return (
            "PaddleOCR no instalado.\n"
            "pip install paddleocr paddlepaddle\n"
            "(CPU; para GPU: pip install paddlepaddle-gpu)"
        )

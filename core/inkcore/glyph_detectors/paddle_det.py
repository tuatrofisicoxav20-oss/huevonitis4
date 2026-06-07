"""
Detector usando solo el módulo de detección de PaddleOCR (sin reconocimiento). Opcional.
Comparte la instancia cargada con PaddleOCRBackend via ModelCache cuando es posible.
"""
import logging

logger = logging.getLogger(__name__)

try:
    from paddleocr import PaddleOCR as _PaddleOCR
    _PADDLE_OK = True
except ImportError:
    _PADDLE_OK = False

try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False

from core.inkcore.glyph_detectors.base import GlyphDetector


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


class PaddleDetector(GlyphDetector):
    """Solo detección PP-OCRv5 — más rápido que el backend completo.

    Estrategia de carga:
    1. Si `paddleocr_full_es` ya está en ModelCache (cargado por PaddleOCRBackend),
       lo reutiliza directamente (ahorra ~500 MB de RAM).
    2. Si no, carga `paddleocr_det_es` (detección sin reconocimiento).
    """

    name = "paddle_det"
    available = _PADDLE_OK and _NP_OK

    def __init__(self):
        self._ocr = None  # lazy

    def _get_ocr(self):
        if self._ocr is not None:
            return self._ocr
        if not _PADDLE_OK:
            return None
        from core.inkcore.model_cache import ModelCache

        # Intentar reutilizar el modelo completo si ya está cargado
        full = ModelCache.peek("paddleocr_full_es")
        if full is not None:
            self._ocr = full
            logger.info("PaddleDetector: reutilizando paddleocr_full_es del ModelCache")
            return self._ocr

        # Cargar solo el detector
        kwargs = _paddle_kwargs("es")
        try:
            import paddleocr
            ver = tuple(int(x) for x in paddleocr.__version__.split(".")[:2])
            if ver >= (3, 0):
                # En 3.0 la API det-only difiere; usar modelo completo con kwargs básicos
                # y luego ignorar el resultado de rec (fallback compatible)
                def loader():
                    return _PaddleOCR(**kwargs)
            else:
                det_kwargs = {**kwargs, "det": True, "rec": False}
                def loader():
                    return _PaddleOCR(**det_kwargs)
        except Exception:
            det_kwargs = {**kwargs, "det": True, "rec": False}
            def loader():
                return _PaddleOCR(**det_kwargs)

        self._ocr = ModelCache.get("paddleocr_det_es", loader)
        return self._ocr

    def detect(self, image_bgr: "np.ndarray") -> list:
        if not _PADDLE_OK or not _NP_OK:
            return []
        try:
            from core.inkcore.extractor import BBox
            ocr = self._get_ocr()
            if ocr is None:
                return []
            try:
                # PaddleOCR 3.0+ predict() API
                result = ocr.predict(image_bgr)
                if result is None:
                    result = [[]]
            except (AttributeError, TypeError):
                # PaddleOCR 2.x ocr() API
                result = ocr.ocr(image_bgr, cls=False)

            boxes = []
            raw = result[0] if result else []
            if raw:
                for line in raw:
                    if not line:
                        continue
                    # Formato 2.x: [[pts], [text, conf]]  3.x varía
                    pts_raw = line[0] if isinstance(line[0], (list, np.ndarray)) else line
                    try:
                        pts = np.array(pts_raw, dtype=np.float32)
                        if pts.ndim == 1:
                            continue
                        x = int(np.min(pts[:, 0]))
                        y = int(np.min(pts[:, 1]))
                        w = int(np.max(pts[:, 0]) - x)
                        h = int(np.max(pts[:, 1]) - y)
                        if w > 0 and h > 0:
                            boxes.append(BBox(x, y, w, h))
                    except Exception:
                        continue
            boxes.sort(key=lambda b: (b.y, b.x))
            return boxes
        except Exception as e:
            logger.error(f"PaddleDetector error: {e}")
            return []

    def install_hint(self) -> str:
        return (
            "PaddleDetector no instalado.\n"
            "pip install paddleocr paddlepaddle"
        )

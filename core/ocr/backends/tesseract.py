"""
Backend de OCR usando Tesseract (default). Refactor del engine.py original.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

import contextlib  # noqa: E402

from core.ocr.base import OCRBackend  # noqa: E402


class TesseractBackend(OCRBackend):
    """Backend Tesseract — sin dependencias extras, default de la app."""

    name = "tesseract"
    available = _TESSERACT_OK

    def __init__(self):
        self._apply_cmd()

    def _apply_cmd(self):
        from core.ocr._tesseract_setup import apply_tesseract_cmd
        apply_tesseract_cmd()

    def _preprocess(self, image_path: str):
        """CLAHE + Otsu + Adaptativo (idéntico al engine.py original)."""
        if not _CV2_OK:
            return None
        img = cv2.imread(str(image_path))
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        return cv2.bitwise_and(otsu, adaptive)

    def extract_text(self, image_path: str, lang: str = "spa") -> str:
        self._apply_cmd()
        # En fallo se devuelve "" (no un mensaje de error): el texto de
        # extract_text se agrega TAL CUAL al documento (TextBlocks → resumen →
        # flashcards/quiz), así que un string de error se convertiría en contenido
        # del documento. Mejor cadena vacía + log que envenenar el material.
        if not _TESSERACT_OK:
            logger.error(
                "Tesseract OCR: pytesseract no disponible (pip install pytesseract "
                "+ paquete tesseract del sistema)"
            )
            return ""
        path = Path(image_path)
        if not path.exists():
            logger.error("Tesseract OCR: archivo no encontrado: %s", image_path)
            return ""
        try:
            if _CV2_OK:
                processed = self._preprocess(image_path)
                if processed is not None:
                    from PIL import Image as PILImage
                    pil_img = PILImage.fromarray(processed)
                    return pytesseract.image_to_string(
                        pil_img, lang=lang, config="--oem 3 --psm 6"
                    ).strip()
            with Image.open(image_path) as img:
                return pytesseract.image_to_string(
                    img, lang=lang, config="--oem 3 --psm 6"
                ).strip()
        except Exception as e:
            logger.error(f"Tesseract OCR error: {e}")
            return ""

    def extract_text_with_boxes(
        self, image_path: str, lang: str = "spa"
    ) -> list[dict]:
        self._apply_cmd()
        if not _TESSERACT_OK:
            return []
        path = Path(image_path)
        if not path.exists():
            return []
        try:
            from PIL import Image as PILImage
            if _CV2_OK:
                processed = self._preprocess(image_path)
                pil_img = (
                    PILImage.fromarray(processed)
                    if processed is not None
                    else PILImage.open(image_path)
                )
            else:
                pil_img = PILImage.open(image_path)
            try:
                data = pytesseract.image_to_data(
                    pil_img, lang=lang, config="--oem 3 --psm 6",
                    output_type=pytesseract.Output.DICT,
                )
            finally:
                # PILImage.open mantiene el fd abierto; fromarray no, pero close()
                # es seguro en ambos casos.
                with contextlib.suppress(Exception):
                    pil_img.close()
            results = []
            for i in range(len(data["text"])):
                text = str(data["text"][i]).strip()
                if not text:
                    continue
                conf = float(data["conf"][i])
                if conf < 0:
                    continue
                results.append({
                    "text": text,
                    "bbox": (
                        int(data["left"][i]), int(data["top"][i]),
                        int(data["width"][i]), int(data["height"][i]),
                    ),
                    "conf": conf / 100.0,
                })
            return results
        except Exception as e:
            logger.error(f"Tesseract boxes error: {e}")
            return []

    def install_hint(self) -> str:
        return (
            "Tesseract no instalado.\n"
            "pip install pytesseract\n"
            "sudo dnf install tesseract tesseract-langpack-spa"
        )

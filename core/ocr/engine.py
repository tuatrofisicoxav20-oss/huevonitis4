import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False

try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False

try:
    import docx
    DOCX_OK = True
except ImportError:
    DOCX_OK = False


class OCREngine:
    def preprocess(self, image_path: str):
        if not CV2_OK:
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
        combined = cv2.bitwise_and(otsu, adaptive)
        return combined

    def extract_text(self, image_path: str) -> str:
        if not TESSERACT_OK:
            return (
                "Error: pytesseract no está disponible.\n"
                "Instalar: pip install pytesseract\n"
                "También necesitas Tesseract: sudo dnf install tesseract tesseract-langpack-spa"
            )
        path = Path(image_path)
        if not path.exists():
            return f"Error: archivo no encontrado: {image_path}"
        try:
            if CV2_OK:
                processed = self.preprocess(image_path)
                if processed is not None:
                    from PIL import Image as PILImage
                    pil_img = PILImage.fromarray(processed)
                    text = pytesseract.image_to_string(pil_img, lang="spa", config="--oem 3 --psm 6")
                    return text.strip()
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang="spa", config="--oem 3 --psm 6")
            return text.strip()
        except Exception as e:
            logger.error(f"OCR error: {e}")
            return f"Error en OCR: {e}"

    def read_docx(self, docx_path: str) -> str:
        if not DOCX_OK:
            return "Error: python-docx no disponible. Instalar: pip install python-docx"
        try:
            doc = docx.Document(docx_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except Exception as e:
            logger.error(f"DOCX error: {e}")
            return f"Error leyendo Word: {e}"

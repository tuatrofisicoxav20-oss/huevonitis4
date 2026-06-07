"""
Etiquetador de glifos usando Tesseract (PSM 10 — carácter único).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

try:
    import pytesseract
    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

from core.inkcore.glyph_labelers.base import GlyphLabeler  # noqa: E402


class TesseractLabeler(GlyphLabeler):
    """Etiqueta un glifo usando Tesseract con PSM 10 (un solo carácter)."""

    name = "tesseract_labeler"
    available = _TESSERACT_OK

    def label(self, glyph_image: Image.Image) -> tuple[str, float]:
        if not _TESSERACT_OK:
            return ("?", 0.0)
        from core.ocr._tesseract_setup import apply_tesseract_cmd
        apply_tesseract_cmd()
        try:
            data = pytesseract.image_to_data(
                glyph_image, lang="spa",
                config="--oem 3 --psm 10",
                output_type=pytesseract.Output.DICT,
            )
            best_text = ""
            best_conf = 0.0
            for i, text in enumerate(data["text"]):
                text = str(text).strip()
                if not text:
                    continue
                raw_conf = float(data["conf"][i])
                if raw_conf < 0:
                    continue
                conf = raw_conf / 100.0
                if conf > best_conf:
                    best_conf = conf
                    best_text = text
            if not best_text:
                return ("?", 0.0)
            return (best_text, best_conf)
        except Exception as e:
            logger.error(f"TesseractLabeler error: {e}")
            return ("?", 0.0)

    def install_hint(self) -> str:
        return (
            "TesseractLabeler requiere pytesseract (ya incluido).\n"
            "sudo dnf install tesseract tesseract-langpack-spa"
        )

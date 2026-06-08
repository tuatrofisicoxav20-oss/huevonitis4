"""Backend de OCR para texto MANUSCRITO usando TrOCR (Microsoft).

Es el primer eslabón del flujo "pasar en limpio": foto de apuntes → texto. TrOCR
rinde mejor por LÍNEA que sobre la página entera, así que acá se: (1) corrige la
orientación por contenido (las fotos de WhatsApp pierden el EXIF), (2) endereza y
normaliza iluminación/contraste reutilizando ImagePreprocessor, (3) segmenta en
líneas por proyección horizontal, y (4) corre TrOCR por línea devolviendo texto +
confianza.

NO pretende ser perfecto: el OCR manuscrito comete errores. El flujo SIEMPRE pasa
por revisión humana (Fase 0.6); la meta es un buen borrador, no transcripción
impecable. La confianza por línea sirve para que la UI resalte lo dudoso.
"""
import logging

import config

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import torch
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    _TROCR_OK = True
except ImportError:
    _TROCR_OK = False

try:
    import cv2
    _CV_OK = True
except ImportError:
    _CV_OK = False

from core.ocr.base import OCRBackend  # noqa: E402

_DEFAULT_MODEL = "microsoft/trocr-base-handwritten"


class TrOCRBackend(OCRBackend):
    """OCR manuscrito por líneas con TrOCR. Degradación elegante si falta torch."""

    name = "trocr"
    available = _TROCR_OK and _CV_OK

    def __init__(self):
        self._processor = None
        self._model = None
        self.model_name = getattr(config, "TROCR_MODEL", _DEFAULT_MODEL)

    # ── carga perezosa del modelo (cacheada) ──────────────────────
    def _load(self):
        if self._model is not None:
            return
        cache_dir = str(getattr(config, "OCR_CACHE_DIR", config.MODELS_DIR))
        from core.inkcore.model_cache import ModelCache

        def _loader():
            logger.info("Cargando TrOCR '%s' (la primera vez descarga el modelo)…", self.model_name)
            proc = TrOCRProcessor.from_pretrained(self.model_name, cache_dir=cache_dir)
            mdl = VisionEncoderDecoderModel.from_pretrained(self.model_name, cache_dir=cache_dir)
            mdl.eval()
            return proc, mdl

        self._processor, self._model = ModelCache.get(f"trocr_ocr_{self.model_name}", _loader)

    # ── preproceso de la foto ─────────────────────────────────────
    @staticmethod
    def _preprocess(image_path: str):
        """Devuelve (gray_limpia uint8, rgb_para_recortes uint8) ya orientada/enderezada."""
        from core.inkcore.extractor_preprocess import (
            ImagePreprocessor,
            imread_oriented,
            orient_by_content,
        )
        bgr = imread_oriented(image_path)
        if bgr is None:
            return None, None
        bgr = orient_by_content(bgr)
        pre = ImagePreprocessor()
        try:
            bgr, _ang = pre.deskew(bgr)
        except Exception as exc:
            logger.debug("deskew falló (%s); sigo sin enderezar", exc)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        try:
            gray = ImagePreprocessor.normalize_illumination(gray)
            gray = ImagePreprocessor.enhance_contrast(gray)
        except Exception as exc:
            logger.debug("normalización falló (%s); uso gris crudo", exc)
        if gray.dtype != np.uint8:
            gray = np.clip(gray, 0, 255).astype(np.uint8)
        rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        return gray, rgb

    @staticmethod
    def _segment_lines(gray) -> list:
        """Bandas (y0, y1) de líneas de texto por proyección horizontal de tinta."""
        # Binariza: tinta oscura → 1. Otsu invertido.
        _, binv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        row_ink = (binv > 0).sum(axis=1).astype(np.float32)
        h, w = gray.shape
        thr = max(3.0, w * 0.012)  # una línea necesita algo de tinta a lo ancho
        on = row_ink > thr
        bands = []
        y = 0
        while y < h:
            if on[y]:
                y0 = y
                while y < h and on[y]:
                    y += 1
                bands.append((y0, y))
            else:
                y += 1
        # Fusiona bandas muy cercanas (gaps menores a ~0.6 de la altura media).
        if not bands:
            return []
        heights = [b - a for a, b in bands]
        med_h = sorted(heights)[len(heights) // 2]
        merged = [list(bands[0])]
        for a, b in bands[1:]:
            if a - merged[-1][1] < med_h * 0.6:
                merged[-1][1] = b
            else:
                merged.append([a, b])
        # Descarta bandas demasiado finas (ruido) y agrega padding vertical.
        out = []
        for a, b in merged:
            if (b - a) < max(8, med_h * 0.4):
                continue
            pad = int((b - a) * 0.18)
            out.append((max(0, a - pad), min(h, b + pad)))
        return out

    # ── inferencia ────────────────────────────────────────────────
    def _read_line(self, rgb_line) -> tuple[str, float]:
        from PIL import Image
        pil = Image.fromarray(rgb_line)
        pv = self._processor(images=pil, return_tensors="pt").pixel_values
        with torch.no_grad():
            out = self._model.generate(
                pv, max_new_tokens=96, num_beams=2,
                output_scores=True, return_dict_in_generate=True,
            )
        text = self._processor.batch_decode(out.sequences, skip_special_tokens=True)[0].strip()
        conf = 0.0
        ss = getattr(out, "sequences_scores", None)
        if ss is not None and len(ss) > 0:
            conf = float(torch.exp(ss[0]).clamp(0, 1))  # log-prob normalizada → prob
        return text, round(conf, 3)

    def extract_text(self, image_path: str, lang: str = "spa") -> str:
        return "\n".join(d["text"] for d in self.extract_text_with_boxes(image_path, lang) if d["text"])

    def extract_text_with_boxes(self, image_path: str, lang: str = "spa") -> list[dict]:
        if not self.available:
            logger.warning("TrOCRBackend no disponible (falta torch/transformers/cv2)")
            return []
        gray, rgb = self._preprocess(image_path)
        if gray is None:
            return []
        self._load()
        _h, w = gray.shape
        results = []
        for (y0, y1) in self._segment_lines(gray):
            # Recorte horizontal a la extensión real de tinta de la línea: el
            # espacio en blanco sobrante hace que TrOCR ALUCINE (suele inventar
            # números o repetir al final). Recortar al bbox lo evita en gran parte.
            band = gray[y0:y1, :]
            _, bandbin = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            cols = np.where((bandbin > 0).sum(axis=0) > 0)[0]
            if len(cols) == 0:
                continue
            x0 = max(0, int(cols[0]) - 6)
            x1 = min(w, int(cols[-1]) + 6)
            line = rgb[y0:y1, x0:x1]
            try:
                text, conf = self._read_line(line)
            except Exception as exc:
                logger.debug("TrOCR falló en una línea (%s)", exc)
                continue
            if text:
                results.append({"text": text, "bbox": (x0, y0, x1 - x0, y1 - y0), "conf": conf})
        return results

    def install_hint(self) -> str:
        return "Instalá 'transformers' + 'torch' + 'opencv-python' para OCR manuscrito (TrOCR)."

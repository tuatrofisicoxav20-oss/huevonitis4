"""
auto_text: predicción de texto desde una imagen completa.

Estrategia: probar TrOCR sobre la imagen entera (mejor que single-char) y
caer a Tesseract PSM 6 si TrOCR no está disponible. Devuelve el texto crudo
que el extractor legacy luego usa como `reference_text` para alinear cada
bbox a su carácter — mucho más preciso que clasificar glifos uno a uno.

Cache: el resultado se memoriza por (path, mtime, size) para evitar re-OCR
si el usuario re-procesa la misma imagen sin modificarla. Ahorra ~2-12s
por re-extracción.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache global de OCR: {(path, mtime_ns, size): (text, source, conf)}
_OCR_CACHE: dict[tuple, tuple[str, str, float]] = {}
_OCR_CACHE_LOCK = threading.Lock()
_OCR_CACHE_MAX = 64  # imágenes; FIFO simple


def _cache_key(path: str) -> tuple | None:
    try:
        st = Path(path).stat()
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def predict_text_from_image(image_path: str) -> tuple[str, str, float]:
    """Devuelve (texto, fuente, confianza).

    Cachea por (path, mtime, size) para evitar re-OCR.
    """
    if not Path(image_path).exists():
        return "", "", 0.0

    key = _cache_key(image_path)
    if key is not None:
        with _OCR_CACHE_LOCK:
            cached = _OCR_CACHE.get(key)
        if cached is not None:
            logger.debug("predict_text cache hit: %s", Path(image_path).name)
            return cached

    # 1) TrOCR — entrenado en handwriting; mucho mejor que tesseract single-char.
    text, conf = _try_trocr(image_path)
    if text:
        result = (text, "trocr", conf)
    else:
        # 2) Tesseract con PSM 6 (paragraph): mejor que PSM 10 para texto continuo.
        text, conf = _try_tesseract(image_path)
        if text:
            result = (text, "tesseract", conf)
        else:
            result = ("", "", 0.0)

    if key is not None and result[0]:
        with _OCR_CACHE_LOCK:
            if len(_OCR_CACHE) >= _OCR_CACHE_MAX:
                _OCR_CACHE.pop(next(iter(_OCR_CACHE)))
            _OCR_CACHE[key] = result
    return result


def preload_trocr() -> bool:
    """Carga TrOCR en memoria (idempotente vía ModelCache).

    Pensado para ejecutarse en un thread daemon al arrancar la app: cuando
    el usuario pulse 'Procesar y extraer' el modelo ya estará caliente.
    Devuelve True si el modelo se cargó (o ya estaba), False si TrOCR no
    está disponible.
    """
    try:
        import torch
        from transformers import (
            TrOCRProcessor, VisionEncoderDecoderModel,
        )
        import config
        from core.inkcore.model_cache import ModelCache
    except ImportError:
        return False

    # Usa todos los cores disponibles para inferencia (TrOCR base-handwritten
    # se beneficia ~30-40 % de tener 12 hilos en lugar de 8 default).
    try:
        import os
        n = max(1, (os.cpu_count() or 4))
        torch.set_num_threads(n)
    except Exception:
        pass

    cache_dir = str(config.MODELS_DIR / "trocr")
    model_name = "microsoft/trocr-base-handwritten"

    def _loader():
        logger.info("Pre-loading TrOCR en background…")
        proc = TrOCRProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        mdl = VisionEncoderDecoderModel.from_pretrained(model_name, cache_dir=cache_dir)
        mdl.eval()
        # Warmup: una pasada con tensor dummy para que PyTorch compile kernels
        # antes de que el usuario haga el primer click. Quita ~1.5s de latencia
        # percibida en la primera inferencia real.
        try:
            with torch.no_grad():
                dummy = torch.zeros((1, 3, 384, 384), dtype=torch.float32)
                mdl.generate(dummy, max_new_tokens=2, num_beams=1, do_sample=False)
        except Exception as exc:
            logger.debug("TrOCR warmup ignorado: %s", exc)
        return proc, mdl

    try:
        ModelCache.get(f"trocr_{model_name}", _loader)
        logger.info("TrOCR ya en memoria.")
        return True
    except Exception as exc:
        logger.warning("preload_trocr falló: %s", exc)
        return False


def _clean_predicted_text(text: str) -> str:
    """Normaliza el texto predicho para usarlo como ref del extractor."""
    text = text.strip()
    # Quitar puntuación al final que TrOCR/Tesseract suelen alucinar
    text = re.sub(r'[.,;:!?]+\s*$', '', text)
    # Colapsar espacios múltiples (mantener líneas)
    lines = [re.sub(r'\s+', ' ', ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def _try_trocr(image_path: str) -> tuple[str, float]:
    try:
        import torch
        import torch.nn.functional as F
        from PIL import Image
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    except ImportError:
        return "", 0.0

    try:
        import config
        from core.inkcore.model_cache import ModelCache

        cache_dir = str(config.MODELS_DIR / "trocr")
        model_name = "microsoft/trocr-base-handwritten"

        def _loader():
            logger.info("Cargando TrOCR para predict_text…")
            proc = TrOCRProcessor.from_pretrained(model_name, cache_dir=cache_dir)
            mdl = VisionEncoderDecoderModel.from_pretrained(model_name, cache_dir=cache_dir)
            mdl.eval()
            return proc, mdl

        proc, mdl = ModelCache.get(f"trocr_{model_name}", _loader)

        img = Image.open(image_path).convert("RGB")
        pv = proc(images=img, return_tensors="pt").pixel_values
        with torch.no_grad():
            # Greedy decode (num_beams=1) en lugar de beam search por defecto:
            # acelera 3-5× sin perder calidad apreciable en handwriting OCR.
            # early_stopping=True termina al encontrar EOS para no rellenar tokens.
            out = mdl.generate(
                pv,
                return_dict_in_generate=True,
                output_scores=True,
                max_new_tokens=96,
                num_beams=1,
                do_sample=False,
                early_stopping=True,
            )
        text = proc.batch_decode(out.sequences, skip_special_tokens=True)[0]
        text = _clean_predicted_text(text)
        # Confianza promedio
        conf = 0.0
        if out.scores:
            tok_confs = []
            for step in out.scores:
                probs = F.softmax(step[0], dim=-1)
                tok_confs.append(float(probs.max()))
            if tok_confs:
                conf = sum(tok_confs) / len(tok_confs)
        if text:
            logger.info("TrOCR predicción: %r (conf=%.2f)", text[:60], conf)
        return text, conf
    except Exception as exc:
        logger.warning("TrOCR predict_text falló: %s", exc)
        return "", 0.0


def _try_tesseract(image_path: str) -> tuple[str, float]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return "", 0.0

    try:
        from core.ocr._tesseract_setup import apply_tesseract_cmd
        apply_tesseract_cmd()
        with Image.open(image_path) as img:
            # PSM 6 = "Assume a single uniform block of text"
            data = pytesseract.image_to_data(
                img, lang="spa", config="--psm 6 --oem 3",
                output_type=pytesseract.Output.DICT,
            )
        words: list[str] = []
        confs: list[float] = []
        for txt, c in zip(data["text"], data["conf"]):
            txt = str(txt).strip()
            try:
                c = float(c)
            except (TypeError, ValueError):
                c = -1.0
            if txt and c >= 0:
                words.append(txt)
                confs.append(c / 100.0)
        text = _clean_predicted_text(" ".join(words))
        conf = sum(confs) / len(confs) if confs else 0.0
        if text:
            logger.info("Tesseract PSM6 predicción: %r (conf=%.2f)", text[:60], conf)
        return text, conf
    except Exception as exc:
        logger.warning("Tesseract predict_text falló: %s", exc)
        return "", 0.0

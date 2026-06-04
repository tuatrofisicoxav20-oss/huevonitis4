"""
Etiquetador usando Microsoft TrOCR (microsoft/trocr-base-handwritten). Opcional.
Requiere transformers + torch. Descarga ~400 MB en primera ejecución.
"""
import logging

import config

logger = logging.getLogger(__name__)

try:
    from transformers import TrOCRProcessor as _TrOCRProc
    from transformers import VisionEncoderDecoderModel as _VED
    _TRANSFORMERS_OK = True
except ImportError:
    _TRANSFORMERS_OK = False

try:
    import torch as _torch
    import torch.nn.functional as _F
    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False

from core.inkcore.glyph_labelers.base import GlyphLabeler

_DEFAULT_MODEL = "microsoft/trocr-base-handwritten"


class TrOCRLabeler(GlyphLabeler):
    """
    Etiqueta un glifo con TrOCR de Microsoft.
    model_name acepta small/base/large según RAM disponible:
      - microsoft/trocr-small-handwritten (~170 MB, más rápido)
      - microsoft/trocr-base-handwritten  (~400 MB, recomendado)
      - microsoft/trocr-large-handwritten (~1.3 GB, máxima calidad)
    """

    name = "trocr_labeler"
    available = _TRANSFORMERS_OK and _TORCH_OK

    def __init__(self, model_name: str | None = None):
        # None → resolver desde config en runtime (no en tiempo de import, para
        # que cambiar TROCR_MODEL en Configuración tenga efecto sin reiniciar).
        self.model_name = model_name or getattr(config, "TROCR_MODEL", _DEFAULT_MODEL) \
            or _DEFAULT_MODEL
        self._processor = None
        self._model = None

    def _load(self):
        if self._processor is not None:
            return
        if not _TRANSFORMERS_OK or not _TORCH_OK:
            return
        cache_dir = str(config.MODELS_DIR / "trocr")
        model_name = self.model_name

        from core.inkcore.model_cache import ModelCache

        def _loader():
            logger.info("Cargando TrOCR '%s' (primera carga puede tardar)…", model_name)
            proc = _TrOCRProc.from_pretrained(model_name, cache_dir=cache_dir)
            mdl = _VED.from_pretrained(model_name, cache_dir=cache_dir)
            mdl.eval()
            logger.info("TrOCR cargado correctamente.")
            return proc, mdl

        self._processor, self._model = ModelCache.get(
            f"trocr_{model_name}", _loader
        )

    @staticmethod
    def _to_rgb(img: "Image.Image") -> "Image.Image":
        if img.mode == "RGB":
            return img
        from PIL import Image as _PILImage
        bg = _PILImage.new("RGB", img.size, (255, 255, 255))
        if img.mode == "RGBA":
            bg.paste(img, mask=img.split()[3])
        else:
            bg.paste(img)
        return bg

    def _generate_with_scores(self, pixel_values) -> tuple[str, float]:
        with _torch.no_grad():
            out = self._model.generate(
                pixel_values,
                return_dict_in_generate=True,
                output_scores=True,
                max_new_tokens=8,
                num_beams=1,
                do_sample=False,
                early_stopping=True,
            )
        text = self._processor.batch_decode(
            out.sequences, skip_special_tokens=True
        )[0].strip()

        if out.scores:
            token_confs = []
            for score in out.scores:
                probs = _F.softmax(score[0], dim=-1)
                token_confs.append(float(probs.max()))
            conf = sum(token_confs) / len(token_confs) if token_confs else 0.0
        else:
            conf = 0.0

        return text or "?", conf

    def label(self, glyph_image: "Image.Image") -> tuple[str, float]:
        if not _TRANSFORMERS_OK or not _TORCH_OK:
            return ("?", 0.0)
        try:
            self._load()
            if self._processor is None or self._model is None:
                return ("?", 0.0)
            rgb = self._to_rgb(glyph_image)
            pixel_values = self._processor(images=rgb, return_tensors="pt").pixel_values
            text, conf = self._generate_with_scores(pixel_values)
            return (text, conf)
        except Exception as e:
            logger.error(f"TrOCRLabeler error: {e}")
            return ("?", 0.0)

    def label_batch(self, glyph_images: list) -> list[tuple[str, float]]:
        """Proceso en batch real — evita overhead de llamar al modelo N veces."""
        if not _TRANSFORMERS_OK or not _TORCH_OK:
            return [("?", 0.0)] * len(glyph_images)
        try:
            self._load()
            if self._processor is None or self._model is None:
                return [("?", 0.0)] * len(glyph_images)
            rgb_imgs = [self._to_rgb(img) for img in glyph_images]
            pixel_values = self._processor(
                images=rgb_imgs, return_tensors="pt"
            ).pixel_values
            with _torch.no_grad():
                out = self._model.generate(
                    pixel_values,
                    return_dict_in_generate=True,
                    output_scores=True,
                    max_new_tokens=8,
                )
            texts = self._processor.batch_decode(
                out.sequences, skip_special_tokens=True
            )
            results = []
            n = len(glyph_images)
            if out.scores:
                # out.scores es tupla de tensors [batch_size, vocab_size] por paso
                # Confianza por sample: promedio de max-softmax sobre tokens generados
                batch_confs = [[] for _ in range(n)]
                for score_step in out.scores:
                    probs = _F.softmax(score_step, dim=-1)  # [batch, vocab]
                    maxes = probs.max(dim=-1).values         # [batch]
                    for j in range(min(n, len(maxes))):
                        batch_confs[j].append(float(maxes[j]))
                for j in range(n):
                    t = (texts[j].strip() if j < len(texts) else "") or "?"
                    c = sum(batch_confs[j]) / len(batch_confs[j]) if batch_confs[j] else 0.0
                    results.append((t, c))
            else:
                for j in range(n):
                    t = (texts[j].strip() if j < len(texts) else "") or "?"
                    results.append((t, 0.0))
            return results
        except Exception as e:
            logger.error(f"TrOCRLabeler batch error: {e}")
            return [("?", 0.0)] * len(glyph_images)

    def install_hint(self) -> str:
        return (
            "TrOCR no instalado.\n"
            "pip install transformers torch\n"
            f"Modelo '{self.model_name}' se descarga ~400 MB en primera ejecución."
        )

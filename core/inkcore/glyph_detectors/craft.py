"""
Detector CRAFT (Character Region Awareness for Text detection). Opcional.
Configurado con link_threshold bajo para detectar a nivel CARÁCTER, no palabra.
"""
import logging
import os
import tempfile

import config

logger = logging.getLogger(__name__)

try:
    from craft_text_detector import Craft as _Craft
    _CRAFT_OK = True
except ImportError:
    _CRAFT_OK = False

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

import contextlib  # noqa: E402

from core.inkcore.glyph_detectors.base import GlyphDetector  # noqa: E402


class CRAFTDetector(GlyphDetector):
    """
    Detector CRAFT — bueno para encontrar caracteres individuales en
    escritura impresa y semi-cursiva.

    link_threshold bajo (0.1) fuerza detección por carácter en vez de por palabra.
    """

    name = "craft"
    available = _CRAFT_OK and _CV2_OK

    def __init__(
        self,
        text_threshold: float = 0.7,
        link_threshold: float = 0.1,
        low_text: float = 0.4,
    ):
        self._craft = None  # lazy
        self.text_threshold = text_threshold
        self.link_threshold = link_threshold
        self.low_text = low_text

    @staticmethod
    def _patch_torchvision_for_craft():
        """craft-text-detector usa torchvision.models.vgg.model_urls que fue
        removido en torchvision >= 0.13. Lo restauramos antes de instanciar."""
        try:
            from torchvision.models import vgg as _vgg
            if not hasattr(_vgg, "model_urls"):
                _vgg.model_urls = {
                    "vgg11": "https://download.pytorch.org/models/vgg11-8a719046.pth",
                    "vgg13": "https://download.pytorch.org/models/vgg13-19584684.pth",
                    "vgg16": "https://download.pytorch.org/models/vgg16-397923af.pth",
                    "vgg19": "https://download.pytorch.org/models/vgg19-dcbb9e9d.pth",
                    "vgg11_bn": "https://download.pytorch.org/models/vgg11_bn-6002323d.pth",
                    "vgg13_bn": "https://download.pytorch.org/models/vgg13_bn-abd245e5.pth",
                    "vgg16_bn": "https://download.pytorch.org/models/vgg16_bn-6c64b313.pth",
                    "vgg19_bn": "https://download.pytorch.org/models/vgg19_bn-c79401a0.pth",
                }
        except Exception:
            pass

    def _get_craft(self):
        if self._craft is None:
            if not _CRAFT_OK:
                return None
            self._patch_torchvision_for_craft()
            models_dir = config.MODELS_DIR / "craft"
            models_dir.mkdir(parents=True, exist_ok=True)
            from core.inkcore.model_cache import ModelCache
            tt, lt, lw = self.text_threshold, self.link_threshold, self.low_text
            self._craft = ModelCache.get(
                f"craft_{tt}_{lt}_{lw}",
                lambda: _Craft(
                    output_dir=str(models_dir),
                    rectify=True,
                    export_extra=False,
                    text_threshold=tt,
                    link_threshold=lt,
                    low_text=lw,
                    cuda=False,
                ),
            )
        return self._craft

    def detect(self, image_bgr: "np.ndarray") -> list:
        if not _CRAFT_OK or not _CV2_OK:
            return []
        try:
            from core.inkcore.extractor import BBox
            craft = self._get_craft()
            if craft is None:
                return []

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                cv2.imwrite(tmp_path, image_bgr)
                result = craft.detect_text(tmp_path)
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

            boxes = []
            if result and "boxes" in result:
                for box in result["boxes"]:
                    pts = np.array(box, dtype=np.float32)
                    x = int(np.min(pts[:, 0]))
                    y = int(np.min(pts[:, 1]))
                    w = int(np.max(pts[:, 0]) - x)
                    h = int(np.max(pts[:, 1]) - y)
                    if w > 0 and h > 0:
                        boxes.append(BBox(x, y, w, h))
            boxes.sort(key=lambda b: (b.y, b.x))
            return boxes
        except Exception as e:
            logger.error(f"CRAFTDetector error: {e}")
            return []

    def install_hint(self) -> str:
        return (
            "CRAFT no instalado.\n"
            "pip install craft-text-detector"
        )

import logging
from pathlib import Path
from core.inkcore.ai.contracts import GlyphImageFeatures

logger = logging.getLogger(__name__)

try:
    import numpy as np
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def extract_image_features(img: "Image.Image") -> GlyphImageFeatures:
    if not _PIL_OK:
        return GlyphImageFeatures()
    # Bug fix #5: guard against zero-size images before any numpy work
    if img.width == 0 or img.height == 0:
        return GlyphImageFeatures(warnings=["zero_size"])
    try:
        alpha = np.array(img.getchannel("A"))
        total = alpha.size
        ink = int(np.sum(alpha > 0))
        ink_density = ink / max(1, total)
        h, w = alpha.shape[:2]
        aspect_ratio = w / max(1, h)
        bbox = Image.fromarray(alpha, mode="L").getbbox()
        if bbox:
            tight_w = bbox[2] - bbox[0]
            tight_h = bbox[3] - bbox[1]
            bbox_fill_ratio = (tight_w * tight_h) / max(1, total)
            top_margin = bbox[1] / max(1, h)
            bottom_margin = (h - bbox[3]) / max(1, h)
            left_margin = bbox[0] / max(1, w)
            right_margin = (w - bbox[2]) / max(1, w)
        else:
            bbox_fill_ratio = top_margin = bottom_margin = left_margin = right_margin = 0.0

        warnings = []
        if ink_density < 0.02:
            warnings.append("very_low_ink")
        if ink_density > 0.85:
            warnings.append("very_high_ink")
        if bbox and (bbox[2] - bbox[0] < 3 or bbox[3] - bbox[1] < 5):
            warnings.append("too_small")
        if aspect_ratio > 4.0:
            warnings.append("very_wide")

        return GlyphImageFeatures(
            ink_density=float(ink_density),
            aspect_ratio=float(aspect_ratio),
            bbox_fill_ratio=float(bbox_fill_ratio),
            top_margin=float(top_margin),
            bottom_margin=float(bottom_margin),
            left_margin=float(left_margin),
            right_margin=float(right_margin),
            warnings=warnings,
        )
    except Exception as e:
        logger.warning(f"Feature extraction failed: {e}")
        return GlyphImageFeatures()


def infer_char_from_path(path: str) -> str:
    stem = Path(path).stem
    parts = stem.rsplit("_", 1)
    if len(parts) == 2:
        try:
            int(parts[1])
            stem = parts[0]
        except ValueError:
            pass
    if stem.startswith("punct_"):
        try:
            return chr(int(stem[6:]))
        except Exception:
            pass
    return stem[:1] if stem else ""


def confidence_adjustment_from_features(features: GlyphImageFeatures) -> float:
    penalty = 0.0
    if "very_low_ink" in features.warnings:
        penalty -= 0.35
    if "too_small" in features.warnings:
        penalty -= 0.20
    if "very_wide" in features.warnings:
        penalty -= 0.12
    if "very_high_ink" in features.warnings:
        penalty -= 0.08
    # Touching border means the crop missed some ink
    if (features.top_margin < 0.02 or features.bottom_margin < 0.02 or
            features.left_margin < 0.02 or features.right_margin < 0.02):
        penalty -= 0.12
    return penalty

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import numpy as np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


def assess_glyph(image_path: str) -> dict:
    """Returns quality metrics for a glyph PNG file."""
    if not PIL_OK or not NUMPY_OK:
        return {"score": 0.5, "tier": "Bronze", "ink_coverage": 0.5, "valid": True}
    try:
        img = Image.open(image_path).convert("RGBA")
        arr = np.array(img)
        alpha = arr[:, :, 3]
        total = alpha.size
        ink = np.sum(alpha > 64)
        ink_coverage = ink / total if total > 0 else 0
        w, h = img.size
        aspect = w / h if h > 0 else 1.0
        aspect_score = 1.0 - abs(aspect - 0.6) / 1.5
        aspect_score = max(0.0, min(1.0, aspect_score))
        size_score = min(1.0, min(w, h) / 30)
        score = ink_coverage * 0.5 + aspect_score * 0.3 + size_score * 0.2
        score = round(min(1.0, max(0.0, score)), 3)
        if score >= 0.75:
            tier = "Gold"
        elif score >= 0.45:
            tier = "Silver"
        else:
            tier = "Bronze"
        return {"score": score, "tier": tier, "ink_coverage": round(ink_coverage, 3), "valid": True}
    except Exception as e:
        logger.warning(f"Quality assess failed for {image_path}: {e}")
        return {"score": 0.3, "tier": "Bronze", "ink_coverage": 0.3, "valid": False}


def compute_final_quality(
    base_quality: float,
    label_confidence: float | None,
    agreement_score: float,
    config,
) -> float:
    """Combina calidad base, acuerdo entre detectores y confianza del labeler.

    Args:
        base_quality: score raw de assess_glyph() (0-1).
        label_confidence: confianza del labeler ganador (0-1), o None si no hubo labeler.
        agreement_score: fracción de detectores que coincidieron (0-1).
        config: PipelineConfig con label_conf_weight y min_quality.

    Returns:
        Score final clampado a [0, 1].
    """
    final = base_quality * (0.7 + 0.3 * agreement_score)
    if label_confidence is not None:
        weight = getattr(config, "label_conf_weight", 0.3)
        if weight > 0:
            boost = 1.0 + weight * (label_confidence - 0.5)
            final *= max(0.1, boost)
    return min(1.0, max(0.0, final))

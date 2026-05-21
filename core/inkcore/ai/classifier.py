"""
Clasificador de glifos para Huevonitis 4.

FallbackGlyphClassifier: clasificador basado en reglas (sin ML).
Usa características de imagen y heurísticas de nombre de archivo.

Ver docs/ai-integration-notes.md para guía de integración de un modelo real.
"""
import logging

from core.inkcore.ai.contracts import GlyphPrediction
from core.inkcore.ai.features import (
    confidence_adjustment_from_features,
    extract_image_features,
    infer_char_from_path,
)

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class FallbackGlyphClassifier:
    """Rule-based glyph classifier using image features and filename heuristics.

    Used when no ML backend is available. Combines quality score,
    alignment score (from DP), and image feature penalties.
    """

    def predict(
        self,
        img: "Image.Image",
        assigned_char: str = "",
        path: str = "",
        quality_score: float = 0.0,
        alignment_score: float | None = None,
    ) -> GlyphPrediction:
        if not _PIL_OK:
            return GlyphPrediction(
                char=assigned_char, confidence=0.5,
                quality_score=quality_score, needs_review=True,
            )
        features = extract_image_features(img)
        char = assigned_char or infer_char_from_path(path)

        if alignment_score is not None:
            base_conf = 0.25 + 0.38 * quality_score + 0.37 * max(0.0, min(1.0, alignment_score))
        else:
            base_conf = 0.42 + 0.45 * quality_score

        adj = confidence_adjustment_from_features(features)
        confidence = max(0.05, min(0.98, base_conf + adj))

        flags = list(features.warnings)
        if confidence < 0.68:
            flags.append("low_confidence")
        if quality_score < 0.70:
            flags.append("low_quality")

        # Bug fix #6: only trigger needs_review for genuinely serious signals.
        # Minor warnings (very_high_ink, border touch) must not override a
        # Gold-quality glyph (quality >= 0.75, confidence >= 0.68).
        SERIOUS_WARNINGS = {"very_low_ink", "too_small", "zero_size"}
        has_serious_warning = bool(SERIOUS_WARNINGS & set(features.warnings))
        needs_review = (
            confidence < 0.68
            or quality_score < 0.46
            or has_serious_warning
        )

        return GlyphPrediction(
            char=char,
            confidence=round(confidence, 3),
            quality_score=round(quality_score, 3),
            needs_review=needs_review,
            flags=flags,
        )

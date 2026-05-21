from dataclasses import dataclass, field


@dataclass
class GlyphImageFeatures:
    ink_density: float = 0.0
    aspect_ratio: float = 1.0
    bbox_fill_ratio: float = 0.0
    top_margin: float = 0.0
    bottom_margin: float = 0.0
    left_margin: float = 0.0
    right_margin: float = 0.0
    warnings: list = field(default_factory=list)


@dataclass
class GlyphPrediction:
    char: str = ""
    confidence: float = 0.0
    quality_score: float = 0.0
    needs_review: bool = False
    flags: list = field(default_factory=list)

"""
Dataclasses de configuración y resultado del pipeline ensemble de extracción.
Separadas de extraction_pipeline.py para mantener los módulos por debajo de
~420 líneas. Se re-exportan desde extraction_pipeline para no romper la API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from core.models import GlyphEntry


@dataclass
class PipelineConfig:
    detectors: list[str] = field(default_factory=lambda: ["classic_cv"])
    detector_fusion: Literal["union", "intersection", "cascade"] = "union"
    iou_dedup_threshold: float = 0.5

    # F6 — defaults del ensemble: ambos labelers + voting por CONSENSO. El
    # consenso es lo que habilita la verificación cruzada (Gold sólo si ambos
    # labelers coinciden). Los labelers no instalados se omiten con un warning.
    labelers: list[str] = field(
        default_factory=lambda: ["tesseract_labeler", "trocr_labeler"]
    )
    labeler_voting: Literal["majority", "highest_conf", "consensus"] = "consensus"

    min_quality: float = 0.18
    min_label_confidence: float = 0.0
    label_conf_weight: float = 0.3

    labeler_batch_size: int = 32
    debug_overlay: bool = False

    # Modo automático: si auto_label=True y labelers está vacío, inyecta
    # los labelers disponibles (trocr si está, si no tesseract). Cuando se usa
    # sin reference_text esto es lo que clasifica cada glifo extraído.
    auto_label: bool = False
    # Si True, descarta glifos cuyo predicted_char no sea letra/dígito
    # (filtra ruido: líneas, manchas, puntuación que el detector recoja).
    letters_only: bool = False
    # Aspect ratio (w/h) admitido para considerar un blob "glifo".
    # Por debajo del mínimo es línea vertical; por arriba del máximo es línea horizontal.
    min_aspect_ratio: float = 0.12
    max_aspect_ratio: float = 6.0
    # Cobertura mínima de tinta dentro del bbox detectado (descarta manchas huecas).
    min_ink_coverage: float = 0.02


@dataclass
class ExtractionResult:
    glyphs: list[GlyphEntry]
    debug_image_path: str | None = None
    stats: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)
    # Salto 0 (eval) — cajas predichas alineadas 1:1 con `glyphs`, en coords de la
    # imagen ya preprocesada (la misma sobre la que corre la detección). Cada
    # entrada es [x, y, w, h]. Permite calcular IoU contra el ground-truth sin
    # tocar el modelo persistido GlyphEntry.
    boxes: list = field(default_factory=list)

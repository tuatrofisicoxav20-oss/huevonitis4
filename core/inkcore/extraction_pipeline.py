"""
Pipeline ensemble de extracción de glifos.
Orquesta: múltiples detectores → fusión → labelers en batch → voting → quality.
Configurable por PipelineConfig; no rompe el flujo legacy si use_pipeline=False.
"""
from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import config as _config

from core.models import GlyphEntry

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    detectors: list[str] = field(default_factory=lambda: ["classic_cv"])
    detector_fusion: Literal["union", "intersection", "cascade"] = "union"
    iou_dedup_threshold: float = 0.5

    labelers: list[str] = field(default_factory=list)
    labeler_voting: Literal["majority", "highest_conf", "consensus"] = "highest_conf"

    min_quality: float = 0.18
    min_label_confidence: float = 0.0
    label_conf_weight: float = 0.3

    labeler_batch_size: int = 32
    debug_overlay: bool = False


@dataclass
class ExtractionResult:
    glyphs: list[GlyphEntry]
    debug_image_path: str | None = None
    stats: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)


class GlyphExtractionPipeline:
    """Orquestador del ensemble de extracción de glifos."""

    def __init__(self, cfg: PipelineConfig):
        self.config = cfg
        self.detectors = []
        self.labelers = []
        self._load_detectors()
        self._load_labelers()

    def _load_detectors(self) -> None:
        from core.inkcore import glyph_detectors
        for name in self.config.detectors:
            d = glyph_detectors.get_detector(name)
            if d.available:
                self.detectors.append(d)
            else:
                logger.warning("Detector '%s' no disponible: %s", name, d.install_hint())
        if not self.detectors:
            logger.info("Pipeline: ningún detector disponible, cargando classic_cv")
            from core.inkcore.glyph_detectors.classic_cv import ClassicCVDetector
            self.detectors.append(ClassicCVDetector())

    def _load_labelers(self) -> None:
        from core.inkcore import glyph_labelers
        for name in self.config.labelers:
            l = glyph_labelers.get_labeler(name)
            if l.available:
                self.labelers.append(l)
            else:
                logger.warning("Labeler '%s' no disponible: %s", name, l.install_hint())

    def extract(self, image_path: str, reference_text: str = "") -> ExtractionResult:
        t_start = time.perf_counter()
        timings: dict = {}
        stats: dict = {}

        try:
            import cv2
            import numpy as np
        except ImportError:
            return ExtractionResult(glyphs=[], stats={"error": "cv2 no disponible"})

        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            return ExtractionResult(glyphs=[], stats={"error": f"no se pudo leer {image_path}"})

        # 1. Preprocesar (reutiliza pipeline del GlyphExtractor)
        from core.inkcore.extractor import ExtractionOptions, GlyphExtractor
        _ext = GlyphExtractor()
        opts = ExtractionOptions(min_quality=self.config.min_quality)
        img = _ext._scale(img_bgr)
        img = _ext._autocrop(img)
        img, _ = _ext._deskew(img)
        _, _, clean = _ext._full_preprocess(img, opts)
        h_img, w_img = img.shape[:2]

        timings["preprocess_ms"] = int((time.perf_counter() - t_start) * 1000)

        # 2. Detectar con cada detector
        all_detections: dict[str, list] = {}
        for det in self.detectors:
            t0 = time.perf_counter()
            try:
                bboxes = det.detect(img)
                all_detections[det.name] = bboxes
                logger.info("Detector '%s': %d bboxes", det.name, len(bboxes))
            except Exception as exc:
                logger.error("Detector '%s' error: %s", det.name, exc)
                all_detections[det.name] = []
            timings[f"detect_{det.name}_ms"] = int((time.perf_counter() - t0) * 1000)

        stats["detector_counts"] = {k: len(v) for k, v in all_detections.items()}

        # 3. Fusionar
        from core.inkcore.glyph_detectors.fusion import fuse, FusedBBox
        fused = fuse(all_detections, strategy=self.config.detector_fusion,
                     iou_threshold=self.config.iou_dedup_threshold)
        stats["fused_count"] = len(fused)

        # 4. Recortar crops PIL de cada bbox fusionado
        try:
            from PIL import Image as _PIL
        except ImportError:
            return ExtractionResult(glyphs=[], stats={"error": "Pillow no disponible"})

        PAD = 4
        crops: list["_PIL.Image"] = []
        valid_fused: list[FusedBBox] = []
        for fb in fused:
            x1 = max(0, fb.x - PAD)
            y1 = max(0, fb.y - PAD)
            x2 = min(w_img, fb.x + fb.w + PAD)
            y2 = min(h_img, fb.y + fb.h + PAD)
            crop_bgr = img[y1:y2, x1:x2]
            if crop_bgr.size == 0:
                continue
            crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
            crops.append(_PIL.fromarray(crop_rgb).convert("RGBA"))
            valid_fused.append(fb)

        # 5. Etiquetar en batch
        t_label = time.perf_counter()
        all_preds: dict[str, list[tuple[str, float]]] = {}
        for labeler in self.labelers:
            preds: list[tuple[str, float]] = []
            bs = self.config.labeler_batch_size
            for i in range(0, len(crops), bs):
                batch = crops[i:i + bs]
                try:
                    preds.extend(labeler.label_batch(batch))
                except Exception as exc:
                    logger.error("Labeler '%s' batch error: %s", labeler.name, exc)
                    preds.extend([("?", 0.0)] * len(batch))
            all_preds[labeler.name] = preds
        timings["label_ms"] = int((time.perf_counter() - t_label) * 1000)

        # 6. Votar + quality scoring
        from core.inkcore.glyph_labelers.voting import vote
        from core.inkcore.quality import assess_glyph, compute_final_quality

        temp_dir = _config.TIPOGRAFIA_DIR / "_temp_extract"
        temp_dir.mkdir(parents=True, exist_ok=True)

        glyphs: list[GlyphEntry] = []
        debug_accepted: list[tuple] = []
        debug_discarded: list[tuple] = []

        for i, (fb, crop) in enumerate(zip(valid_fused, crops)):
            crop_preds = {
                name: preds[i]
                for name, preds in all_preds.items()
                if i < len(preds)
            }

            if crop_preds:
                char, label_conf, _ = vote(crop_preds, self.config.labeler_voting)
            else:
                char, label_conf = "?", None

            if (label_conf is not None
                    and label_conf < self.config.min_label_confidence):
                debug_discarded.append((fb, crop, char, label_conf))
                continue

            safe = char if (char.isalnum() or char == "?") else f"punct_{ord(char)}"
            out_path = temp_dir / f"{safe}_{i:04d}.png"
            try:
                crop.save(str(out_path))
            except Exception:
                continue

            quality = assess_glyph(str(out_path))
            base_q = quality.get("score", 0.0)
            final_q = compute_final_quality(
                base_quality=base_q,
                label_confidence=label_conf,
                agreement_score=fb.agreement_score,
                config=self.config,
            )

            if final_q < self.config.min_quality:
                debug_discarded.append((fb, crop, char, label_conf))
                continue

            tier = "Gold" if final_q > 0.75 else "Silver" if final_q > 0.48 else "Bronze"
            glyphs.append(GlyphEntry(
                char=char,
                image_path=str(out_path),
                quality_score=round(final_q, 3),
                tier=tier,
                ink_coverage=round(quality.get("ink_coverage", 0.0), 3),
                index=i,
                predicted_char=char if self.labelers else None,
                label_confidence=label_conf,
                detector_sources=list(fb.sources),
            ))
            debug_accepted.append((fb, crop, char, label_conf))

        stats["glyphs_accepted"] = len(glyphs)
        stats["glyphs_discarded"] = len(debug_discarded)
        timings["total_ms"] = int((time.perf_counter() - t_start) * 1000)

        # 7. Debug overlay
        debug_path = None
        if self.config.debug_overlay:
            try:
                debug_path = _generate_debug_overlay(
                    img, debug_accepted, debug_discarded
                )
            except Exception as exc:
                logger.warning("Debug overlay error: %s", exc)

        logger.info(
            "Pipeline: %d aceptados, %d descartados en %dms",
            len(glyphs), len(debug_discarded), timings["total_ms"],
        )
        return ExtractionResult(
            glyphs=glyphs,
            debug_image_path=debug_path,
            stats=stats,
            timings_ms=timings,
        )


def _generate_debug_overlay(
    img_bgr: "np.ndarray",
    accepted: list[tuple],
    discarded: list[tuple],
) -> str | None:
    """Genera PNG con overlay de cajas aceptadas y descartadas."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    overlay = img_bgr.copy()
    h, w = overlay.shape[:2]

    for fb, _, char, conf in accepted:
        # Verde si todos lo vieron, amarillo si solo algunos
        if fb.agreement_score >= 0.99:
            color = (0, 200, 0)
        else:
            color = (0, 180, 255)  # BGR amarillo
        cv2.rectangle(overlay, (fb.x, fb.y), (fb.x + fb.w, fb.y + fb.h), color, 2)
        label = char
        if conf is not None:
            label += f" {conf:.2f}"
        cv2.putText(overlay, label, (fb.x, max(10, fb.y - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

    for fb, _, char, conf in discarded:
        cv2.rectangle(overlay, (fb.x, fb.y), (fb.x + fb.w, fb.y + fb.h),
                      (0, 0, 200), 1)

    # Leyenda en esquina superior derecha
    legend_x = max(0, w - 210)
    cv2.rectangle(overlay, (legend_x, 5), (w - 5, 75), (20, 20, 30), -1)
    cv2.putText(overlay, "Verde: todos detectores", (legend_x + 5, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 200, 0), 1)
    cv2.putText(overlay, "Amarillo: algunos", (legend_x + 5, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 180, 255), 1)
    cv2.putText(overlay, "Rojo: descartados", (legend_x + 5, 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 200), 1)

    debug_dir = _config.DEBUG_DIR
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    out_path = str(debug_dir / f"extraction_{ts}.png")
    cv2.imwrite(out_path, overlay)
    logger.info("Debug overlay guardado en %s", out_path)
    return out_path

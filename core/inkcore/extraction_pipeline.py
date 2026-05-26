"""
Pipeline ensemble de extracción de glifos.
Orquesta: múltiples detectores → fusión → labelers en batch → voting → quality.
Configurable por PipelineConfig; no rompe el flujo legacy si use_pipeline=False.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
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
        names = list(self.config.labelers)
        # Modo automático: si no hay labelers explícitos, inyectar los que existan.
        # Preferimos TrOCR (handwriting-aware); caemos a tesseract si no está.
        if self.config.auto_label and not names:
            avail = glyph_labelers.get_available()
            if avail.get("trocr_labeler"):
                names.append("trocr_labeler")
            if avail.get("tesseract_labeler"):
                names.append("tesseract_labeler")
            if not names:
                logger.warning(
                    "auto_label=True pero no hay labelers instalados; "
                    "los glifos saldrán sin clasificar."
                )
        for name in names:
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

        # 3.5. Filtrar bboxes que claramente NO son letras (líneas, manchas)
        min_ar = self.config.min_aspect_ratio
        max_ar = self.config.max_aspect_ratio
        min_cov = self.config.min_ink_coverage
        kept: list[FusedBBox] = []
        dropped_shape = 0
        dropped_cov = 0
        for fb in fused:
            if fb.h <= 0 or fb.w <= 0:
                dropped_shape += 1
                continue
            ar = fb.w / fb.h
            if ar < min_ar or ar > max_ar:
                # Línea vertical/horizontal o blob aberrante
                dropped_shape += 1
                continue
            y1 = max(0, fb.y)
            y2 = min(h_img, fb.y + fb.h)
            x1 = max(0, fb.x)
            x2 = min(w_img, fb.x + fb.w)
            if x2 <= x1 or y2 <= y1:
                dropped_shape += 1
                continue
            sub_mask = clean[y1:y2, x1:x2]
            cov = float(np.sum(sub_mask > 0)) / max(1, sub_mask.size)
            if cov < min_cov:
                dropped_cov += 1
                continue
            kept.append(fb)
        if dropped_shape or dropped_cov:
            logger.info(
                "Pre-label filter: %d/%d kept (descartados shape=%d, cov=%d)",
                len(kept), len(fused), dropped_shape, dropped_cov,
            )
        stats["dropped_shape"] = dropped_shape
        stats["dropped_coverage"] = dropped_cov
        stats["kept_after_filter"] = len(kept)
        fused = kept

        # 4. Recortar crops PIL de cada bbox fusionado.
        # Mejorado: usamos la máscara limpia (sin líneas/fondo), refinamos
        # la región para capturar diacríticos (puntos de i, acentos, ñ) y
        # descenders (g, p, q, y, j), aplicamos tight_crop y convertimos
        # a RGBA con anti-aliasing — todo del extractor legacy.
        try:
            from PIL import Image as _PIL
        except ImportError:
            return ExtractionResult(glyphs=[], stats={"error": "Pillow no disponible"})

        PAD = 4
        crops: list["_PIL.Image"] = []
        valid_fused: list[FusedBBox] = []
        for fb in fused:
            # Banda horizontal con margen vertical extra para que
            # _refine_char_region pueda detectar diacríticos arriba y
            # descenders abajo del bbox crudo del detector.
            band_top = max(0, fb.y - int(fb.h * 0.45))
            band_bot = min(h_img, fb.y + fb.h + int(fb.h * 0.30))
            if band_bot <= band_top:
                continue
            line_mask = clean[band_top:band_bot, :]

            # Refinar incluyendo diacríticos/descenders (coords dentro de line_mask)
            gx1, gy1, gx2, gy2 = _ext._refine_char_region(
                line_mask, fb.x, fb.x + fb.w,
            )

            y1 = max(0, band_top + gy1 - PAD)
            y2 = min(h_img, band_top + gy2 + PAD)
            x1 = max(0, gx1 - PAD)
            x2 = min(w_img, gx2 + PAD)
            if x2 <= x1 or y2 <= y1:
                continue

            mask_crop = clean[y1:y2, x1:x2]
            if mask_crop.size == 0:
                continue

            tight = _ext._tight_crop(mask_crop, padding=3)
            if tight is None:
                continue

            pil_img = _ext._to_rgba_smooth(tight)
            crops.append(pil_img)
            valid_fused.append(fb)

        # 5. Etiquetar en batch.
        # Los crops guardados son RGBA con tinta blanca (para mostrarse sobre
        # tema oscuro). Tesseract y TrOCR esperan tinta NEGRA sobre fondo
        # BLANCO con contexto blanco alrededor (Tesseract descarta chars en
        # el borde). Convertimos antes de etiquetar.
        def _rgba_to_label_rgb(pil_rgba, border: int = 8):
            arr = np.array(pil_rgba.convert("RGBA"))
            alpha = arr[..., 3].astype(np.float32) / 255.0
            # alpha alto = tinta densa → píxel oscuro
            intensity = ((1.0 - alpha) * 255.0).astype(np.uint8)
            rgb_arr = np.stack([intensity, intensity, intensity], axis=-1)
            pil = _PIL.fromarray(rgb_arr, mode="RGB")
            # Margen blanco — clave para que Tesseract no descarte el char.
            new_w = pil.width + border * 2
            new_h = pil.height + border * 2
            bg = _PIL.new("RGB", (new_w, new_h), (255, 255, 255))
            bg.paste(pil, (border, border))
            return bg

        label_crops = [_rgba_to_label_rgb(c) for c in crops]

        t_label = time.perf_counter()
        all_preds: dict[str, list[tuple[str, float]]] = {}
        for labeler in self.labelers:
            preds: list[tuple[str, float]] = []
            bs = self.config.labeler_batch_size
            for i in range(0, len(label_crops), bs):
                batch = label_crops[i:i + bs]
                try:
                    preds.extend(labeler.label_batch(batch))
                except Exception as exc:
                    logger.error("Labeler '%s' batch error: %s", labeler.name, exc)
                    preds.extend([("?", 0.0)] * len(batch))
            all_preds[labeler.name] = preds
        timings["label_ms"] = int((time.perf_counter() - t_label) * 1000)

        # 6. Votar + quality scoring (usa la versión rica _assess_quality
        # del extractor, que pondera cobertura asimétrica, ancho de trazo
        # por distance transform, borde, alineación e ink absoluto).
        from core.inkcore.glyph_labelers.voting import vote
        from core.inkcore.quality import compute_final_quality

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

            # Tesseract puede devolver "" o "ab" — normalizamos a 1 char.
            char = (char or "?").strip()
            if not char:
                char = "?"
            char = char[0]

            if (label_conf is not None
                    and label_conf < self.config.min_label_confidence):
                debug_discarded.append((fb, crop, char, label_conf))
                continue

            # letters_only: descarta cualquier predicción que no sea letra del
            # alfabeto español (incluye á é í ó ú ñ y dígitos 0-9). Útil cuando
            # el detector recoge basura no-textual y el labeler la confirma como
            # punctuación/símbolo.
            if self.config.letters_only:
                allowed = "abcdefghijklmnñopqrstuvwxyzáéíóúABCDEFGHIJKLMNÑOPQRSTUVWXYZÁÉÍÓÚ0123456789"
                # Si no hay labeler, char puede ser "?" → conservar (tratar como
                # candidato sin clasificar, no como ruido)
                if char and char != "?" and char not in allowed:
                    debug_discarded.append((fb, crop, char, label_conf))
                    continue

            safe = char if (char.isalnum() or char == "?") else f"punct_{ord(char)}"
            out_path = temp_dir / f"{safe}_{i:04d}.png"
            try:
                crop.save(str(out_path))
            except Exception:
                continue

            # Quality rica del extractor (sobre el PIL en memoria, sin re-leer disco).
            # align_score=agreement_score → glifos vistos por más detectores
            # ganan un pequeño boost al ponderar la alineación interna.
            quality = _ext._assess_quality(crop, align_score=fb.agreement_score)
            base_q = quality.get("quality_score", 0.0)
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
                ink_coverage=round(quality.get("coverage", 0.0), 3),
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

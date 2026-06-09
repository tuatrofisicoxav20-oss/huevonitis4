"""
Pipeline ensemble de extracción de glifos.
Orquesta: múltiples detectores → fusión → labelers en batch → voting → quality.
Configurable por PipelineConfig; no rompe el flujo legacy si use_pipeline=False.
"""
from __future__ import annotations

import logging
import time

import config as _config

# PipelineConfig/ExtractionResult viven en extraction_pipeline_config y el
# overlay de debug en extraction_debug; se re-exportan acá para no romper la
# API pública (from core.inkcore.extraction_pipeline import ...).
from core.inkcore.extraction_debug import _generate_debug_overlay
from core.inkcore.extraction_pipeline_config import (
    ExtractionResult,
    PipelineConfig,
)
from core.models import GlyphEntry

__all__ = [
    "ExtractionResult",
    "GlyphExtractionPipeline",
    "PipelineConfig",
    "_generate_debug_overlay",
]

logger = logging.getLogger(__name__)


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
            labeler = glyph_labelers.get_labeler(name)
            if labeler.available:
                self.labelers.append(labeler)
            else:
                logger.warning("Labeler '%s' no disponible: %s", name, labeler.install_hint())

    def _build_expected_map(self, valid_fused, ref_chars, med_h, box_votes) -> dict:
        """Salto 3 — mapa {idx_caja: carácter esperado de la referencia}.

        "positional": la k-ésima caja en orden de lectura ↔ el k-ésimo char
        (greedy, hereda desfases). "dp": alineación global Needleman-Wunsch,
        robusta a cajas extra/faltantes (costos = ancho vs wf + confianza del
        labeler). Opt-in vía PipelineConfig.char_alignment.
        """
        if not ref_chars or not valid_fused:
            return {}
        order = sorted(
            range(len(valid_fused)),
            key=lambda j: (int(valid_fused[j].y / max(1.0, med_h * 0.6)),
                           valid_fused[j].x),
        )
        if self.config.char_alignment == "dp":
            try:
                from core.inkcore.extractor_align_basic import wf
                from core.inkcore.glyph_dp_align import nw_align
                widths = [valid_fused[j].w / med_h for j in order]
                preds = [box_votes[j][0] for j in order]
                confs = [box_votes[j][1] for j in order]
                mapping = nw_align(widths, preds, confs, ref_chars, wf)
                return {order[k]: ref_chars[v] for k, v in mapping.items()}
            except Exception as exc:
                logger.warning("alineación DP falló (%s); caigo a posicional", exc)
        # Posicional (default / fallback).
        em: dict[int, str] = {}
        for pos, j in enumerate(order):
            if pos < len(ref_chars):
                em[j] = ref_chars[pos]
        return em

    def extract(self, image_path: str, reference_text: str = "") -> ExtractionResult:
        t_start = time.perf_counter()
        timings: dict = {}
        stats: dict = {}

        try:
            import cv2  # noqa: F401
            import numpy as np
        except ImportError:
            return ExtractionResult(glyphs=[], stats={"error": "cv2 no disponible"})

        # F5/F6 — respetar orientación EXIF también en el pipeline ensemble
        # (cv2.imread la ignora; fotos de celular entrarían acostadas).
        from core.inkcore.glyph_ingest import (
            GlyphPreprocessOptions,
            ImagePreprocessor,
            assess_quality,
            imread_oriented,
            orient_by_content,
            refine_char_region,
            tight_crop,
            to_rgba_smooth,
        )
        img_bgr = imread_oriented(image_path)
        if img_bgr is None:
            return ExtractionResult(glyphs=[], stats={"error": f"no se pudo leer {image_path}"})
        # Paso 2 (5ta tanda) — orientación por contenido/OSD o manual antes del deskew.
        img_bgr = orient_by_content(img_bgr, self.config.manual_orientation)

        # 1. Preprocesar con el motor de imagen (extractor_preprocess), desacoplado
        # de la fachada GlyphExtractor (eliminada en la limpieza v4.2).
        _prep = ImagePreprocessor()
        opts = GlyphPreprocessOptions(min_quality=self.config.min_quality)
        img = _prep.scale(img_bgr)
        img = _prep.autocrop(img)
        img, _ = _prep.deskew(img)
        _, _, clean = _prep.full_preprocess(img, opts)
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
        from core.inkcore.glyph_detectors.fusion import FusedBBox, fuse
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
        crops: list[_PIL.Image] = []
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
            gx1, gy1, gx2, gy2 = refine_char_region(
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

            tight = tight_crop(mask_crop, padding=3)
            if tight is None:
                continue

            pil_img = to_rgba_smooth(tight)
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
        # F4 — Mapeo glifo→char esperado de la referencia, para verificar la
        # predicción del labeler contra lo que el usuario dijo que escribió.
        import re as _re

        from core.inkcore.glyph_labelers.voting import vote
        from core.inkcore.quality import (
            classify_tier_verified,
            compute_final_quality,
            is_verified,
        )
        ref_chars = list(_re.sub(r"\s+", "", reference_text)) if reference_text else []

        # Altura de línea de referencia (Salto 4 para normalizar anchos, y Salto 3
        # para ordenar las cajas por renglón).
        med_h = float(np.median([fb.h for fb in valid_fused])) if valid_fused else 1.0
        med_h = med_h or 1.0

        # Pre-pass: voto de labelers por caja (se reutiliza en el loop y, si la
        # alineación es DP, para construir el mapa caja→char esperado).
        box_votes: list[tuple] = []
        for bi in range(len(valid_fused)):
            cp = {name: preds[bi] for name, preds in all_preds.items()
                  if bi < len(preds)}
            if cp:
                _c, _lc, _hc = vote(cp, self.config.labeler_voting)
            else:
                _c, _lc, _hc = "?", None, False
            _c = (_c or "?").strip()
            _c = _c[0] if _c else "?"
            box_votes.append((_c, _lc, _hc))

        # Salto 3 — mapa caja→carácter esperado: posicional (default) o DP global.
        expected_map = self._build_expected_map(valid_fused, ref_chars, med_h, box_votes)

        temp_dir = _config.TIPOGRAFIA_DIR / "_temp_extract"
        temp_dir.mkdir(parents=True, exist_ok=True)
        # F10-B — higiene de orphans. Con el pipeline activo por defecto (F6) el
        # path legacy _run (que purgaba al inicio) ya no corre, así que sin esto
        # los temporales de extracciones abandonadas (no guardadas) se acumularían
        # sin límite. Misma estrategia que el legacy: cada extracción reemplaza a
        # la anterior en la UI (self._extracted = glyphs), así que purgar los
        # PNG sueltos previos al empezar es seguro. El cleanup selectivo de
        # save_glyphs_to_bank sigue borrando solo los que SÍ se guardaron.
        from core.inkcore.glyph_ingest import purge_temp_pngs
        purge_temp_pngs(temp_dir)

        glyphs: list[GlyphEntry] = []
        boxes: list[list[int]] = []  # Salto 0 — caja [x,y,w,h] por glifo aceptado
        accepted_hashes: list[str] = []  # Salto 2 — hash perceptual por glifo
        debug_accepted: list[tuple] = []
        debug_discarded: list[tuple] = []
        # Salto 4 — muestras de ancho de glifos VERIFICADOS (consenso+match) que
        # calibran wf().
        wf_samples: list[tuple[str, float]] = []

        for i, (fb, crop) in enumerate(zip(valid_fused, crops, strict=False)):
            # Voto pre-computado (ya normalizado a 1 char) — ver pre-pass arriba.
            char, label_conf, has_consensus = box_votes[i]

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

            # Quality rica del extractor (sobre el PIL en memoria, sin re-leer disco).
            # align_score=agreement_score → glifos vistos por más detectores
            # ganan un pequeño boost al ponderar la alineación interna.
            quality = assess_quality(crop, align_score=fb.agreement_score)
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

            # F10-A — guardar a disco SOLO los glifos que ya pasaron TODOS los
            # filtros (confianza, letters_only, calidad). Antes se guardaba cada
            # crop aquí arriba y luego se descartaba por calidad, dejando PNGs
            # huérfanos en el temp dir.
            safe = char if (char.isalnum() or char == "?") else f"punct_{ord(char)}"
            out_path = temp_dir / f"{safe}_{i:04d}.png"
            try:
                crop.save(str(out_path))
            except Exception:
                continue

            # F4 — Gold sólo si está VERIFICADO: hubo consenso entre labelers y la
            # predicción coincide con el char esperado de la referencia. Sin
            # verificación el tope es Silver, por alta que sea la calidad.
            expected = expected_map.get(i)
            verified = is_verified(char, expected, has_consensus)
            tier = classify_tier_verified(final_q, verified)
            # Salto 4 — solo aprendemos anchos de glifos VERIFICADOS (alta
            # confianza); el char es el confirmado y la caja es fiable.
            if verified and char.isalnum():
                wf_samples.append((char, fb.w / med_h))
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
            boxes.append([int(fb.x), int(fb.y), int(fb.w), int(fb.h)])
            # Salto 2 — hash perceptual (mismo _dhash alpha-aware que usa el banco)
            # para el consenso entre instancias del mismo char.
            try:
                from core.inkcore.bank_hashing import _dhash
                accepted_hashes.append(_dhash(crop.convert("RGBA")))
            except Exception:
                accepted_hashes.append("")
            debug_accepted.append((fb, crop, char, label_conf))

        # Salto 2 — consenso entre instancias del mismo char: baja de tier las
        # outliers (mala segmentación) aunque hayan pasado calidad+verificación.
        try:
            from core.inkcore.glyph_consensus import demote_session_outliers
            n_dem = demote_session_outliers(glyphs, accepted_hashes)
            if n_dem:
                stats["outliers_demoted"] = n_dem
        except Exception as exc:
            logger.debug("consenso outliers falló: %s", exc)

        stats["glyphs_accepted"] = len(glyphs)
        stats["glyphs_discarded"] = len(debug_discarded)
        # Salto 4 — persistir las muestras de ancho de los glifos verificados.
        if wf_samples:
            try:
                from core.inkcore import wf_calibration
                wf_calibration.record_many(wf_samples)
                stats["wf_samples_learned"] = len(wf_samples)
            except Exception as exc:
                logger.debug("wf_calibration record falló: %s", exc)
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
            boxes=boxes,
            debug_image_path=debug_path,
            stats=stats,
            timings_ms=timings,
        )

"""
GlyphExtractor — pipeline de extracción profesional para Huevonitis 4.

Mejoras sobre v2:
  • Normalización de iluminación (background subtraction morfológico)
  • Thresholding múltiple con votación: Otsu + Adaptativo + Sauvola
  • Corrección de perspectiva de 4 puntos (fotos inclinadas)
  • Deskew mejorado: HoughLines + projection-profile fallback
  • Eliminación de líneas de cuaderno preservando trazos
  • Adjuntar componentes flotantes (puntos de i, acentos, tilde de ñ, barras de t)
  • Alineación DP con merge-2 y merge-3 (trazos muy fragmentados)
  • Split de cajas anchas por valles de proyección vertical
  • RGBA anti-aliased (bordes suaves via Gaussian + distance transform)
  • Quality scoring mejorado: ancho de trazo (distance transform) + alineación
  • Doble hash perceptual (8x8 + 16x16) para deduplicación más precisa
  • get_preprocessed_preview() para mostrar resultado del pre-proceso en UI
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import config
from core.models import GlyphEntry

logger = logging.getLogger(__name__)


def _purge_temp_pngs(temp_dir: Path) -> int:
    """Borra los PNG residuales de _temp_extract antes de una extracción nueva.

    Cada extracción reemplaza a la anterior (el extractor_tab hace
    self._extracted = glyphs, no acumula). Los temporales de una extracción que
    no se guardó quedan huérfanos y solo acumulan disco — el cleanup selectivo
    de save_glyphs_to_bank solo borra los que SÍ se guardaron. Limpiar aquí, al
    inicio, evita que crezcan sin límite. (El bulk capture usa otro directorio.)
    """
    removed = 0
    for png in temp_dir.glob("*.png"):
        try:
            png.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("_purge_temp_pngs: no se pudo borrar %s: %s", png, exc)
    if removed:
        logger.info("_purge_temp_pngs: %d temporal(es) huérfano(s) descartado(s)", removed)
    return removed

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import pytesseract
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False

# ── Constantes ─────────────────────────────────────────────────────
MIN_COMP_AREA = 10    # componentes más pequeños que esto son ruido
MIN_CHAR_W = 2
MIN_CHAR_H = 3
MAX_DESKEW_DEG = 15.0
CHAR_PAD = 6
TARGET_LONG = 2200
QUALITY_MIN = 0.18    # umbral mínimo por defecto (más permisivo para escritura real)
LINE_THRESHOLD_F = 0.004   # fracción del ancho usada como umbral de línea
MIN_BAND_H = 5             # altura mínima de banda de línea en píxeles


# ── Estructuras ────────────────────────────────────────────────────
@dataclass
class ExtractionOptions:
    remove_lines: bool = True
    brightness: float = 0.0
    contrast: float = 0.0
    rotation_deg: float = 0.0
    min_quality: float = QUALITY_MIN
    max_per_char: int = 10
    # Pipeline ensemble — F6: ACTIVADO por defecto. El ensemble (detectores +
    # labelers + voting con consenso) es el camino que verifica cada glifo; el
    # legacy queda como fallback automático si el pipeline falla o da 0 glifos.
    use_pipeline: bool = True
    pipeline_config: "object | None" = None
    # Quinta tanda Paso 2 — override manual de orientación (0/90/180/270). Si es
    # None, se intenta OSD por contenido (requiere osd.traineddata).
    manual_orientation: "int | None" = None


class BBox:
    __slots__ = ("h", "w", "x", "y")

    def __init__(self, x: int, y: int, w: int, h: int):
        self.x = int(x)
        self.y = int(y)
        self.w = int(max(1, w))
        self.h = int(max(1, h))

    @property
    def x2(self) -> int: return self.x + self.w
    @property
    def y2(self) -> int: return self.y + self.h

    def area(self) -> int: return self.w * self.h
    def cx(self) -> float: return self.x + self.w / 2
    def cy(self) -> float: return self.y + self.h / 2


_BBox = BBox  # backward compat alias

# ── Orquestación de alineación + pipeline (mixins separados) ───────
# El hash perceptual (extractor_hashing) lo consume directamente el
# ExtractionPipelineMixin; ya no se re-exporta desde aquí.
from core.inkcore.extractor_align_mixin import AlignmentMixin
from core.inkcore.extractor_pipeline_mixin import ExtractionPipelineMixin


# ── Extractor principal ────────────────────────────────────────────
class GlyphExtractor(ExtractionPipelineMixin, AlignmentMixin):

    def __init__(self):
        # Delegados de preprocesamiento (Fase 4A — extractor refactor)
        from core.inkcore.extractor_preprocess import ImagePreprocessor
        from core.inkcore.extractor_segments import SegmentDetector
        self._preprocessor = ImagePreprocessor()
        self._seg_detector = SegmentDetector()
        # Última corrida del pipeline ensemble (None si solo se usó legacy).
        # Permite a la UI leer stats, timings y debug_image_path tras extraer.
        self._last_ensemble_result: "object | None" = None
        # Detector de glifos opcional — se inicializa desde config.GLYPH_DETECTOR.
        self._detector = None
        try:
            det_name = getattr(config, "GLYPH_DETECTOR", "classic_cv")
            if det_name != "classic_cv":
                from core.inkcore import glyph_detectors as _gd
                det = _gd.get_detector(det_name)
                if det.available:
                    self._detector = det
                    logger.info(f"GlyphExtractor usando detector: {det_name}")
                else:
                    logger.warning(
                        f"Detector '{det_name}' no disponible ({det.install_hint()}); "
                        "usando pipeline clásico"
                    )
        except Exception as exc:
            logger.warning(f"No se pudo cargar el detector de glifos: {exc}")

        # Clasificador de caracteres (juez de cortes por CNN) — opcional.
        self._char_classifier = None
        self.reload_char_classifier()

    def reload_char_classifier(self) -> bool:
        """(Re)carga el clasificador CNN según config.USE_CNN_ALIGN / H4_CNN_ALIGN.

        Permite togglear la IA en vivo desde la UI sin recrear el extractor. Se
        activa sólo si el flag está on Y el modelo entrenado está presente; si no,
        queda None y el alineador clásico sigue intacto. Devuelve True si quedó
        activo.
        """
        self._char_classifier = None
        try:
            import os
            use_cnn = (os.environ.get("H4_CNN_ALIGN", "") == "1"
                       or getattr(config, "USE_CNN_ALIGN", False))
            if use_cnn:
                from core.inkcore.ai.char_cnn import EMNISTCharClassifier
                clf = EMNISTCharClassifier()
                if clf.available:
                    self._char_classifier = clf
                    logger.info("GlyphExtractor: clasificador CNN activo (juez de cortes)")
                else:
                    logger.info("GlyphExtractor: CNN solicitado pero sin modelo entrenado")
        except Exception as exc:
            logger.warning(f"No se pudo cargar el clasificador CNN: {exc}")
        return self._char_classifier is not None

    def extract_from_image(
        self,
        image_path: str,
        reference_text: str,
        options: ExtractionOptions | None = None,
    ) -> list[GlyphEntry]:
        opts = options or ExtractionOptions()
        # Reiniciar metadata del ensemble en cada extracción nueva.
        self._last_ensemble_result = None
        if opts.use_pipeline:
            try:
                from core.inkcore.extraction_pipeline import (
                    GlyphExtractionPipeline, PipelineConfig,
                )
                cfg = opts.pipeline_config or PipelineConfig()
                pipeline = GlyphExtractionPipeline(cfg)
                result = pipeline.extract(image_path, reference_text)
                self._last_ensemble_result = result
                if result.glyphs:
                    return result.glyphs
                # F6 — fallback por 0 glifos: si el ensemble no extrajo nada
                # (p.ej. ningún labeler instalado o todo descartado), caemos al
                # path legacy en vez de devolver vacío.
                logger.info(
                    "Pipeline ensemble devolvió 0 glifos; cayendo a legacy"
                )
            except Exception as exc:
                logger.error("Pipeline ensemble falló, cayendo a legacy: %s", exc,
                             exc_info=True)
                # Caer al flujo legacy si la pipeline falla

        if not CV2_OK or not PIL_OK:
            logger.warning("cv2/Pillow no disponibles")
            return []
        if not Path(image_path).exists():
            logger.warning(f"Imagen no existe: {image_path}")
            return []
        try:
            return self._run(image_path, reference_text, opts)
        except Exception as exc:
            logger.error(f"Error en extracción: {exc}", exc_info=True)
            return []

    def compare_strategies(
        self,
        image_path: str,
        reference_text: str,
        options: ExtractionOptions | None = None,
    ) -> dict:
        """Ejecuta las 5 estrategias de segmentación sobre la primera línea detectada.

        Útil para tuning/debug desde la UI: la respuesta es el dict crudo de
        `_test_all_strategies` con un campo extra `_meta` describiendo qué
        línea se usó (índice, ancho, ref) y cualquier error fatal.

        Devuelve {} si no se pudo preprocesar o no hay línea/ref aprovechable.
        """
        meta: dict = {}
        if not CV2_OK or not PIL_OK or not Path(image_path).exists():
            return {"_meta": {"error": "cv2/Pillow no disponibles o imagen inexistente"}}
        try:
            opts = options or ExtractionOptions()
            img = cv2.imread(image_path)
            if img is None:
                return {"_meta": {"error": "no se pudo leer la imagen"}}
            img = self._apply_manual(img, opts)
            img = self._scale(img)
            img = self._autocrop(img)
            img, _ = self._deskew(img)
            gray, _, clean = self._full_preprocess(img, opts)
            line_boxes = self._find_line_boxes(clean)
            if not line_boxes:
                return {"_meta": {"error": "no se detectaron líneas en la imagen"}}

            ref_lines = self._prepare_ref_lines(reference_text, line_boxes)
            best_idx = 0
            for i, ln in enumerate(ref_lines):
                if ln and len(ln.replace(" ", "")) >= 2:
                    best_idx = i
                    break
            if best_idx >= len(ref_lines):
                return {"_meta": {"error": "ninguna línea de referencia válida"}}

            lb = line_boxes[best_idx]
            ref_line = ref_lines[best_idx]
            chars = [ch for ch in ref_line if ch != " "]
            if len(chars) < 2:
                return {"_meta": {"error": f"línea {best_idx} con muy pocos chars"}}

            line_mask = clean[lb.y:lb.y + lb.h, lb.x:lb.x + lb.w]
            band_binary = line_mask
            band_img = img[lb.y:lb.y + lb.h, lb.x:lb.x + lb.w]

            vpp = np.sum(band_binary > 0, axis=0).astype(np.float32)
            ink_cols = np.where(vpp > 0)[0]
            if len(ink_cols) == 0:
                return {"_meta": {"error": "banda sin tinta"}}
            x_min = int(ink_cols[0])
            x_max = int(ink_cols[-1]) + 1

            results = self._test_all_strategies(
                band_img, band_binary, x_min, x_max,
                len(chars), chars, line_mask,
            )
            meta = {
                "line_index": best_idx,
                "line_count": len(line_boxes),
                "line_w": int(lb.w),
                "line_h": int(lb.h),
                "ref_line": ref_line,
                "n_chars": len(chars),
            }
            results["_meta"] = meta
            return results
        except Exception as exc:
            logger.error("compare_strategies error: %s", exc, exc_info=True)
            return {"_meta": {"error": str(exc)}}

    def get_preprocessed_preview(
        self,
        image_path: str,
        options: ExtractionOptions | None = None,
    ) -> Optional["Image.Image"]:
        """Devuelve imagen lado a lado: original | máscara limpia (para UI)."""
        if not CV2_OK or not PIL_OK or not Path(image_path).exists():
            return None
        try:
            opts = options or ExtractionOptions()
            img = cv2.imread(image_path)
            if img is None:
                return None
            img = self._apply_manual(img, opts)
            img = self._scale(img)
            img = self._autocrop(img)
            img, _ = self._deskew(img)
            _, _, clean = self._full_preprocess(img, opts)
            left = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            right = cv2.cvtColor(clean, cv2.COLOR_GRAY2RGB)
            # Resize both to same height
            h = min(left.shape[0], 500)
            def resize_h(a, target_h):
                s = target_h / a.shape[0]
                return cv2.resize(a, (int(a.shape[1] * s), target_h))
            combined = np.hstack([resize_h(left, h), resize_h(right, h)])
            return Image.fromarray(combined)
        except Exception as exc:
            logger.warning(f"Preview falló: {exc}")
            return None

    # ── Pipeline legacy delegado al ExtractionPipelineMixin ──────────
    #   _run, _clean_ref, _prepare_ref_lines y _extract_pass viven ahora
    #   en ExtractionPipelineMixin (extractor_pipeline_mixin.py) para
    #   mantener este archivo por debajo de ~420 líneas.

    # ── Ajustes manuales ───────────────────────────────────────────

    def _apply_manual(self, img: np.ndarray, opts: ExtractionOptions) -> np.ndarray:
        return self._preprocessor.apply_options(img, opts)

    def _scale(self, img: np.ndarray) -> np.ndarray:
        return self._preprocessor.scale(img)

    def _autocrop(self, img: np.ndarray) -> np.ndarray:
        return self._preprocessor.autocrop(img)

    def _four_point_transform(self, img: np.ndarray, pts: np.ndarray) -> np.ndarray | None:
        return self._preprocessor._four_point_transform(img, pts)

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        from core.inkcore.extractor_preprocess import ImagePreprocessor
        return ImagePreprocessor._order_points(pts)

    def _deskew(self, img: np.ndarray) -> tuple[np.ndarray, float]:
        return self._preprocessor.deskew(img)

    def _estimate_skew(self, mask: np.ndarray, width: int) -> float | None:
        return self._preprocessor._estimate_skew(mask, width)

    def _full_preprocess(
        self, img: np.ndarray, opts: ExtractionOptions
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self._preprocessor.full_preprocess(img, opts)

    @staticmethod
    def _normalize_illumination(gray: np.ndarray) -> np.ndarray:
        from core.inkcore.extractor_preprocess import ImagePreprocessor
        return ImagePreprocessor.normalize_illumination(gray)

    @staticmethod
    def _sauvola(gray: np.ndarray, window: int = 25, k: float = 0.20) -> np.ndarray:
        from core.inkcore.extractor_preprocess import ImagePreprocessor
        return ImagePreprocessor.sauvola(gray, window=window, k=k)

    @staticmethod
    def _filtered_mask(mask: np.ndarray) -> np.ndarray:
        from core.inkcore.extractor_preprocess import ImagePreprocessor
        return ImagePreprocessor.filtered_mask(mask)

    def _remove_lines(self, mask: np.ndarray) -> np.ndarray:
        return self._preprocessor.remove_lines(mask)

    # ── Detección de líneas — delegado a SegmentDetector ─────────

    def _find_line_boxes(self, mask: np.ndarray) -> list[BBox]:
        return self._seg_detector.find_line_boxes(mask)

    # ── Hints OCR delegados a extractor_ocr_hints ────────────────

    def _get_detector_boundaries(self, line_mask: np.ndarray) -> list[int]:
        from core.inkcore.extractor_ocr_hints import get_detector_boundaries
        return get_detector_boundaries(self._detector, line_mask)

    def _tesseract_boundaries(self, line_mask: np.ndarray) -> list[int]:
        from core.inkcore.extractor_ocr_hints import tesseract_boundaries
        return tesseract_boundaries(line_mask)

    # ── Alineación delegada al AlignmentMixin (extractor_align_mixin) ──
    #   _align_pos, _align_*, _segment_words, _find_word_gaps, _wf y
    #   _test_all_strategies viven ahora en AlignmentMixin para mantener
    #   este archivo por debajo de ~420 líneas.

    # ── Glyph ops delegados a extractor_glyph_ops ─────────────────

    @staticmethod
    def _refine_char_region(line_mask, x1, x2):
        from core.inkcore.extractor_glyph_ops import refine_char_region
        return refine_char_region(line_mask, x1, x2)

    @staticmethod
    def _tight_crop(mask, padding: int = 3):
        from core.inkcore.extractor_glyph_ops import tight_crop
        return tight_crop(mask, padding)

    @staticmethod
    def _to_rgba_smooth(mask):
        from core.inkcore.extractor_glyph_ops import to_rgba_smooth
        return to_rgba_smooth(mask)

    @staticmethod
    def _assess_quality(img, align_score: float = 0.5):
        from core.inkcore.extractor_glyph_ops import assess_quality
        return assess_quality(img, align_score)

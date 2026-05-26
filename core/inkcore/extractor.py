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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import config
from core.models import GlyphEntry

logger = logging.getLogger(__name__)

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
    # Pipeline ensemble (B8) — False por defecto para mantener backward compat
    use_pipeline: bool = False
    pipeline_config: "object | None" = None


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

# ── Hash perceptual (delegado a extractor_hashing) ─────────────────
from core.inkcore.extractor_hashing import (
    avg_hash, hamming,
    dual_hash as _dual_hash,
    dual_dist as _dual_dist,
)


# ── Extractor principal ────────────────────────────────────────────
class GlyphExtractor:

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
                return result.glyphs
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

    # ── Pipeline principal ─────────────────────────────────────────

    def _run(self, path: str, ref_text: str, opts: ExtractionOptions) -> list[GlyphEntry]:
        img = cv2.imread(path)
        if img is None:
            return []

        img = self._apply_manual(img, opts)
        img = self._scale(img)
        img = self._autocrop(img)
        img, skew = self._deskew(img)
        if abs(skew) > 0.3:
            logger.debug(f"Corrección de inclinación: {skew:.2f}°")

        gray, _, clean = self._full_preprocess(img, opts)

        line_boxes = self._find_line_boxes(clean)
        if not line_boxes:
            logger.warning("No se detectaron líneas. Intentando con Otsu simple…")
            _, alt = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            alt = cv2.morphologyEx(alt, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            alt = self._filtered_mask(alt)
            line_boxes = self._find_line_boxes(alt)
            clean = alt
            if not line_boxes:
                logger.error("Imposible detectar líneas de texto en la imagen")
                return []

        median_line_h = float(np.median([lb.h for lb in line_boxes]))
        logger.info(f"Líneas detectadas: {len(line_boxes)}, altura mediana: {median_line_h:.1f}px")
        for li, lb in enumerate(line_boxes):
            logger.info(f"  banda {li}: x={lb.x} y={lb.y} w={lb.w} h={lb.h}")

        ref_lines = self._prepare_ref_lines(ref_text, line_boxes)
        logger.info(f"Líneas de referencia ({len(ref_lines)}): {ref_lines}")

        temp_dir = config.TIPOGRAFIA_DIR / "_temp_extract"
        temp_dir.mkdir(parents=True, exist_ok=True)

        glyphs = self._extract_pass(clean, line_boxes, ref_lines, median_line_h,
                                    opts, temp_dir)

        # Reintento con parámetros relajados si no se extrajo nada
        if not glyphs:
            logger.warning("0 glifos en primera pasada. Reintentando con parámetros relajados…")
            relaxed = ExtractionOptions(
                remove_lines=opts.remove_lines,
                brightness=opts.brightness,
                contrast=opts.contrast,
                rotation_deg=opts.rotation_deg,
                min_quality=max(0.12, opts.min_quality - 0.10),
                max_per_char=opts.max_per_char,
            )
            # Intentar también con máscara Otsu pura si la limpia está muy vacía
            _, alt_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            alt_mask = cv2.morphologyEx(alt_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            alt_mask = self._filtered_mask(alt_mask)
            alt_lines = self._find_line_boxes(alt_mask)
            use_mask = alt_mask if alt_lines else clean
            use_lines = alt_lines if alt_lines else line_boxes
            use_med = float(np.median([lb.h for lb in use_lines]))
            glyphs = self._extract_pass(use_mask, use_lines, ref_lines, use_med,
                                        relaxed, temp_dir)
            if glyphs:
                logger.info(f"Reintento exitoso: {len(glyphs)} glifos")

        logger.info(f"Extraídos {len(glyphs)} glifos de {len(line_boxes)} líneas detectadas")
        return glyphs

    # ── Preparación del texto de referencia ───────────────────────────

    @staticmethod
    def _clean_ref(text: str) -> str:
        """Quita separadores comunes (comas, puntos y coma, pipes) y espacios extra."""
        cleaned = re.sub(r'[,;|]+', ' ', text)
        # Colapsar espacios múltiples
        cleaned = re.sub(r'  +', ' ', cleaned)
        return cleaned.strip()

    def _prepare_ref_lines(self, ref_text: str, line_boxes: list["BBox"]) -> list[str]:
        """Limpia el texto de referencia y lo divide entre los renglones detectados."""
        # Limpiar separadores en cada línea del texto
        raw_lines = [self._clean_ref(ln) for ln in ref_text.splitlines()]
        raw_lines = [ln for ln in raw_lines if ln]
        if not raw_lines:
            raw_lines = [self._clean_ref(ref_text)]

        n_bands = len(line_boxes)

        # Si ya hay suficientes líneas de referencia, usarlas directamente
        if len(raw_lines) >= n_bands:
            return raw_lines[:n_bands]

        # Si hay más bandas que líneas de referencia:
        # distribuir todos los caracteres del texto entre las bandas
        # de forma proporcional al ancho de cada banda
        all_chars = "".join(ln.replace(" ", "") for ln in raw_lines)
        if not all_chars:
            return raw_lines

        total_w = max(1, sum(lb.w for lb in line_boxes))
        result: list[str] = []
        start = 0
        for i, lb in enumerate(line_boxes):
            if i == n_bands - 1:
                result.append(all_chars[start:])
            else:
                n = max(1, round(len(all_chars) * lb.w / total_w))
                result.append(all_chars[start:start + n])
                start += n
        # Asegurarse de que no haya líneas vacías
        result = [r for r in result if r]
        return result or raw_lines

    def _extract_pass(
        self,
        clean: np.ndarray,
        line_boxes: list[BBox],
        ref_lines: list[str],
        median_line_h: float,
        opts: "ExtractionOptions",
        temp_dir: Path,
    ) -> list[GlyphEntry]:
        """Pasada de extracción sobre una máscara y bandas dadas."""
        glyphs: list[GlyphEntry] = []
        seen: dict[str, list[tuple[str, str]]] = {}
        counts: dict[str, int] = {}

        for li, lb in enumerate(line_boxes):
            if li >= len(ref_lines):
                break
            ref_line = ref_lines[li]
            if not ref_line:
                continue

            lx, ly = lb.x, lb.y
            line_mask = clean[ly:ly + lb.h, lx:lx + lb.w]

            if line_mask.size == 0 or not np.any(line_mask > 0):
                logger.debug(f"Línea {li}: máscara vacía")
                continue

            # Para líneas con poca tinta (< 2%), aplicar CLAHE adicional ligero
            # que ayuda a recuperar escritura tenue o con poco contraste.
            line_ink_ratio = float(np.sum(line_mask > 0)) / max(1, line_mask.size)
            if line_ink_ratio < 0.02 and CV2_OK:
                clahe_line = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
                line_mask = clahe_line.apply(line_mask)
                _, line_mask = cv2.threshold(line_mask, 127, 255, cv2.THRESH_BINARY)

            # Alineación por partición VPP (no usa blobs — divide directamente)
            aligned = self._align_pos([], ref_line, median_line_h, line_mask)

            for gbox, char, align_score in aligned:
                if counts.get(char, 0) >= opts.max_per_char:
                    continue

                # Refinar límites al blob dominante + diacríticos (punto de i, acentos, ñ)
                rx1, ry1, rx2, ry2 = self._refine_char_region(
                    line_mask, gbox.x, gbox.x2
                )
                # Verificar que la región refinada contiene tinta suficiente.
                # Si tiene menos del 5% de la tinta esperada para el char, advertir.
                ref_ink = float(np.sum(line_mask[ry1:ry2, rx1:rx2] > 0))
                ref_area = max(1, (ry2 - ry1) * max(1, rx2 - rx1))
                ref_cov = ref_ink / ref_area
                # Tinta esperada mínima: 5% del área del glyph
                if ref_cov < 0.05:
                    logger.warning(
                        f"Región de '{char}' muy vacía (cov={ref_cov:.3f}) "
                        f"— posible boundary incorrecto en x={gbox.x}-{gbox.x2}"
                    )
                # Recalcular align_score desde la región refinada (más precisa)
                align_score = max(align_score, min(1.0, ref_cov / 0.18))

                pad = CHAR_PAD
                y1 = max(0, ry1 + ly - pad)
                y2 = min(clean.shape[0], ry2 + ly + pad)
                x1 = max(0, rx1 + lx - pad)
                x2 = min(clean.shape[1], rx2 + lx + pad)
                crop = clean[y1:y2, x1:x2]
                if crop.size == 0:
                    continue

                crop = self._tight_crop(crop, 3)
                if crop is None:
                    continue

                pil_img = self._to_rgba_smooth(crop)
                quality = self._assess_quality(pil_img, align_score)
                if quality["quality_score"] < opts.min_quality:
                    continue

                dhash = _dual_hash(pil_img)
                prev = seen.setdefault(char, [])
                if prev:
                    best_d = min(_dual_dist(dhash, h) for h in prev)
                    # Umbral más alto para aceptar variantes naturales de cada char.
                    # Los chars estrechos siguen con umbral menor para evitar duplicados
                    # obvios, pero caracteres complejos (a, g) obtienen más tolerancia.
                    narrow = char in ".,;:!¡|`'iltI1íì"
                    strict = 4 if narrow else 6
                    if best_d <= strict:
                        continue
                prev.append(dhash)

                safe = char if char.isalnum() else f"punct_{ord(char)}"
                out_path = temp_dir / f"{safe}_{len(glyphs):04d}.png"
                try:
                    pil_img.save(str(out_path))
                except Exception as _save_err:
                    logger.warning(f"No se pudo guardar glifo temporal '{char}' en {out_path}: {_save_err}")
                    continue

                qs = quality["quality_score"]
                tier = "Gold" if qs > 0.75 else "Silver" if qs > 0.48 else "Bronze"
                glyphs.append(GlyphEntry(
                    char=char,
                    image_path=str(out_path),
                    quality_score=round(qs, 3),
                    tier=tier,
                    ink_coverage=round(quality["coverage"], 3),
                    index=len(glyphs),
                ))
                counts[char] = counts.get(char, 0) + 1

        return glyphs

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

    # ── Alineación delegada a extractor_alignment ────────────────

    @staticmethod
    def _wf(ch):
        from core.inkcore.extractor_alignment import wf
        return wf(ch)

    def _align_inkflow(self, vpp, x_min, x_max, chars):
        from core.inkcore.extractor_alignment import align_inkflow
        return align_inkflow(vpp, x_min, x_max, chars)

    def _align_vpp_only(self, vpp, x_min, x_max, n):
        from core.inkcore.extractor_alignment import align_vpp_only
        return align_vpp_only(vpp, x_min, x_max, n)

    def _align_uniform(self, x_min, x_max, n):
        from core.inkcore.extractor_alignment import align_uniform
        return align_uniform(x_min, x_max, n)

    def _align_dp_energy(self, vpp, x_min, x_max, n):
        from core.inkcore.extractor_alignment import align_dp_energy
        return align_dp_energy(vpp, x_min, x_max, n)

    def _align_cc_first(self, binary_band, x_min, x_max, n):
        from core.inkcore.extractor_alignment import align_cc_first
        return align_cc_first(binary_band, x_min, x_max, n)

    def _align_hybrid_v2(self, vpp, binary_band, x_min, x_max, n, chars):
        from core.inkcore.extractor_alignment import align_hybrid_v2
        return align_hybrid_v2(vpp, binary_band, x_min, x_max, n, chars)

    def _find_word_gaps(self, vpp, x_min, x_max, words):
        from core.inkcore.extractor_alignment import find_word_gaps
        return find_word_gaps(vpp, x_min, x_max, words)

    def _segment_words(
        self,
        words: list[str],
        word_bounds: list[int],
        line_mask: np.ndarray,
        line_h: float,
    ) -> list[tuple["BBox", str, float]]:
        """Segmenta cada palabra de forma independiente usando los bounds dados."""
        h, w = line_mask.shape[:2]
        result: list[tuple[BBox, str, float]] = []
        for wi, word in enumerate(words):
            wx1 = word_bounds[wi]
            wx2 = word_bounds[wi + 1]
            word_chars = [ch for ch in word]
            if not word_chars:
                continue
            word_mask = line_mask[:, max(0, wx1):min(w, wx2)]
            if word_mask.size == 0:
                continue
            if len(word_chars) == 1:
                bx = max(0, wx1)
                bw_ = max(1, min(w, wx2) - bx)
                box = BBox(bx, 0, bw_, h)
                ink = float(np.sum(word_mask > 0))
                cov = ink / max(1, h * bw_)
                result.append((box, word_chars[0], min(1.0, max(0.1, cov / 0.18))))
            else:
                # Segmentación recursiva dentro de la palabra
                sub = self._align_pos([], word, line_h, word_mask)
                for box, ch, score in sub:
                    result.append((BBox(box.x + wx1, box.y, box.w, box.h), ch, score))
        return result

    # [testing] ── Benchmark de estrategias delegado ────────────────

    def _test_all_strategies(self, band_img, band_binary, x_min, x_max, n, chars, line_mask):
        from core.inkcore.extractor_strategies import benchmark_all
        return benchmark_all(band_img, band_binary, x_min, x_max, n, chars, line_mask)

    def _align_pos(
        self, boxes: list[BBox], text: str, line_h: float = 30.0,
        line_mask: np.ndarray | None = None,
    ) -> list[tuple[BBox, str, float]]:
        """Pipeline de alineación mejorado: hybrid_v2 primario + 3-etapas como fallback.

        Etapa 1 — hybrid_v2 (InkFlow + búsqueda de mínimo absoluto + verificación CC)
            • Calcula fronteras iniciales con InkFlow (calibrado al ancho real de cada char).
            • Para cada frontera, amplía la búsqueda a ±40 % del ancho promedio y elige
              la columna de MÍNIMA tinta absoluta (no solo "por debajo de umbral").
              Esto maneja mejor los gaps parciales comunes en escritura ligada.
            • Verifica si el corte atraviesa un componente conectado; si sí, desplaza
              ±5 px buscando un gap real entre trazos.

        Fallback — 3 etapas clásicas (InkFlow + VPP snap + Tesseract)
            Se activa cuando hybrid_v2 produce calidad promedio baja (< 0.28).
            Mantiene compatibilidad con la estrategia probada anterior.

        Etapa final — Anclaje Tesseract
            Si Tesseract detectó fronteras de caracteres, las usa para ajustar
            las fronteras finales (aplica tanto a hybrid_v2 como al fallback).
        """
        chars = [ch for ch in text if ch != " "]
        if not chars or line_mask is None or line_mask.size == 0:
            return []

        h, w = line_mask.shape[:2]
        n = len(chars)

        vpp = np.sum(line_mask > 0, axis=0).astype(np.float32)

        ink_cols = np.where(vpp > 0)[0]
        if len(ink_cols) == 0:
            return []
        # Estimación robusta: percentiles 2%/98% para excluir ruido en bordes
        p2_idx = max(0, int(len(ink_cols) * 0.02))
        p98_idx = min(len(ink_cols) - 1, int(len(ink_cols) * 0.98))
        x_min = int(ink_cols[p2_idx])
        x_max = int(ink_cols[p98_idx]) + 1
        total_span = max(1, x_max - x_min)
        char_w_avg = total_span / n

        # VPP suavizado (común para ambas rutas y para Tesseract snap)
        ks = max(3, int(w / max(1, n) * 0.12))
        ks = ks if ks % 2 == 1 else ks + 1
        vpp_s = cv2.GaussianBlur(vpp.reshape(1, -1), (1, ks), 0).flatten()
        vpp_max = float(np.max(vpp_s[x_min:x_max])) if x_max > x_min else 1.0
        min_cw = max(1, int(char_w_avg * 0.20))

        # ── Pre-alineación por palabras (cuando el texto tiene espacios) ──
        # Segmentar primero por gaps de palabra evita que un error en el char 3
        # desplace todos los chars siguientes. Cada palabra se procesa sola.
        words = [w_tok for w_tok in text.split(" ") if w_tok]
        if len(words) > 1:
            word_bounds = self._find_word_gaps(vpp, x_min, x_max, words)
            if len(word_bounds) == len(words) + 1:
                word_result = self._segment_words(words, word_bounds, line_mask, line_h)
                if len(word_result) == n:
                    logger.debug(
                        f"Word-gap align: {len(words)} palabras, "
                        f"{n} chars totales"
                    )
                    return word_result
                # Si el conteo no cuadra, caer al pipeline completo

        # ── Etapa 1: hybrid_v2 (primario) ─────────────────────────
        primary_bounds = self._align_hybrid_v2(vpp, line_mask, x_min, x_max, n, chars)

        # Evaluar calidad rápida del primario para decidir si usar fallback
        def _quick_avg_quality(bounds: list[int]) -> float:
            scores: list[float] = []
            for i in range(len(bounds) - 1):
                x1b = max(0, bounds[i])
                x2b = min(w, bounds[i + 1])
                if x2b <= x1b:
                    continue
                ink = float(np.sum(line_mask[:, x1b:x2b] > 0))
                area = max(1, h * (x2b - x1b))
                cov = ink / area
                scores.append(min(1.0, max(0.0, cov / 0.18)))
            return float(np.mean(scores)) if scores else 0.0

        use_bounds = primary_bounds
        primary_q = _quick_avg_quality(primary_bounds)

        if primary_q < 0.28:
            # ── Fallback: 3 etapas clásicas ───────────────────────
            logger.debug(
                f"hybrid_v2 calidad baja ({primary_q:.3f}) — usando fallback InkFlow+VPP"
            )
            fallback_bounds = self._align_inkflow(vpp, x_min, x_max, chars)
            gap_thr = vpp_max * 0.12
            sw = max(2, int(char_w_avg * 0.30))
            refined_fb: list[int] = [fallback_bounds[0]]
            for i in range(1, n):
                eb = fallback_bounds[i]
                prev = refined_fb[-1]
                lo = max(prev + min_cw, eb - sw)
                hi = min(w, eb + sw + 1)
                if lo < hi:
                    seg = vpp_s[lo:hi]
                    min_i = int(np.argmin(seg))
                    min_v = float(seg[min_i])
                    if min_v < gap_thr:
                        best_x = max(prev + 1, lo + min_i)
                    else:
                        best_x = max(prev + 1, eb)
                else:
                    best_x = max(prev + 1, eb)
                refined_fb.append(best_x)
            refined_fb.append(fallback_bounds[-1])
            for i in range(1, len(refined_fb)):
                if refined_fb[i] <= refined_fb[i - 1]:
                    refined_fb[i] = refined_fb[i - 1] + 1
            fallback_q = _quick_avg_quality(refined_fb)
            # Usar el mejor de los dos
            if fallback_q >= primary_q:
                use_bounds = refined_fb
                logger.debug(
                    f"Fallback InkFlow+VPP elegido ({fallback_q:.3f} ≥ {primary_q:.3f})"
                )

        # ── Etapa final: Anclaje con Tesseract + detector alternativo ────
        # Optimización: Tesseract sobre línea corta no aporta y cuesta ~150ms
        # (escalar + binarizar + 2× PSM). Saltamos para n < 4 (no hay márgenes
        # útiles para hacer snap) o si la calidad primaria ya es alta (>0.55).
        if n < 4 or primary_q > 0.55:
            tess_bdry: list[int] = []
        else:
            tess_bdry = self._tesseract_boundaries(line_mask)
        det_bdry = self._get_detector_boundaries(line_mask)
        # Unión de fronteras de ambas fuentes
        all_hints = sorted(set(tess_bdry) | set(det_bdry))
        tess_bdry = all_hints  # reutilizamos variable para el bloque siguiente
        if tess_bdry:
            snap_r = max(3, int(char_w_avg * 0.22))
            final: list[int] = [use_bounds[0]]
            prev = use_bounds[0]
            for i in range(1, n):
                eb = use_bounds[i]
                nearby = [
                    tb for tb in tess_bdry
                    if abs(tb - eb) <= snap_r
                    and prev + min_cw < tb < w
                    and 0 <= tb < len(vpp_s)
                    and float(vpp_s[tb]) < vpp_max * 0.35   # conservador: no aterrizar dentro de trazo
                ]
                if nearby:
                    eb = max(prev + 1,
                             min(nearby, key=lambda tb: abs(tb - eb)))
                final.append(eb)
                prev = eb
            final.append(use_bounds[-1])
        else:
            final = use_bounds

        # Garantizar orden estrictamente creciente
        for i in range(1, len(final)):
            if final[i] <= final[i - 1]:
                final[i] = final[i - 1] + 1

        result: list[tuple[BBox, str, float]] = []
        for i, ch in enumerate(chars):
            x1 = final[i]
            x2 = min(final[i + 1], w)
            bw = max(1, x2 - x1)
            box = BBox(x1, 0, bw, h)
            ink = float(np.sum(line_mask[:, x1:x2] > 0))
            coverage = ink / max(1, h * bw)
            align_score = min(1.0, max(0.1, coverage / 0.18))
            result.append((box, ch, align_score))

        logger.info(
            f"hybrid_v2+tess align '{text[:40]}': span={x_min}-{x_max}px "
            f"char_w_avg={char_w_avg:.1f} primary_q={primary_q:.3f} "
            f"tess_hints={len(tess_bdry)} → {len(result)} regiones"
        )
        for box, ch, _ in result:
            logger.debug(f"  '{ch}' x={box.x}-{box.x+box.w}")
        return result

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

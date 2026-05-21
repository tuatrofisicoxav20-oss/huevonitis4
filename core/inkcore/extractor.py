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
  • Doble hash perceptual (8×8 + 16×16) para deduplicación más precisa
  • get_preprocessed_preview() para mostrar resultado del pre-proceso en UI
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import config
from core.models import GlyphEntry

# Módulos auxiliares extraídos para mejorar la modularidad.
# La API pública de GlyphExtractor permanece sin cambios.
# Estos módulos están disponibles para importación directa si se necesita.
# from core.inkcore.extractor_preprocess import ImagePreprocessor
# from core.inkcore.extractor_segments import SegmentDetector

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


class _BBox:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x: int, y: int, w: int, h: int):
        self.x = int(x); self.y = int(y)
        self.w = int(max(1, w)); self.h = int(max(1, h))

    @property
    def x2(self) -> int: return self.x + self.w
    @property
    def y2(self) -> int: return self.y + self.h

    def area(self) -> int: return self.w * self.h
    def cx(self) -> float: return self.x + self.w / 2
    def cy(self) -> float: return self.y + self.h / 2


# ── Hash perceptual ────────────────────────────────────────────────
def avg_hash(img: "Image.Image", size: int = 16) -> str:
    gray = img.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    px = list(gray.getdata())
    avg = sum(px) / max(1, len(px))
    return "".join("1" if p >= avg else "0" for p in px)


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def _dual_hash(img: "Image.Image") -> tuple[str, str]:
    return avg_hash(img, 8), avg_hash(img, 16)


def _dual_dist(a: tuple[str, str], b: tuple[str, str]) -> float:
    h8 = hamming(a[0], b[0])          # 0-64
    h16 = hamming(a[1], b[1]) / 4.0   # 0-64 normalizado
    return h8 * 0.6 + h16 * 0.4


# ── Extractor principal ────────────────────────────────────────────
class GlyphExtractor:

    def extract_from_image(
        self,
        image_path: str,
        reference_text: str,
        options: Optional[ExtractionOptions] = None,
    ) -> list[GlyphEntry]:
        if not CV2_OK or not PIL_OK:
            logger.warning("cv2/Pillow no disponibles")
            return []
        if not Path(image_path).exists():
            logger.warning(f"Imagen no existe: {image_path}")
            return []
        try:
            return self._run(image_path, reference_text, options or ExtractionOptions())
        except Exception as exc:
            logger.error(f"Error en extracción: {exc}", exc_info=True)
            return []

    def get_preprocessed_preview(
        self,
        image_path: str,
        options: Optional[ExtractionOptions] = None,
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

        gray, raw_mask, clean = self._full_preprocess(img, opts)

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
        import re
        # Eliminar separadores que rodean letras/dígitos (comas/punto-coma usados como listado)
        cleaned = re.sub(r'[,;|]+', ' ', text)
        # Colapsar espacios múltiples
        cleaned = re.sub(r'  +', ' ', cleaned)
        return cleaned.strip()

    def _prepare_ref_lines(self, ref_text: str, line_boxes: list["_BBox"]) -> list[str]:
        """Limpia el texto de referencia y lo divide entre los renglones detectados."""
        # Limpiar separadores en cada línea del texto
        raw_lines = [self._clean_ref(l) for l in ref_text.splitlines()]
        raw_lines = [l for l in raw_lines if l]
        if not raw_lines:
            raw_lines = [self._clean_ref(ref_text)]

        n_bands = len(line_boxes)

        # Si ya hay suficientes líneas de referencia, usarlas directamente
        if len(raw_lines) >= n_bands:
            return raw_lines[:n_bands]

        # Si hay más bandas que líneas de referencia:
        # distribuir todos los caracteres del texto entre las bandas
        # de forma proporcional al ancho de cada banda
        all_chars = "".join(l.replace(" ", "") for l in raw_lines)
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
        line_boxes: list[_BBox],
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
        if abs(opts.rotation_deg) > 0.1:
            h, w = img.shape[:2]
            M = cv2.getRotationMatrix2D((w / 2, h / 2), -opts.rotation_deg, 1.0)
            img = cv2.warpAffine(img, M, (w, h),
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
        if abs(opts.brightness) > 0.5 or abs(opts.contrast) > 0.5:
            alpha = max(0.05, 1.0 + opts.contrast / 100.0)
            beta = opts.brightness
            img = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
        return img

    # ── Escala ─────────────────────────────────────────────────────

    def _scale(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        ls = max(h, w)
        if ls <= TARGET_LONG:
            return img
        s = TARGET_LONG / ls
        return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

    # ── Autocrop + corrección de perspectiva ───────────────────────

    def _autocrop(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        edges = cv2.Canny(blurred, 25, 90)
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (12, 12)))
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return img
        for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            if cv2.contourArea(cnt) < 0.12 * h * w:
                continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.025 * peri, True)
            if len(approx) == 4:
                warped = self._four_point_transform(img, approx.reshape(4, 2))
                if warped is not None:
                    return warped
            x, y, cw, ch = cv2.boundingRect(cnt)
            m = 10
            crop = img[max(0, y-m):min(h, y+ch+m), max(0, x-m):min(w, x+cw+m)]
            if crop.size > 0:
                return crop
        return img

    def _four_point_transform(self, img: np.ndarray, pts: np.ndarray) -> Optional[np.ndarray]:
        try:
            rect = self._order_points(pts.astype(np.float32))
            tl, tr, br, bl = rect
            wA = float(np.linalg.norm(br - bl))
            wB = float(np.linalg.norm(tr - tl))
            hA = float(np.linalg.norm(tr - br))
            hB = float(np.linalg.norm(tl - bl))
            mW = max(1, max(int(wA), int(wB)))
            mH = max(1, max(int(hA), int(hB)))
            if mW < 80 or mH < 80:
                return None
            dst = np.array([[0, 0], [mW-1, 0], [mW-1, mH-1], [0, mH-1]], dtype=np.float32)
            M = cv2.getPerspectiveTransform(rect, dst)
            return cv2.warpPerspective(img, M, (mW, mH),
                                       borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
        except Exception:
            return None

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        d = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(d)]
        rect[3] = pts[np.argmax(d)]
        return rect

    # ── Deskew ─────────────────────────────────────────────────────

    def _deskew(self, img: np.ndarray) -> tuple[np.ndarray, float]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        binary = self._filtered_mask(binary)
        angle = self._estimate_skew(binary, img.shape[1])
        if angle is None or abs(angle) < 0.25:
            return img, 0.0
        if abs(angle) > MAX_DESKEW_DEG:
            logger.warning(f"Inclinación {angle:.1f}° fuera del límite, no se corrige")
            return img, 0.0
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
        return rotated, float(angle)

    def _estimate_skew(self, mask: np.ndarray, width: int) -> Optional[float]:
        edges = cv2.Canny(mask, 50, 150)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=max(50, width // 12))
        if lines is not None:
            angles = []
            for line in lines:
                theta = float(line[0][1])
                a = np.degrees(theta) - 90.0
                if abs(a) <= MAX_DESKEW_DEG:
                    angles.append(a)
            if len(angles) >= 2:
                return float(np.median(angles))
        # Fallback: buscar el ángulo que maximiza varianza de proyección horizontal
        best_angle, best_var = 0.0, -1.0
        for a in np.arange(-MAX_DESKEW_DEG, MAX_DESKEW_DEG + 0.5, 1.0):
            M = cv2.getRotationMatrix2D((mask.shape[1]/2, mask.shape[0]/2), a, 1.0)
            rot = cv2.warpAffine(mask, M, (mask.shape[1], mask.shape[0]))
            proj = np.sum(rot > 0, axis=1, dtype=np.float32)
            v = float(np.var(proj))
            if v > best_var:
                best_var = v
                best_angle = a
        return best_angle if abs(best_angle) > 0.3 else None

    # ── Pre-procesamiento completo ─────────────────────────────────

    def _full_preprocess(
        self, img: np.ndarray, opts: ExtractionOptions
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Normalización de iluminación: dividir por fondo estimado
        gray = self._normalize_illumination(gray)

        # Suavizado muy ligero para reducir ruido de sensor
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        # CLAHE para contraste local adaptativo.
        # El tamaño de tile se ajusta dinámicamente al ancho de la imagen:
        # imágenes muy anchas necesitan tiles más grandes para no ser demasiado
        # granulares y crear artefactos en zonas homogéneas.
        img_w = gray.shape[1]
        tile = max(8, min(32, img_w // 60))
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(tile, tile))
        enhanced = clahe.apply(gray)

        # 5 estrategias de umbralización → votación
        _, m1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        m2 = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 8)
        m3 = self._sauvola(enhanced, window=25, k=0.14)
        m4 = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 19, 6)
        m5 = self._sauvola(enhanced, window=41, k=0.20)

        vote = ((m1 > 0).astype(np.int16) + (m2 > 0).astype(np.int16)
                + (m3 > 0).astype(np.int16) + (m4 > 0).astype(np.int16)
                + (m5 > 0).astype(np.int16))

        # Umbral de votación adaptativo: si la máscara con ≥2 es muy vacía, bajar a ≥1
        # Umbral subido a 0.008 para capturar escritura con poco contraste.
        mask = np.where(vote >= 2, np.uint8(255), np.uint8(0))
        ink_ratio = np.sum(mask > 0) / max(1, mask.size)
        if ink_ratio < 0.008:
            mask = np.where(vote >= 1, np.uint8(255), np.uint8(0))
            logger.debug(f"Votación relajada a ≥1 (ratio={ink_ratio:.4f})")

        # Limpieza morfológica
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        raw = mask.copy()

        if opts.remove_lines:
            mask = self._remove_lines(mask)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))

        clean = self._filtered_mask(mask)
        return gray, raw, clean

    @staticmethod
    def _normalize_illumination(gray: np.ndarray) -> np.ndarray:
        """Sustrae el fondo estimado por dilatación morfológica → iluminación uniforme."""
        ks = max(51, gray.shape[1] // 10)
        ks = ks if ks % 2 == 1 else ks + 1
        # Acotar a 201 para evitar kernels extremadamente grandes en imágenes anchas
        ks = min(ks, 201)
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (ks, ks))
        bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, k)
        norm = cv2.divide(gray.astype(np.float32), bg.astype(np.float32), scale=255.0)
        return np.clip(norm, 0, 255).astype(np.uint8)

    @staticmethod
    def _sauvola(gray: np.ndarray, window: int = 25, k: float = 0.20) -> np.ndarray:
        """Thresholding de Sauvola — mucho mejor que Otsu para escritura a mano."""
        g = gray.astype(np.float32)
        mean = cv2.boxFilter(g, cv2.CV_32F, (window, window))
        sq_mean = cv2.boxFilter(g * g, cv2.CV_32F, (window, window))
        std = np.sqrt(np.maximum(0.0, sq_mean - mean * mean))
        threshold = mean * (1.0 + k * (std / 128.0 - 1.0))
        threshold = np.maximum(0.0, threshold)
        return (g < threshold).astype(np.uint8) * 255

    @staticmethod
    def _filtered_mask(mask: np.ndarray) -> np.ndarray:
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        out = np.zeros_like(mask)
        for i in range(1, num):
            a = int(stats[i, cv2.CC_STAT_AREA])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            if a >= MIN_COMP_AREA and w >= MIN_CHAR_W and h >= MIN_CHAR_H:
                out[labels == i] = 255
        return out

    def _remove_lines(self, mask: np.ndarray) -> np.ndarray:
        mask = np.where(mask > 0, np.uint8(255), np.uint8(0))
        h, w = mask.shape[:2]
        if h == 0 or w == 0:
            return mask
        kl = max(40, w // 12)
        horiz = cv2.getStructuringElement(cv2.MORPH_RECT, (kl, 1))
        detected = cv2.morphologyEx(mask, cv2.MORPH_OPEN, horiz)
        row_strength = np.sum(detected > 0, axis=1) / max(1, w)
        line_mask = np.zeros_like(mask)
        line_mask[row_strength > 0.18, :] = detected[row_strength > 0.18, :]
        line_mask = cv2.dilate(line_mask,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (3, 2)), iterations=1)
        vert = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, h // 20)))
        protect = cv2.dilate(
            cv2.morphologyEx(mask, cv2.MORPH_OPEN, vert),
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=1,
        )
        cleaned = mask.copy()
        cleaned[cv2.bitwise_and(line_mask, cv2.bitwise_not(protect)) > 0] = 0
        return np.where(cleaned > 0, np.uint8(255), np.uint8(0))

    # ── Detección de líneas ────────────────────────────────────────

    def _find_line_boxes(self, mask: np.ndarray) -> list[_BBox]:
        h, w = mask.shape[:2]
        proj = np.sum(mask > 0, axis=1).astype(np.float32)
        # Suavizado de proyección — kernel más grande para escritura irregular
        if h > 20:
            proj = cv2.GaussianBlur(proj.reshape(-1, 1), (1, 15), 0).flatten()
        threshold = max(1, int(w * LINE_THRESHOLD_F))

        # Detectar bandas de texto
        raw_bands: list[tuple[int, int]] = []
        in_band = False
        start = 0
        for y in range(h):
            if proj[y] > threshold and not in_band:
                start = y; in_band = True
            elif proj[y] <= threshold and in_band:
                if y - start >= MIN_BAND_H:
                    raw_bands.append((start, y))
                in_band = False
        if in_band and h - start >= MIN_BAND_H:
            raw_bands.append((start, h))

        # Fusionar bandas cercanas para no partir una línea en dos.
        # El umbral escala con la imagen para manejar fotos de mayor resolución.
        merge_gap = max(8, h // 40)
        merged: list[list[int]] = []
        for band in raw_bands:
            if merged and band[0] - merged[-1][1] <= merge_gap:
                merged[-1][1] = band[1]
            else:
                merged.append([band[0], band[1]])

        # Aplicar split a todas las bandas (no solo cuando hay 1).
        # Cada banda que contenga 2 renglones fusionados se divide recursivamente.
        split_merged = []
        for band in merged:
            split_merged.extend(self._split_tall_band(band, proj, h))
        merged = split_merged

        boxes: list[_BBox] = []
        for start, end in merged:
            y1 = max(0, start - 6)
            y2 = min(h, end + 6)
            cols = np.where(np.sum(mask[y1:y2] > 0, axis=0) > 0)[0]
            if len(cols):
                boxes.append(_BBox(int(cols[0]), y1,
                                   int(cols[-1]) + 1 - int(cols[0]), y2 - y1))
        return boxes

    @staticmethod
    def _split_tall_band(
        band: list[int], proj: np.ndarray, img_h: int
    ) -> list[list[int]]:
        """Divide una banda alta en sub-bandas usando prominencia del valle.

        La prominencia = min(pico_izquierdo - valle, pico_derecho - valle).
        Un separador real entre renglones tiene alta prominencia (la tinta sube
        claramente a ambos lados). Las variaciones internas de un renglón tienen
        prominencia baja (solo un lado sube mucho).
        """
        y0, y1 = band
        band_h = y1 - y0
        if band_h < 30:
            return [band]

        band_proj = proj[y0:y1].copy()
        local_max = float(np.max(band_proj))
        if local_max == 0:
            return [band]

        # Acotar el margen superior para bandas muy altas (> 300px) donde
        # band_h // 6 puede ser demasiado grande y dejar fuera la zona de separación.
        margin = max(8, min(band_h // 6, 30))
        if band_h - 2 * margin < 1:
            return [band]

        # Precomputar máximo acumulado prefijo y sufijo para prominencia O(n)
        prefix_max = np.maximum.accumulate(band_proj)
        suffix_max = np.maximum.accumulate(band_proj[::-1])[::-1]

        # Encontrar la posición con mayor PROMINENCIA (no solo la más profunda).
        # La prominencia = min(pico_izq - valle, pico_der - valle).
        # El valle entre renglones tiene altísima prominencia porque hay picos
        # grandes a ambos lados. Las variaciones dentro de un renglón tienen
        # prominencia menor porque uno de los lados es bajo.
        best_prom = 0.0
        best_i = -1
        for i in range(margin, band_h - margin):
            val = float(band_proj[i])
            lp = float(prefix_max[i - 1]) if i > 0 else val
            rp = float(suffix_max[i + 1]) if i < band_h - 1 else val
            prom = min(lp - val, rp - val)
            if prom > best_prom:
                best_prom = prom
                best_i = i

        min_val = float(band_proj[best_i]) if best_i >= 0 else local_max
        # Condición doble: alta prominencia Y valle suficientemente bajo.
        # El valle entre renglones está por debajo del 30% del máximo; las
        # variaciones internas de un renglón tienen valores mucho más altos.
        if best_i < 0 or best_prom < local_max * 0.40 or min_val > local_max * 0.30:
            return [band]
        # Bug fix #7: guard against split_row at or beyond band edges
        split_y = y0 + best_i
        if best_i <= 0 or best_i >= band_h:
            return [band]
        logger.info(
            f"Renglón separado en y={split_y} "
            f"(prominencia={best_prom:.0f}/{local_max:.0f}={best_prom/local_max*100:.0f}%)"
        )
        result = []
        for sub in [[y0, split_y], [split_y, y1]]:
            if sub[1] - sub[0] >= MIN_BAND_H:
                result.extend(GlyphExtractor._split_tall_band(sub, proj, img_h))
        return result or [band]

    # ── Detección asistida por IA (Tesseract) ─────────────────────

    def _tesseract_boundaries(self, line_mask: np.ndarray) -> list[int]:
        """Fronteras X de caracteres via Tesseract (varias estrategias).

        • Escala a 3× la altura original (mín. 200 px) — Tesseract necesita
          texto grande para operar con fiabilidad en escritura manual.
        • Añade borde blanco amplio — Tesseract descarta caracteres en los
          bordes; el borde evita esto.
        • Prueba PSM 7 (línea de texto) y PSM 13 (línea cruda, sin léxico).
        • Toma la UNIÓN de todas las fronteras detectadas por ambos modos.
        • No nos interesa QUÉ letra detectó Tesseract, solo DÓNDE están
          los bordes derecho/izquierdo de cada carácter detectado.
        """
        if not TESSERACT_OK or not CV2_OK or not PIL_OK:
            return []
        try:
            h, w = line_mask.shape[:2]

            # Escalar agresivamente: mínimo 200 px de altura, máximo 3×
            target_h = max(200, h * 3)
            scale = target_h / max(1, h)
            scaled_w = int(w * scale)
            lm = cv2.resize(
                line_mask, (scaled_w, target_h),
                interpolation=cv2.INTER_LINEAR,
            )
            # Binarizar limpiamente para Tesseract
            _, lm = cv2.threshold(lm, 127, 255, cv2.THRESH_BINARY)

            # Borde blanco amplio — Tesseract necesita contexto alrededor del texto
            border = 50
            lm = cv2.copyMakeBorder(
                lm, border, border, border, border,
                cv2.BORDER_CONSTANT, value=0,
            )

            # Invertir: Tesseract espera tinta oscura sobre fondo claro
            tess_in = 255 - lm
            pil_in = Image.fromarray(tess_in, mode="L")

            all_boundaries: set[int] = set()

            # Probar múltiples modos de segmentación
            import io as _io
            import sys as _sys
            for psm in [7, 13]:
                try:
                    # Bug fix #5: suppress Tesseract stderr warnings
                    _old_stderr = _sys.stderr
                    _sys.stderr = _io.StringIO()
                    try:
                        raw = pytesseract.image_to_boxes(
                            pil_in,
                            lang="spa",
                            config=f"--psm {psm} --oem 3",
                        )
                    finally:
                        _sys.stderr = _old_stderr
                    for ln in raw.strip().split("\n"):
                        parts = ln.split()
                        if len(parts) < 5:
                            continue
                        try:
                            bx1 = int(parts[1])
                            bx2 = int(parts[3])
                        except ValueError:
                            continue
                        # Convertir coordenadas escaladas+bordeadas a originales
                        orig_x1 = max(0, int((bx1 - border) / scale))
                        orig_x2 = max(0, int((bx2 - border) / scale))
                        if orig_x2 > orig_x1 and orig_x1 < w:
                            all_boundaries.add(min(orig_x1, w))
                            all_boundaries.add(min(orig_x2, w))
                except Exception:
                    continue

            result = sorted(all_boundaries)
            if result:
                logger.info(
                    f"Tesseract: {len(result)} fronteras "
                    f"(PSM 7+13, escala×{scale:.1f})"
                )
            return result
        except Exception as e:
            logger.debug(f"Tesseract boundary error: {e}")
            return []

    # ── Alineación por masa de tinta + VPP + IA ───────────────────

    def _align_inkflow(
        self, vpp: np.ndarray, x_min: int, x_max: int, chars: list[str]
    ) -> list[int]:
        """Fronteras por masa de tinta acumulada.

        Principio: los caracteres más anchos y con trazos más gruesos generan
        más píxeles de tinta. Sumando la tinta de izquierda a derecha y
        dividiendo proporcionalmente a los factores _wf(), obtenemos fronteras
        que se auto-calibran a la escritura real del usuario, sin asumir
        espaciados fijos.

        Devuelve N+1 posiciones (primera = x_min, última = x_max).
        """
        n = len(chars)
        span = vpp[x_min:x_max].astype(np.float64)
        total_ink = max(1e-6, float(np.sum(span)))
        cumink = np.cumsum(span)

        total_wf = max(0.01, sum(self._wf(c) for c in chars))
        # Mínimo ancho por región: 15 % del ancho promedio
        min_cw = max(1, int((x_max - x_min) / n * 0.15))

        bounds: list[int] = [x_min]
        cum_wf = 0.0
        for i, ch in enumerate(chars[:-1]):
            cum_wf += self._wf(ch)
            target = cum_wf / total_wf * total_ink
            prev = bounds[-1]

            # Buscar índice donde la tinta acumulada alcanza el objetivo
            lo_idx = max(0, prev + min_cw - x_min)
            if lo_idx >= len(cumink):
                # Fallback: distribuir el espacio restante proporcionalmente
                # entre los caracteres que quedan (incluido el actual)
                remaining_chars = chars[i:]
                remaining_wf = sum(self._wf(c) for c in remaining_chars)
                remaining_wf = max(0.01, remaining_wf)
                space_left = max(0, x_max - prev)
                frac = self._wf(ch) / remaining_wf
                step = max(min_cw, int(space_left * frac))
                bounds.append(min(prev + step, x_max - (n - 1 - i)))
                continue
            idx = int(np.searchsorted(cumink[lo_idx:], target)) + lo_idx
            idx = min(idx, len(span) - max(1, n - 1 - i))
            x = x_min + idx
            x = max(prev + min_cw, min(x, x_max - (n - 1 - i)))
            bounds.append(x)

        bounds.append(x_max)
        # Garantizar orden estrictamente creciente
        for i in range(1, len(bounds)):
            if bounds[i] <= bounds[i - 1]:
                bounds[i] = bounds[i - 1] + 1
        return bounds

    @staticmethod
    def _wf(ch: str) -> float:
        """Factor de ancho esperado por carácter.

        Tabla calibrada para escritura manual española.
        Valores más específicos → mejor distribución de fronteras.
        """
        if ch in ".,;:!¡|`'\"":          return 0.28
        if ch in "iltI1íì":              return 0.40
        if ch in "jr":                   return 0.50  # 'r' explícito para no confundirse con 's'
        if ch in "fFtT":                 return 0.60
        if ch in "scCeéèêëS":            return 0.63  # curvados estrechos; 's' era 0.78 → fijo r/s
        if ch in "nuvbpkxyzñhúùü":       return 0.72  # grupo medio
        if ch in "adgqáàâ":              return 0.80  # redondos con bucle
        if ch in "oóòôöO":               return 0.85  # circular
        if ch in "mwMW":                 return 1.30
        if ch.isupper():                 return 0.92
        if ch.isdigit():                 return 0.73
        return 0.78

    # [testing] ── Estrategias alternativas de segmentación ──────────

    def _align_vpp_only(
        self, vpp: np.ndarray, x_min: int, x_max: int, n: int
    ) -> list[int]:
        """A. VPP puro con selección por prominencia.

        Normaliza el VPP, detecta todos los valles (mínimos locales por debajo
        de un umbral), y selecciona los n-1 mejores valles como fronteras.
        La puntuación de un valle = profundidad relativa al máximo (prominencia).
        """
        if n <= 1:
            return [x_min, x_max]

        span = vpp[x_min:x_max].astype(np.float64)
        if len(span) == 0:
            return list(np.linspace(x_min, x_max, n + 1, dtype=int))

        # Suavizar para estabilizar mínimos
        ks = max(3, int((x_max - x_min) / max(1, n) * 0.15))
        ks = ks if ks % 2 == 1 else ks + 1
        smoothed = cv2.GaussianBlur(
            span.astype(np.float32).reshape(1, -1), (1, ks), 0
        ).flatten().astype(np.float64)

        vmax = float(np.max(smoothed)) if len(smoothed) > 0 else 1.0
        vmax = max(vmax, 1.0)

        # Encontrar todos los mínimos locales
        valleys: list[tuple[float, int]] = []  # (score, abs_x)
        L = len(smoothed)
        for i in range(1, L - 1):
            if smoothed[i] <= smoothed[i - 1] and smoothed[i] <= smoothed[i + 1]:
                left_peak = float(np.max(smoothed[:i])) if i > 0 else smoothed[i]
                right_peak = float(np.max(smoothed[i + 1:])) if i < L - 1 else smoothed[i]
                depth = min(left_peak - smoothed[i], right_peak - smoothed[i])
                prominence = depth / vmax
                if prominence > 0.05:  # filtrar ruido
                    valleys.append((prominence, x_min + i))

        if not valleys:
            return list(np.linspace(x_min, x_max, n + 1, dtype=int))

        # Seleccionar los n-1 mejores valles por prominencia
        valleys.sort(key=lambda v: -v[0])
        chosen = sorted([v[1] for v in valleys[:n - 1]])

        bounds = [x_min] + chosen + [x_max]
        for i in range(1, len(bounds)):
            if bounds[i] <= bounds[i - 1]:
                bounds[i] = bounds[i - 1] + 1
        return bounds

    def _align_uniform(self, x_min: int, x_max: int, n: int) -> list[int]:
        """B. División uniforme de ancho igual. Línea base de comparación."""
        if n <= 0:
            return [x_min, x_max]
        return [int(x_min + (x_max - x_min) * i / n) for i in range(n + 1)]

    def _align_dp_energy(
        self, vpp: np.ndarray, x_min: int, x_max: int, n: int
    ) -> list[int]:
        """C. Minimización de energía por programación dinámica O(L·k).

        Usa backpointers enteros (en vez de copiar listas) → memoria O(L·k)
        y running-minimum → tiempo O(L·k) en vez de O(L²·k).
        """
        if n <= 1:
            return [x_min, x_max]

        span = vpp[x_min:x_max].astype(np.float64)
        L = len(span)
        if L == 0:
            return list(np.linspace(x_min, x_max, n + 1, dtype=int))

        ks = max(3, int(L / max(1, n) * 0.15))
        ks = ks if ks % 2 == 1 else ks + 1
        cost = cv2.GaussianBlur(
            span.astype(np.float32).reshape(1, -1), (1, ks), 0
        ).flatten().astype(np.float64)

        min_gap = max(1, int(L / n * 0.15))
        num_cuts = n - 1
        INF = float("inf")

        # dp[i] = costo mínimo para colocar el corte actual en posición i
        # ptr[k, i] = posición del corte (k-1) en el camino óptimo que termina en i
        dp = np.full(L, INF, dtype=np.float64)
        ptr = np.full((num_cuts, L), -1, dtype=np.int32)

        # k=1: primer corte — sin backpointer necesario
        i_lo = min_gap
        i_hi = L - (num_cuts - 1) * min_gap
        for i in range(i_lo, i_hi):
            dp[i] = cost[i]

        # k=2..num_cuts: running minimum para O(L) amortizado por corte
        for k in range(2, num_cuts + 1):
            new_dp = np.full(L, INF, dtype=np.float64)
            run_min_val = INF
            run_min_pos = -1
            j_cursor = (k - 1) * min_gap          # primer j válido para este k

            i_lo = k * min_gap
            i_hi = L - (num_cuts - k) * min_gap
            for i in range(i_lo, i_hi):
                # Expandir la ventana de j hasta i-min_gap
                j_max = i - min_gap
                while j_cursor <= j_max:
                    if dp[j_cursor] < run_min_val:
                        run_min_val = dp[j_cursor]
                        run_min_pos = j_cursor
                    j_cursor += 1
                if run_min_pos >= 0 and run_min_val < INF:
                    new_val = run_min_val + cost[i]
                    if new_val < new_dp[i]:
                        new_dp[i] = new_val
                        ptr[k - 1, i] = run_min_pos
            dp = new_dp

        # Encontrar el último corte óptimo
        best_last = -1
        best_cost = INF
        for i in range(num_cuts * min_gap, L):
            if dp[i] < best_cost:
                best_cost = dp[i]
                best_last = i

        if best_last < 0:
            return list(np.linspace(x_min, x_max, n + 1, dtype=int))

        # Reconstruir camino por backpointers
        cut_positions: list[int] = [best_last]
        pos = best_last
        for k in range(num_cuts - 1, 0, -1):
            prev = int(ptr[k, pos])
            if prev < 0:
                return list(np.linspace(x_min, x_max, n + 1, dtype=int))
            cut_positions.append(prev)
            pos = prev
        cut_positions = sorted(cut_positions)

        while len(cut_positions) < num_cuts:
            cut_positions.append(cut_positions[-1] + min_gap if cut_positions else min_gap)
        cut_positions = cut_positions[:num_cuts]

        bounds = [x_min] + [x_min + p for p in sorted(cut_positions)] + [x_max]
        for i in range(1, len(bounds)):
            if bounds[i] <= bounds[i - 1]:
                bounds[i] = bounds[i - 1] + 1
        return bounds

    def _align_cc_first(
        self, binary_band: np.ndarray, x_min: int, x_max: int, n: int
    ) -> list[int]:
        """D. Componentes conectados primero.

        Encuentra todos los CCs en la banda, los ordena por centroide X,
        fusiona los que se tocan/solapan, y mapea los n slots de carácter
        a los n grupos CC más grandes.
        """
        if n <= 1:
            return [x_min, x_max]

        h, w = binary_band.shape[:2]
        num, labels, stats, centroids = cv2.connectedComponentsWithStats(
            binary_band, connectivity=8
        )

        blobs = []
        for i in range(1, num):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < MIN_COMP_AREA:
                continue
            bx = int(stats[i, cv2.CC_STAT_LEFT])
            bw_ = int(stats[i, cv2.CC_STAT_WIDTH])
            cx = float(centroids[i][0])
            blobs.append({"area": area, "x1": bx, "x2": bx + bw_, "cx": cx})

        if not blobs:
            return list(np.linspace(x_min, x_max, n + 1, dtype=int))

        blobs.sort(key=lambda b: b["x1"])

        merge_gap = 3
        groups: list[dict] = []
        for b in blobs:
            if groups and b["x1"] <= groups[-1]["x2"] + merge_gap:
                g = groups[-1]
                g["x2"] = max(g["x2"], b["x2"])
                g["area"] += b["area"]
                g["cx"] = (g["cx"] + b["cx"]) / 2
            else:
                groups.append({"x1": b["x1"], "x2": b["x2"],
                                "area": b["area"], "cx": b["cx"]})

        if not groups:
            return list(np.linspace(x_min, x_max, n + 1, dtype=int))

        # Fusionar grupos más próximos hasta llegar a exactamente n grupos.
        # Esto preserva chars pequeños ('i', 'l', '1') en vez de descartarlos
        # por área (problema del método anterior: top-n por área los perdía).
        while len(groups) > n:
            # Encontrar el gap más pequeño entre grupos consecutivos y fusionar
            min_gap_val = float("inf")
            min_gap_idx = 0
            for gi in range(len(groups) - 1):
                gap = groups[gi + 1]["x1"] - groups[gi]["x2"]
                if gap < min_gap_val:
                    min_gap_val = gap
                    min_gap_idx = gi
            g1, g2 = groups[min_gap_idx], groups[min_gap_idx + 1]
            merged = {
                "x1": g1["x1"], "x2": g2["x2"],
                "area": g1["area"] + g2["area"],
                "cx": (g1["cx"] * g1["area"] + g2["cx"] * g2["area"])
                       / max(1, g1["area"] + g2["area"]),
            }
            groups = groups[:min_gap_idx] + [merged] + groups[min_gap_idx + 2:]

        top_n = groups

        bounds: list[int] = [x_min]
        for i in range(len(top_n) - 1):
            g1 = top_n[i]
            g2 = top_n[i + 1]
            gap_center = (g1["x2"] + g2["x1"]) // 2
            bounds.append(max(bounds[-1] + 1, gap_center))
        bounds.append(x_max)

        while len(bounds) < n + 1:
            bounds.append(bounds[-1] + 1)
        bounds = bounds[:n + 1]

        for i in range(1, len(bounds)):
            if bounds[i] <= bounds[i - 1]:
                bounds[i] = bounds[i - 1] + 1
        return bounds

    def _align_hybrid_v2(
        self,
        vpp: np.ndarray,
        binary_band: np.ndarray,
        x_min: int,
        x_max: int,
        n: int,
        chars: list[str],
    ) -> list[int]:
        """E. Híbrido mejorado: InkFlow → columna de mínima tinta → verificación CC.

        1. Parte de las fronteras de InkFlow.
        2. Para cada frontera, busca en ±40 % del ancho promedio la COLUMNA CON
           MENOS TINTA (no solo un valle con umbral).
        3. Si el corte parte un CC, desplaza ±5 px buscando un gap real.
        """
        if n <= 1:
            return [x_min, x_max]

        base_bounds = self._align_inkflow(vpp, x_min, x_max, chars)

        h, w_full = binary_band.shape[:2]
        char_w_avg = max(1, (x_max - x_min) / n)
        search_half = int(char_w_avg * 0.40)

        num, labels, stats, _ = cv2.connectedComponentsWithStats(
            binary_band, connectivity=8
        )

        ks = max(3, int(char_w_avg * 0.12))
        ks = ks if ks % 2 == 1 else ks + 1
        vpp_s = cv2.GaussianBlur(
            vpp.astype(np.float32).reshape(1, -1), (1, ks), 0
        ).flatten()

        min_cw = max(1, int(char_w_avg * 0.20))
        refined: list[int] = [base_bounds[0]]

        for i in range(1, n):
            eb = base_bounds[i]
            prev = refined[-1]
            lo = max(prev + min_cw, eb - search_half)
            hi = min(w_full, eb + search_half + 1)

            if lo < hi:
                seg = vpp_s[lo:hi]
                best_x = lo + int(np.argmin(seg))
                best_x = max(prev + 1, best_x)
            else:
                best_x = max(prev + 1, eb)

            # Verificar si el corte parte un CC; si sí, buscar gap real ±5 px
            shift_range = 5
            if 0 <= best_x < w_full:
                col_labels = set(int(labels[r, best_x]) for r in range(h)
                                 if labels[r, best_x] > 0)
                if col_labels:
                    found_gap = False
                    for delta in range(1, shift_range + 1):
                        for candidate in [best_x - delta, best_x + delta]:
                            if candidate <= prev or candidate >= w_full:
                                continue
                            cand_labels = set(
                                int(labels[r, candidate]) for r in range(h)
                                if labels[r, candidate] > 0
                            )
                            if not cand_labels:
                                best_x = max(prev + 1, candidate)
                                found_gap = True
                                break
                        if found_gap:
                            break

            refined.append(max(prev + 1, best_x))

        refined.append(base_bounds[-1])
        for i in range(1, len(refined)):
            if refined[i] <= refined[i - 1]:
                refined[i] = refined[i - 1] + 1
        return refined

    # ── Pre-alineación por palabras ───────────────────────────────────

    def _find_word_gaps(
        self,
        vpp: np.ndarray,
        x_min: int,
        x_max: int,
        words: list[str],
    ) -> list[int]:
        """Devuelve len(words)+1 posiciones [x_min, gap1, gap2, ..., x_max].

        Detecta gaps de palabra (columnas con poca tinta) y asigna cada
        boundary esperado al gap más cercano. Si no hay suficientes gaps
        claros, devuelve lista vacía para señalizar "usar segmentación completa".
        """
        n_words = len(words)
        if n_words <= 1:
            return [x_min, x_max]

        span_len = x_max - x_min
        if span_len < 4:
            return []

        n_chars = max(1, sum(len(w) for w in words))
        char_w_est = span_len / n_chars

        # Suavizar VPP
        ks = max(3, int(char_w_est * 0.12))
        ks = ks if ks % 2 == 1 else ks + 1
        vpp_s = cv2.GaussianBlur(
            vpp.astype(np.float32).reshape(1, -1), (1, ks), 0
        ).flatten()

        vpp_max = float(np.max(vpp_s[x_min:x_max])) if x_max > x_min else 1.0
        # Gap de palabra: < 15 % de la tinta pico Y anchura ≥ 35 % del char_w
        gap_thr = vpp_max * 0.15
        min_gap_w = max(2, int(char_w_est * 0.35))

        # Detectar zonas de gap
        in_gap = False
        gap_zones: list[tuple[int, int]] = []
        gs = x_min
        for x in range(x_min, x_max):
            below = float(vpp_s[x]) <= gap_thr
            if below and not in_gap:
                gs = x
                in_gap = True
            elif not below and in_gap:
                if x - gs >= min_gap_w:
                    gap_zones.append((gs, x))
                in_gap = False
        if in_gap and x_max - gs >= min_gap_w:
            gap_zones.append((gs, x_max))

        if len(gap_zones) < n_words - 1:
            return []  # insuficientes gaps → usar segmentación completa

        gap_centers = [int((g[0] + g[1]) / 2) for g in gap_zones]

        # Posiciones esperadas de frontera proporcionales a la longitud de cada palabra
        word_lens = [max(1, len(w)) for w in words]
        total_chars = sum(word_lens)
        expected: list[int] = []
        cum = 0
        for wl in word_lens[:-1]:
            cum += wl
            expected.append(int(x_min + span_len * cum / total_chars))

        # Asignar cada boundary esperado al gap más cercano (sin repetir)
        chosen: list[int] = []
        used: set[int] = set()
        for ex in expected:
            candidates = [i for i in range(len(gap_centers)) if i not in used]
            if not candidates:
                return []
            best_i = min(candidates, key=lambda i: abs(gap_centers[i] - ex))
            used.add(best_i)
            chosen.append(gap_centers[best_i])

        bounds = [x_min] + sorted(chosen) + [x_max]
        for i in range(1, len(bounds)):
            if bounds[i] <= bounds[i - 1]:
                bounds[i] = bounds[i - 1] + 1
        return bounds

    def _segment_words(
        self,
        words: list[str],
        word_bounds: list[int],
        line_mask: np.ndarray,
        line_h: float,
    ) -> list[tuple["_BBox", str, float]]:
        """Segmenta cada palabra de forma independiente usando los bounds dados."""
        h, w = line_mask.shape[:2]
        result: list[tuple[_BBox, str, float]] = []
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
                box = _BBox(bx, 0, bw_, h)
                ink = float(np.sum(word_mask > 0))
                cov = ink / max(1, h * bw_)
                result.append((box, word_chars[0], min(1.0, max(0.1, cov / 0.18))))
            else:
                # Segmentación recursiva dentro de la palabra
                sub = self._align_pos([], word, line_h, word_mask)
                for box, ch, score in sub:
                    result.append((_BBox(box.x + wx1, box.y, box.w, box.h), ch, score))
        return result

    # [testing] ── Función de prueba de todas las estrategias ─────────

    def _test_all_strategies(
        self,
        band_img: np.ndarray,
        band_binary: np.ndarray,
        x_min: int,
        x_max: int,
        n: int,
        chars: list[str],
        line_mask: np.ndarray,
    ) -> dict:
        """Ejecuta todas las estrategias de segmentación y puntúa sus glifos.

        Retorna dict: {nombre_estrategia: {"boundaries": [...], "avg_quality": float,
                                            "min_quality": float, "max_quality": float,
                                            "glyph_count": int}}
        """
        if not CV2_OK or not PIL_OK:
            return {}

        h, w = band_binary.shape[:2]
        vpp = np.sum(band_binary > 0, axis=0).astype(np.float32)

        def _score_bounds(bounds: list[int]) -> dict:
            scores: list[float] = []
            for i in range(len(bounds) - 1):
                x1 = max(0, bounds[i])
                x2 = min(w, bounds[i + 1])
                if x2 <= x1:
                    continue
                crop = band_binary[:, x1:x2]
                crop_tight = self._tight_crop(crop, 3)
                if crop_tight is None:
                    continue
                pil_img = self._to_rgba_smooth(crop_tight)
                ink = float(np.sum(band_binary[:, x1:x2] > 0))
                area = max(1, h * (x2 - x1))
                cov = ink / area
                align_score = min(1.0, max(0.1, cov / 0.18))
                q = self._assess_quality(pil_img, align_score)
                scores.append(q["quality_score"])
            if not scores:
                return {"avg_quality": 0.0, "min_quality": 0.0,
                        "max_quality": 0.0, "glyph_count": 0}
            return {
                "avg_quality": float(np.mean(scores)),
                "min_quality": float(np.min(scores)),
                "max_quality": float(np.max(scores)),
                "glyph_count": len(scores),
            }

        results: dict = {}

        # Estrategia actual de producción (InkFlow + VPP snap + Tesseract)
        try:
            prod_bounds = self._align_inkflow(vpp, x_min, x_max, chars)
            char_w_avg = (x_max - x_min) / max(1, n)
            ks = max(3, int(w / max(1, n) * 0.12))
            ks = ks if ks % 2 == 1 else ks + 1
            vpp_s = cv2.GaussianBlur(vpp.reshape(1, -1), (1, ks), 0).flatten()
            vpp_max = float(np.max(vpp_s[x_min:x_max])) if x_max > x_min else 1.0
            gap_thr = vpp_max * 0.12
            sw = max(2, int(char_w_avg * 0.30))
            min_cw = max(1, int(char_w_avg * 0.20))
            refined_prod: list[int] = [prod_bounds[0]]
            for i in range(1, n):
                eb = prod_bounds[i]
                prev = refined_prod[-1]
                lo = max(prev + min_cw, eb - sw)
                hi = min(w, eb + sw + 1)
                if lo < hi:
                    seg = vpp_s[lo:hi]
                    min_i = int(np.argmin(seg))
                    min_v = float(seg[min_i])
                    best_x = max(prev + 1, lo + min_i) if min_v < gap_thr else max(prev + 1, eb)
                else:
                    best_x = max(prev + 1, eb)
                refined_prod.append(best_x)
            refined_prod.append(prod_bounds[-1])
            for i in range(1, len(refined_prod)):
                if refined_prod[i] <= refined_prod[i - 1]:
                    refined_prod[i] = refined_prod[i - 1] + 1
            tess = self._tesseract_boundaries(line_mask)
            snap_r = max(3, int(char_w_avg * 0.22))
            if tess:
                final_prod: list[int] = [refined_prod[0]]
                prev_p = refined_prod[0]
                for i in range(1, n):
                    eb = refined_prod[i]
                    nearby = [tb for tb in tess
                               if abs(tb - eb) <= snap_r
                               and prev_p + min_cw < tb < w
                               and 0 <= tb < len(vpp_s)
                               and float(vpp_s[tb]) < vpp_max * 0.35]
                    if nearby:
                        eb = max(prev_p + 1, min(nearby, key=lambda tb: abs(tb - eb)))
                    final_prod.append(eb)
                    prev_p = eb
                final_prod.append(refined_prod[-1])
            else:
                final_prod = refined_prod
            r = _score_bounds(final_prod)
            r["boundaries"] = final_prod
            results["production (inkflow+vpp+tess)"] = r
        except Exception as exc:
            results["production (inkflow+vpp+tess)"] = {
                "error": str(exc), "avg_quality": 0.0,
                "min_quality": 0.0, "max_quality": 0.0, "glyph_count": 0}

        # A. VPP puro
        try:
            bounds_a = self._align_vpp_only(vpp, x_min, x_max, n)
            r = _score_bounds(bounds_a)
            r["boundaries"] = bounds_a
            results["A: vpp_only"] = r
        except Exception as exc:
            results["A: vpp_only"] = {"error": str(exc), "avg_quality": 0.0,
                                       "min_quality": 0.0, "max_quality": 0.0,
                                       "glyph_count": 0}

        # B. Uniforme
        try:
            bounds_b = self._align_uniform(x_min, x_max, n)
            r = _score_bounds(bounds_b)
            r["boundaries"] = bounds_b
            results["B: uniform"] = r
        except Exception as exc:
            results["B: uniform"] = {"error": str(exc), "avg_quality": 0.0,
                                      "min_quality": 0.0, "max_quality": 0.0,
                                      "glyph_count": 0}

        # C. DP Energy (solo para n pequeño)
        if n <= 20:
            try:
                bounds_c = self._align_dp_energy(vpp, x_min, x_max, n)
                r = _score_bounds(bounds_c)
                r["boundaries"] = bounds_c
                results["C: dp_energy"] = r
            except Exception as exc:
                results["C: dp_energy"] = {"error": str(exc), "avg_quality": 0.0,
                                            "min_quality": 0.0, "max_quality": 0.0,
                                            "glyph_count": 0}
        else:
            results["C: dp_energy"] = {"avg_quality": 0.0, "min_quality": 0.0,
                                        "max_quality": 0.0, "glyph_count": 0,
                                        "note": f"skipped (n={n} > 20)"}

        # D. CC first
        try:
            bounds_d = self._align_cc_first(band_binary, x_min, x_max, n)
            r = _score_bounds(bounds_d)
            r["boundaries"] = bounds_d
            results["D: cc_first"] = r
        except Exception as exc:
            results["D: cc_first"] = {"error": str(exc), "avg_quality": 0.0,
                                       "min_quality": 0.0, "max_quality": 0.0,
                                       "glyph_count": 0}

        # E. Hybrid v2
        try:
            bounds_e = self._align_hybrid_v2(vpp, band_binary, x_min, x_max, n, chars)
            r = _score_bounds(bounds_e)
            r["boundaries"] = bounds_e
            results["E: hybrid_v2"] = r
        except Exception as exc:
            results["E: hybrid_v2"] = {"error": str(exc), "avg_quality": 0.0,
                                        "min_quality": 0.0, "max_quality": 0.0,
                                        "glyph_count": 0}

        return results

    def _align_pos(
        self, boxes: list[_BBox], text: str, line_h: float = 30.0,
        line_mask: Optional[np.ndarray] = None,
    ) -> list[tuple[_BBox, str, float]]:
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

        # ── Etapa final: Anclaje con Tesseract ────────────────────
        tess_bdry = self._tesseract_boundaries(line_mask)
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

        result: list[tuple[_BBox, str, float]] = []
        for i, ch in enumerate(chars):
            x1 = final[i]
            x2 = min(final[i + 1], w)
            bw = max(1, x2 - x1)
            box = _BBox(x1, 0, bw, h)
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

    # ── Refinamiento de región por componentes conectados ─────────

    @staticmethod
    def _refine_char_region(
        line_mask: np.ndarray, x1: int, x2: int
    ) -> tuple[int, int, int, int]:
        """Reduce el recorte al blob dominante + diacríticos flotantes.

        Después de que VPP da los bordes aproximados, aquí encontramos el
        componente conectado más grande (= el carácter principal) y le sumamos
        los blobs pequeños situados sobre él que corresponden a puntos de i/j,
        acentos (á é í ó ú) y tildes de ñ.

        Devuelve (bx1, by1, bx2, by2) en coordenadas de line_mask.
        Si no hay blobs reconocibles, devuelve la región original completa.
        """
        h, w = line_mask.shape[:2]
        # Pequeño margen para no recortar diacríticos al borde de la región
        pad = 4
        rx1 = max(0, x1 - pad)
        rx2 = min(w, x2 + pad)
        region = line_mask[:, rx1:rx2]

        if not np.any(region > 0):
            return x1, 0, x2, h

        num, _labels, stats, centroids = cv2.connectedComponentsWithStats(
            region, connectivity=8
        )
        if num < 2:
            return x1, 0, x2, h

        blobs = []
        for i in range(1, num):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < MIN_COMP_AREA:
                continue
            bx = int(stats[i, cv2.CC_STAT_LEFT]) + rx1   # coords absolutas
            by = int(stats[i, cv2.CC_STAT_TOP])
            bw_ = int(stats[i, cv2.CC_STAT_WIDTH])
            bh_ = int(stats[i, cv2.CC_STAT_HEIGHT])
            cx = float(centroids[i][0]) + rx1
            cy = float(centroids[i][1])
            blobs.append({"area": area, "x": bx, "y": by, "w": bw_, "h": bh_,
                          "cx": cx, "cy": cy})

        if not blobs:
            return x1, 0, x2, h

        blobs.sort(key=lambda b: b["area"], reverse=True)
        main = blobs[0]
        char_span = max(1, x2 - x1)

        # Agregar diacríticos flotantes: blobs pequeños SOBRE el cuerpo principal
        # que estén horizontalmente alineados (punto de i, acento, tilde de ñ)
        # También adjuntar descenders: blobs de g, p, q, y, j bajo el cuerpo.
        group = [main]
        for b in blobs[1:]:
            is_diacritic = (
                b["area"] < main["area"] * 0.40
                and b["cy"] < main["cy"]
                # Tolerancia X ajustada: 0.55 en vez de 0.90 para no capturar
                # la tinta del carácter vecino (punto de 'i' nunca está tan lejos)
                and abs(b["cx"] - main["cx"]) < char_span * 0.55
            )
            is_descender = (
                b["area"] < main["area"] * 0.60
                and b["cy"] > main["cy"]
                # Tolerancia X reducida: 0.50 en vez de 0.80
                and abs(b["cx"] - main["cx"]) < char_span * 0.50
                and b["y"] > main["y"] + main["h"] * 0.5
            )
            if is_diacritic or is_descender:
                group.append(b)

        gx1 = max(0, min(b["x"] for b in group))
        gy1 = max(0, min(b["y"] for b in group))
        gx2 = min(w, max(b["x"] + b["w"] for b in group))
        gy2 = min(h, max(b["y"] + b["h"] for b in group))

        # No expandir X más allá del ancho del carácter esperado; si se expande
        # demasiado significa que capturó tinta del carácter vecino y se "fusionarían".
        expand_max = max(6, int((x2 - x1) * 0.18))
        gx1 = max(gx1, x1 - expand_max)
        gx2 = min(gx2, x2 + expand_max)
        return gx1, gy1, gx2, gy2

    # ── Glifo → RGBA + calidad ─────────────────────────────────────

    @staticmethod
    def _tight_crop(mask: np.ndarray, padding: int = 3) -> Optional[np.ndarray]:
        rows = np.any(mask > 0, axis=1)
        cols = np.any(mask > 0, axis=0)
        if not rows.any() or not cols.any():
            return None
        r0, r1 = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
        c0, c1 = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
        h, w = mask.shape[:2]
        result = mask[max(0, r0-padding):min(h, r1+1+padding),
                      max(0, c0-padding):min(w, c1+1+padding)]
        # Bug fix #4: guard against zero-dimension crops
        if result.shape[0] < 1 or result.shape[1] < 1:
            return None
        return result

    @staticmethod
    def _to_rgba_smooth(mask: np.ndarray) -> "Image.Image":
        """RGBA con bordes anti-aliased. RGB=blanco para que sea visible sobre fondos oscuros."""
        # Bug fix #4: guard against zero-dimension mask
        if mask.shape[0] < 1 or mask.shape[1] < 1:
            return Image.fromarray(np.zeros((1, 1, 4), dtype=np.uint8))
        alpha = cv2.GaussianBlur(mask.astype(np.float32), (3, 3), 0.9)
        alpha = np.clip(alpha, 0, 255).astype(np.uint8)
        h, w = mask.shape[:2]
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[..., :3] = 255   # tinta blanca — visible sobre cualquier fondo oscuro
        rgba[..., 3] = alpha
        return Image.fromarray(rgba)

    @staticmethod
    def _assess_quality(img: "Image.Image", align_score: float = 0.5) -> dict:
        """Calidad integral: cobertura + ancho de trazo + alineación."""
        alpha = np.array(img.getchannel("A"))
        ink = int(np.sum(alpha > 50))
        h, w = alpha.shape[:2]
        if h == 0 or w == 0:
            return {"quality_score": 0.0, "coverage": 0.0, "ok": False, "score": 0.0}

        coverage = ink / max(1, w * h)
        bbox = Image.fromarray(alpha, mode="L").getbbox()
        tw = (bbox[2] - bbox[0]) if bbox else 0
        th = (bbox[3] - bbox[1]) if bbox else 0

        # Toque en borde: penalización leve (carácter recortado) pero no severa
        touches = bool(
            np.any(alpha[0] > 50) or np.any(alpha[-1] > 50)
            or np.any(alpha[:, 0] > 50) or np.any(alpha[:, -1] > 50)
        )

        # Ancho de trazo via distance transform
        binary = (alpha > 50).astype(np.uint8) * 255
        dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
        sv = dist[dist > 0]
        if len(sv) > 4:
            sw_mean = float(np.mean(sv))
            sw_std = float(np.std(sv))
            sw_consistency = max(0.0, 1.0 - sw_std / max(1.0, sw_mean))
            sw_score = min(1.0, sw_mean / 3.0) * 0.5 + sw_consistency * 0.5
        else:
            sw_score = 0.30

        # Fórmula asimétrica: penaliza más la cobertura muy baja (char vacío)
        # que la muy alta (char estrecho 'i','l','f','1' con buen recorte).
        if coverage < 0.22:
            cov_score = max(0.0, 1.0 - (0.22 - coverage) / 0.22)
        else:
            cov_score = max(0.0, 1.0 - (coverage - 0.22) / 0.60)
        ink_score = max(0.0, min(1.0, ink / 40.0))   # más sensible a glifos pequeños
        size_score = (1.0 if tw >= 4 and th >= 6
                      else 0.60 if tw >= 2 and th >= 3 else 0.10)
        border_score = 0.82 if touches else 1.0       # penalización leve
        align_c = max(0.0, min(1.0, align_score))

        qs = max(0.0, min(1.0,
            0.10
            + cov_score   * 0.22
            + ink_score   * 0.22
            + size_score  * 0.18
            + sw_score    * 0.16
            + border_score * 0.07
            + align_c     * 0.05
        ))
        ok = (ink >= 10 and coverage >= 0.004 and tw >= 2
              and th >= 3 and qs >= QUALITY_MIN)
        return {
            "ink_pixels": ink, "coverage": float(coverage),
            "tight_w": tw, "tight_h": th,
            "touches_border": touches, "sw_score": float(sw_score),
            "quality_score": float(qs), "score": float(qs), "ok": bool(ok),
        }

"""
SegmentDetector — detección de líneas y alineación de caracteres para GlyphExtractor.

Extraído de extractor.py para mejorar la modularidad.
Contiene: find_line_boxes, _split_tall_band, tesseract_boundaries.
"""
import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

try:
    import pytesseract
    PIL_OK = True
except ImportError:
    TESSERACT_OK = False

try:
    from PIL import Image as _PILImage
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    TESSERACT_OK
except NameError:
    TESSERACT_OK = PIL_OK and "pytesseract" in dir()

MIN_COMP_AREA = 10
MIN_CHAR_W = 2
MIN_CHAR_H = 3
MIN_BAND_H = 5
LINE_THRESHOLD_F = 0.004


class SegmentDetector:
    """Detecta bandas de líneas de texto y alinea segmentos de caracteres."""

    def find_line_boxes(self, mask: "np.ndarray", BBox) -> list:
        return self._find_line_boxes(mask, BBox)

    def _find_line_boxes(self, mask: "np.ndarray", BBox) -> list:
        h, w = mask.shape[:2]
        proj = np.sum(mask > 0, axis=1).astype(np.float32)
        if h > 20:
            proj = cv2.GaussianBlur(proj.reshape(-1, 1), (1, 15), 0).flatten()
        threshold = max(1, int(w * LINE_THRESHOLD_F))

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

        merge_gap = max(8, h // 40)
        merged: list[list[int]] = []
        for band in raw_bands:
            if merged and band[0] - merged[-1][1] <= merge_gap:
                merged[-1][1] = band[1]
            else:
                merged.append([band[0], band[1]])

        split_merged = []
        for band in merged:
            split_merged.extend(self._split_tall_band(band, proj, h))
        merged = split_merged

        boxes = []
        for start, end in merged:
            y1 = max(0, start - 6)
            y2 = min(h, end + 6)
            cols = np.where(np.sum(mask[y1:y2] > 0, axis=0) > 0)[0]
            if len(cols):
                boxes.append(BBox(int(cols[0]), y1,
                                  int(cols[-1]) + 1 - int(cols[0]), y2 - y1))
        return boxes

    @staticmethod
    def _split_tall_band(
        band: list, proj: "np.ndarray", img_h: int
    ) -> list:
        y0, y1 = band
        band_h = y1 - y0
        if band_h < 30:
            return [band]

        band_proj = proj[y0:y1].copy()
        local_max = float(np.max(band_proj))
        if local_max == 0:
            return [band]

        margin = max(8, min(band_h // 6, 30))
        if band_h - 2 * margin < 1:
            return [band]

        prefix_max = np.maximum.accumulate(band_proj)
        suffix_max = np.maximum.accumulate(band_proj[::-1])[::-1]

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
        if best_i < 0 or best_prom < local_max * 0.40 or min_val > local_max * 0.30:
            return [band]
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
                result.extend(SegmentDetector._split_tall_band(sub, proj, img_h))
        return result or [band]

    def tesseract_boundaries(self, line_mask: "np.ndarray") -> list[int]:
        if not TESSERACT_OK or not CV2_OK or not PIL_OK:
            return []
        try:
            h, w = line_mask.shape[:2]
            target_h = max(200, h * 3)
            scale = target_h / max(1, h)
            scaled_w = int(w * scale)
            lm = cv2.resize(line_mask, (scaled_w, target_h), interpolation=cv2.INTER_LINEAR)
            _, lm = cv2.threshold(lm, 127, 255, cv2.THRESH_BINARY)
            border = 50
            lm = cv2.copyMakeBorder(lm, border, border, border, border,
                                    cv2.BORDER_CONSTANT, value=0)
            tess_in = 255 - lm
            pil_in = _PILImage.fromarray(tess_in, mode="L")

            import io as _io
            import sys as _sys
            all_boundaries: set[int] = set()
            for psm in [7, 13]:
                try:
                    _old_stderr = _sys.stderr
                    _sys.stderr = _io.StringIO()
                    try:
                        raw = pytesseract.image_to_boxes(
                            pil_in, lang="spa", config=f"--psm {psm} --oem 3",
                        )
                    finally:
                        _sys.stderr = _old_stderr
                    for ln in raw.strip().split("\n"):
                        parts = ln.split()
                        if len(parts) < 5:
                            continue
                        try:
                            bx1, bx2 = int(parts[1]), int(parts[3])
                        except ValueError:
                            continue
                        orig_x1 = max(0, int((bx1 - border) / scale))
                        orig_x2 = max(0, int((bx2 - border) / scale))
                        if orig_x2 > orig_x1 and orig_x1 < w:
                            all_boundaries.add(min(orig_x1, w))
                            all_boundaries.add(min(orig_x2, w))
                except Exception:
                    continue

            result = sorted(all_boundaries)
            if result:
                logger.info(f"Tesseract: {len(result)} fronteras (PSM 7+13, escala×{scale:.1f})")
            return result
        except Exception as e:
            logger.debug(f"Tesseract boundary error: {e}")
            return []

"""
SegmentDetector — detección de líneas y bandas de texto para GlyphExtractor.

Movido desde extractor.py (Fase 4A). Contiene la lógica de _find_line_boxes
y _split_tall_band que previamente eran métodos inline de GlyphExtractor.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

# Constantes compartidas con extractor.py
LINE_THRESHOLD_F = 0.004
MIN_BAND_H = 5

# Importar BBox desde extractor para no duplicar la definición
# (se hace lazy para evitar import circular al cargar el módulo)
def _BBox():
    from core.inkcore.extractor import BBox
    return BBox


class SegmentDetector:
    """Detecta bandas de texto y sus límites horizontales en una máscara binaria.

    Se instancia una vez en GlyphExtractor.__init__ como self._seg_detector.
    """

    def find_line_boxes(self, mask: "np.ndarray") -> list:
        """Detecta bandas de texto (líneas de escritura) en la máscara.

        Devuelve lista de BBox con las coordenadas de cada banda.
        """
        if not CV2_OK:
            return []
        BBox = _BBox()
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
                start = y
                in_band = True
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

        split_merged: list[list[int]] = []
        for band in merged:
            split_merged.extend(self.split_tall_band(band, proj, h))
        merged = split_merged

        boxes = []
        for start_y, end_y in merged:
            y1 = max(0, start_y - 6)
            y2 = min(h, end_y + 6)
            cols = np.where(np.sum(mask[y1:y2] > 0, axis=0) > 0)[0]
            if len(cols):
                boxes.append(BBox(int(cols[0]), y1,
                                  int(cols[-1]) + 1 - int(cols[0]), y2 - y1))
        return boxes

    @staticmethod
    def split_tall_band(
        band: list[int], proj: "np.ndarray", img_h: int
    ) -> list[list[int]]:
        """Divide una banda alta en sub-bandas por prominencia de valle.

        La prominencia = min(pico_izquierdo - valle, pico_derecho - valle).
        Un separador real entre renglones tiene alta prominencia.
        """
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
            "Renglón separado en y=%d (prominencia=%.0f/%.0f=%.0f%%)",
            split_y, best_prom, local_max, best_prom / local_max * 100,
        )
        result: list[list[int]] = []
        for sub in [[y0, split_y], [split_y, y1]]:
            if sub[1] - sub[0] >= MIN_BAND_H:
                result.extend(SegmentDetector.split_tall_band(sub, proj, img_h))
        return result or [band]

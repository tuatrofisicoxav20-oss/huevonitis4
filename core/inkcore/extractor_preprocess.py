"""
ImagePreprocessor — preprocesamiento de imágenes para GlyphExtractor.

Extraído de extractor.py para mejorar la modularidad.
Contiene todas las operaciones de imagen que preceden a la detección de segmentos.
"""
import logging

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

# Constantes compartidas con extractor.py
MIN_COMP_AREA = 10
MIN_CHAR_W = 2
MIN_CHAR_H = 3
MAX_DESKEW_DEG = 15.0
TARGET_LONG = 2200


class ImagePreprocessor:
    """Maneja todas las operaciones de preprocesamiento de imagen:
    ajustes manuales, escala, autocrop, deskew, umbralización y limpieza.
    """

    def apply_options(self, img: "np.ndarray", opts) -> "np.ndarray":
        """Aplica rotación y ajustes de brillo/contraste manuales."""
        return self._apply_manual(img, opts)

    def normalize_illumination(self, gray: "np.ndarray") -> "np.ndarray":
        return self._normalize_illumination(gray)

    def deskew(self, img: "np.ndarray") -> "tuple[np.ndarray, float]":
        return self._deskew(img)

    def remove_notebook_lines(self, mask: "np.ndarray") -> "np.ndarray":
        return self._remove_lines(mask)

    def multi_threshold_vote(self, gray: "np.ndarray") -> "np.ndarray":
        """Votación de 5 estrategias de umbralización."""
        return self._multi_threshold_vote(gray)

    def perspective_correct(self, img: "np.ndarray") -> "np.ndarray":
        return self._autocrop(img)

    # ── Implementaciones ────────────────────────────────────────────

    def _apply_manual(self, img: "np.ndarray", opts) -> "np.ndarray":
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

    def scale(self, img: "np.ndarray") -> "np.ndarray":
        h, w = img.shape[:2]
        ls = max(h, w)
        if ls <= TARGET_LONG:
            return img
        s = TARGET_LONG / ls
        return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

    def _autocrop(self, img: "np.ndarray") -> "np.ndarray":
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

    def _four_point_transform(
        self, img: "np.ndarray", pts: "np.ndarray"
    ) -> "np.ndarray | None":
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
                                       borderMode=cv2.BORDER_CONSTANT,
                                       borderValue=(255, 255, 255))
        except Exception:
            return None

    @staticmethod
    def _order_points(pts: "np.ndarray") -> "np.ndarray":
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        d = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(d)]
        rect[3] = pts[np.argmax(d)]
        return rect

    def _deskew(self, img: "np.ndarray") -> "tuple[np.ndarray, float]":
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        binary = self.filtered_mask(binary)
        angle = self._estimate_skew(binary, img.shape[1])
        if angle is None or abs(angle) < 0.25:
            return img, 0.0
        if abs(angle) > MAX_DESKEW_DEG:
            logger.warning(f"Inclinación {angle:.1f}° fuera del límite, no se corrige")
            return img, 0.0
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT,
                                 borderValue=(255, 255, 255))
        return rotated, float(angle)

    def _estimate_skew(self, mask: "np.ndarray", width: int) -> "float | None":
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

    def full_preprocess(
        self, img: "np.ndarray", opts
    ) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
        """Normalización + umbralización + limpieza. Retorna (gray, raw_mask, clean_mask)."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = self._normalize_illumination(gray)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        img_w = gray.shape[1]
        tile = max(8, min(32, img_w // 60))
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(tile, tile))
        enhanced = clahe.apply(gray)

        mask = self._multi_threshold_vote(enhanced)

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        raw = mask.copy()

        if opts.remove_lines:
            mask = self._remove_lines(mask)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))

        clean = self.filtered_mask(mask)
        return gray, raw, clean

    def _multi_threshold_vote(self, enhanced: "np.ndarray") -> "np.ndarray":
        """5 estrategias de umbralización con votación adaptativa."""
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

        mask = np.where(vote >= 2, np.uint8(255), np.uint8(0))
        ink_ratio = np.sum(mask > 0) / max(1, mask.size)
        if ink_ratio < 0.008:
            mask = np.where(vote >= 1, np.uint8(255), np.uint8(0))
            logger.debug(f"Votación relajada a ≥1 (ratio={ink_ratio:.4f})")
        return mask

    @staticmethod
    def _normalize_illumination(gray: "np.ndarray") -> "np.ndarray":
        ks = max(51, gray.shape[1] // 10)
        ks = ks if ks % 2 == 1 else ks + 1
        ks = min(ks, 201)
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (ks, ks))
        bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, k)
        norm = cv2.divide(gray.astype(np.float32), bg.astype(np.float32), scale=255.0)
        return np.clip(norm, 0, 255).astype(np.uint8)

    @staticmethod
    def _sauvola(gray: "np.ndarray", window: int = 25, k: float = 0.20) -> "np.ndarray":
        g = gray.astype(np.float32)
        mean = cv2.boxFilter(g, cv2.CV_32F, (window, window))
        sq_mean = cv2.boxFilter(g * g, cv2.CV_32F, (window, window))
        std = np.sqrt(np.maximum(0.0, sq_mean - mean * mean))
        threshold = mean * (1.0 + k * (std / 128.0 - 1.0))
        threshold = np.maximum(0.0, threshold)
        return (g < threshold).astype(np.uint8) * 255

    @staticmethod
    def filtered_mask(mask: "np.ndarray") -> "np.ndarray":
        """Elimina componentes demasiado pequeños (ruido)."""
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        out = np.zeros_like(mask)
        for i in range(1, num):
            a = int(stats[i, cv2.CC_STAT_AREA])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            if a >= MIN_COMP_AREA and w >= MIN_CHAR_W and h >= MIN_CHAR_H:
                out[labels == i] = 255
        return out

    def _remove_lines(self, mask: "np.ndarray") -> "np.ndarray":
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

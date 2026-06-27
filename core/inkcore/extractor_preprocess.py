"""
ImagePreprocessor — preprocesamiento de imágenes para GlyphExtractor.

Movido desde extractor.py (Fase 4A). La clase contiene todos los métodos
de preprocesamiento previamente inline en GlyphExtractor, que ahora
delegan aquí. La API pública de GlyphExtractor no cambia.
"""
from __future__ import annotations

import logging

# Funciones de orientación (lectura EXIF, rotación 90°, OSD). Viven en
# extractor_orient para acotar este módulo; se re-exportan porque glyph_ingest,
# core/ocr/backends/trocr y los tests las importan desde acá. OJO: el test de
# orientación parchea _osd_rotation en core.inkcore.extractor_orient (donde
# orient_by_content lo resuelve ahora), no en este módulo.
from core.inkcore.extractor_orient import (  # noqa: F401
    _osd_rotation,
    _rotate_90s,
    imread_oriented,
    orient_by_content,
)

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

# scikit-image (opcional): binarización de documento de nivel "escáner".
# Si no está instalado, todo el preprocesamiento degrada a las variantes
# basadas en cv2 (Sauvola casero + CLAHE de OpenCV) — el comportamiento previo.
try:
    from skimage.exposure import equalize_adapthist as _sk_equalize_adapthist
    from skimage.exposure import rescale_intensity as _sk_rescale_intensity
    from skimage.filters import threshold_sauvola as _sk_threshold_sauvola
    SKIMAGE_OK = True
except ImportError:  # pragma: no cover - entorno sin scikit-image
    SKIMAGE_OK = False

# Constantes compartidas con extractor.py
MIN_COMP_AREA = 10
MIN_CHAR_W = 2
MIN_CHAR_H = 3
CHAR_PAD = 6
TARGET_LONG = 2200
MAX_DESKEW_DEG = 15.0


class ImagePreprocessor:
    """Preprocesa imágenes BGR de apuntes para extracción de glifos.

    Todos los métodos son puros respecto a la imagen (no guardan estado
    entre llamadas). Se instancia una vez en GlyphExtractor.__init__.
    """

    # ── Ajustes manuales (brillo/contraste/rotación) ───────────────

    def apply_options(self, img: np.ndarray, opts) -> np.ndarray:
        """Aplica ajustes manuales de brillo, contraste y rotación."""
        if not CV2_OK:
            return img
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

    def scale(self, img: np.ndarray) -> np.ndarray:
        """Reduce imágenes grandes a TARGET_LONG en el lado mayor."""
        if not CV2_OK:
            return img
        h, w = img.shape[:2]
        ls = max(h, w)
        if ls <= TARGET_LONG:
            return img
        s = TARGET_LONG / ls
        return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

    # ── Autocrop + corrección de perspectiva ───────────────────────

    def autocrop(self, img: np.ndarray) -> np.ndarray:
        """Detecta y recorta el área de escritura; corrige perspectiva si es posible."""
        if not CV2_OK:
            return img
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
            crop = img[max(0, y - m):min(h, y + ch + m), max(0, x - m):min(w, x + cw + m)]
            if crop.size > 0:
                return crop
        return img

    def _four_point_transform(self, img: np.ndarray, pts: np.ndarray) -> np.ndarray | None:
        if not CV2_OK:
            return None
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
            dst = np.array([[0, 0], [mW - 1, 0], [mW - 1, mH - 1], [0, mH - 1]], dtype=np.float32)
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

    def deskew(self, img: np.ndarray) -> tuple[np.ndarray, float]:
        """Endereza la imagen si está inclinada. Devuelve (imagen, ángulo_grados)."""
        if not CV2_OK:
            return img, 0.0
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        binary = self.filtered_mask(binary)
        angle = self._estimate_skew(binary, img.shape[1])
        if angle is None or abs(angle) < 0.25:
            return img, 0.0
        if abs(angle) > MAX_DESKEW_DEG:
            logger.warning("Inclinación %.1f° fuera del límite, no se corrige", angle)
            return img, 0.0
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
        return rotated, float(angle)

    def _estimate_skew(self, mask: np.ndarray, width: int) -> float | None:
        edges = cv2.Canny(mask, 50, 150)
        # F5 — HoughLinesP da segmentos con extremos: medimos ángulo Y longitud y
        # descartamos las rayas del cuaderno (casi horizontales y que abarcan casi
        # todo el ancho), que si no dominan el Hough y sesgan el baseline real del
        # texto. El texto, fragmentado en letras, no produce segmentos tan largos.
        angles: list[float] = []
        linesp = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=max(50, width // 12),
            minLineLength=max(20, width // 8), maxLineGap=max(3, width // 40),
        )
        if linesp is not None:
            for seg in linesp[:, 0, :]:
                x1, y1, x2, y2 = (int(seg[0]), int(seg[1]), int(seg[2]), int(seg[3]))
                dx, dy = x2 - x1, y2 - y1
                length = (dx * dx + dy * dy) ** 0.5
                a = float(np.degrees(np.arctan2(dy, dx)))
                if a > 90:
                    a -= 180
                elif a < -90:
                    a += 180
                # Raya de cuaderno: casi horizontal y muy larga → ignorar.
                if abs(a) < 1.2 and length >= 0.55 * width:
                    continue
                if abs(a) <= MAX_DESKEW_DEG:
                    angles.append(a)
            if len(angles) >= 2:
                return float(np.median(angles))
        # Fallback: Hough clásico (sin longitud) si lo anterior no dio señal.
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=max(50, width // 12))
        if lines is not None:
            cangles = []
            for line in lines:
                theta = float(line[0][1])
                a = np.degrees(theta) - 90.0
                if abs(a) <= MAX_DESKEW_DEG:
                    cangles.append(a)
            if len(cangles) >= 2:
                return float(np.median(cangles))
        best_angle, best_var = 0.0, -1.0
        for a in np.arange(-MAX_DESKEW_DEG, MAX_DESKEW_DEG + 0.5, 1.0):
            M = cv2.getRotationMatrix2D((mask.shape[1] / 2, mask.shape[0] / 2), a, 1.0)
            rot = cv2.warpAffine(mask, M, (mask.shape[1], mask.shape[0]))
            proj = np.sum(rot > 0, axis=1, dtype=np.float32)
            v = float(np.var(proj))
            if v > best_var:
                best_var = v
                best_angle = a
        return best_angle if abs(best_angle) > 0.3 else None

    # ── Detección del papel (encuadre con fondo oscuro / mano) ─────

    @staticmethod
    def detect_paper_mask(gray: np.ndarray) -> np.ndarray | None:
        """Detecta la región del PAPEL (zona clara grande) en la imagen.

        Pensado para fotos donde el papel no llena el cuadro: hay fondo oscuro,
        sombra lateral o una mano sosteniendo la hoja (img2). El papel es la
        componente brillante más grande; todo lo demás (oscuro) se descarta.

        Devuelve una máscara uint8 (255 = papel) o None cuando el papel ya cubre
        casi todo el cuadro (escaneos limpios como img1/img3): en ese caso no hay
        nada que recortar y aplicar la máscara sería contraproducente.
        """
        if not CV2_OK or gray is None or gray.size == 0:
            return None
        h, w = gray.shape[:2]
        total = float(h * w)

        # Otsu sobre gris suavizado separa "claro" (papel) de "oscuro" (fondo/mano).
        blur = cv2.GaussianBlur(gray, (9, 9), 0)
        _otsu_thr, bright = cv2.threshold(blur, 0, 255,
                                         cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Si casi todo es claro, no hay fondo oscuro que recortar (escaneo limpio).
        bright_frac = float(np.count_nonzero(bright)) / max(1.0, total)
        if bright_frac > 0.93:
            return None

        # OPEN: borra motas brillantes del fondo oscuro (ruido de sensor) que si no
        # se fusionarían con el papel al cerrar y lo inflarían.
        op = max(3, min(h, w) // 120)
        op = op if op % 2 == 1 else op + 1
        bright = cv2.morphologyEx(
            bright, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (op, op)),
        )
        # CLOSE: une el papel (la tinta y sombras suaves dejan huecos) en una sola
        # componente sólida.
        k = max(15, min(h, w) // 25)
        k = k if k % 2 == 1 else k + 1
        closed = cv2.morphologyEx(
            bright, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)),
        )

        num, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
        if num <= 1:
            return None
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        area_frac = float(stats[big, cv2.CC_STAT_AREA]) / total

        # El papel debe ser una porción sustancial del cuadro (evita confundir un
        # reflejo pequeño con el papel) pero no casi todo (ya cubierto arriba).
        if area_frac < 0.20 or area_frac > 0.95:
            return None

        paper = np.where(labels == big, np.uint8(255), np.uint8(0))
        # Rellenar agujeros internos del papel (tinta, sombras) para no perder
        # letras que caen sobre zonas que Otsu marcó oscuras.
        paper = ImagePreprocessor._fill_holes(paper)
        # Erosión: descarta el borde del papel donde se cuela la transición
        # papel→fondo (anillo de tinta espuria). Moderada: la escritura vive en el
        # interior, pero erosionar de más recorta papel útil sin matar el pliegue.
        er = max(9, min(h, w) // 45)
        er = er if er % 2 == 1 else er + 1
        paper = cv2.erode(paper, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (er, er)))

        # Guarda final: tras rellenar/erosionar, si el papel quedó cubriendo casi
        # todo (la imagen era casi todo claro) no aporta y podría dañar — no-op.
        final_frac = float(np.count_nonzero(paper)) / max(1.0, total)
        if final_frac > 0.95:
            return None
        return paper

    @staticmethod
    def _fill_holes(mask: np.ndarray) -> np.ndarray:
        """Rellena agujeros internos (rodeados de blanco) de una máscara binaria.

        Hace flood-fill del FONDO desde un marco exterior de 1px (garantizado
        background): así el "exterior" siempre está conectado a la semilla aunque
        el fondo real esté fragmentado por la propia forma. Lo que el flood NO
        alcanza son agujeros internos → se rellenan.
        """
        h, w = mask.shape[:2]
        padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        ff = padded.copy()
        m = np.zeros((h + 4, w + 4), np.uint8)
        cv2.floodFill(ff, m, (0, 0), 255)
        ff = ff[1:-1, 1:-1]
        holes = cv2.bitwise_not(ff)  # lo que el flood NO alcanzó = agujeros internos
        return cv2.bitwise_or(mask, holes)

    # ── Umbralización y normalización ──────────────────────────────

    @staticmethod
    def normalize_illumination(gray: np.ndarray) -> np.ndarray:
        """Sustrae el fondo estimado por dilatación → iluminación uniforme.

        (Versión original, robusta para escaneos/cuaderno rayado: estima el fondo
        como el máximo local —dilatación— y divide. La penumbra ancha de las fotos
        se trata aparte en `flatten_shadows`, sólo cuando se detecta papel, para no
        alterar este camino que ya funciona bien en hojas limpias.)
        """
        ks = max(51, gray.shape[1] // 10)
        ks = ks if ks % 2 == 1 else ks + 1
        ks = min(ks, 201)
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (ks, ks))
        bg = cv2.morphologyEx(gray, cv2.MORPH_DILATE, k)
        norm = cv2.divide(gray.astype(np.float32), bg.astype(np.float32), scale=255.0)
        return np.clip(norm, 0, 255).astype(np.uint8)

    @staticmethod
    def flatten_shadows(gray: np.ndarray) -> np.ndarray:
        """Aplana sombras/pliegues anchos del papel (caso foto) dividiendo por un
        CLOSE morfológico de kernel mayor que el grosor de los trazos.

        El CLOSE borra la tinta (rellena trazos finos con el papel de alrededor)
        pero conserva la penumbra ancha; dividir gris/fondo cancela esa penumbra y
        deja la tinta. Pensado para llamarse SOLO cuando hay papel detectado, antes
        de la normalización estándar, para no afectar escaneos limpios.
        """
        h, w = gray.shape[:2]
        ks = max(31, min(w, h) // 16)
        ks = ks if ks % 2 == 1 else ks + 1
        ks = min(ks, 151)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ks, ks))
        bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, k)
        bg = cv2.GaussianBlur(bg, (0, 0), ks / 3.0)
        bg = np.maximum(bg, 1)
        flat = cv2.divide(gray.astype(np.float32), bg.astype(np.float32), scale=235.0)
        return np.clip(flat, 0, 255).astype(np.uint8)

    @staticmethod
    def sauvola(gray: np.ndarray, window: int = 25, k: float = 0.20) -> np.ndarray:
        """Thresholding de Sauvola — robusto para escritura a mano con iluminación variable.

        Usa la implementación canónica de scikit-image (`threshold_sauvola`,
        fórmula Sauvola–Pietikäinen con r=128 para 8 bits) cuando está disponible,
        que tolera mejor la iluminación despareja de las fotos (img2) que la
        aproximación casera. Si scikit-image no está, cae a la versión basada en
        OpenCV. En ambos casos devuelve una máscara binaria {0,255} del mismo
        shape (tinta = 255, escritura oscura sobre papel claro).
        """
        win = int(window)
        if win % 2 == 0:  # skimage exige ventana impar
            win += 1
        if SKIMAGE_OK:
            try:
                thr = _sk_threshold_sauvola(gray, window_size=win, k=k, r=128.0)
                return (gray < thr).astype(np.uint8) * 255
            except Exception:  # pragma: no cover - degradar a cv2 ante cualquier fallo
                pass
        # Fallback OpenCV (entorno sin scikit-image)
        g = gray.astype(np.float32)
        mean = cv2.boxFilter(g, cv2.CV_32F, (win, win))
        sq_mean = cv2.boxFilter(g * g, cv2.CV_32F, (win, win))
        std = np.sqrt(np.maximum(0.0, sq_mean - mean * mean))
        threshold = mean * (1.0 + k * (std / 128.0 - 1.0))
        threshold = np.maximum(0.0, threshold)
        return (g < threshold).astype(np.uint8) * 255

    @staticmethod
    def enhance_contrast(gray: np.ndarray) -> np.ndarray:
        """Realza letras tenues/de bajo contraste (img3) antes de binarizar.

        Combina dos técnicas de scikit-image:
          • `equalize_adapthist` (CLAHE de skimage) ecualiza por regiones para
            que la tinta gris pálida gane separación respecto al papel.
          • `rescale_intensity` con percentiles (2–98) estira el histograma
            recortando extremos, levantando trazos muy claros sin saturar.
        Se aplican en cascada y se devuelve un gris uint8 del mismo shape.

        Si scikit-image no está, devuelve el gris sin tocar (el CLAHE de OpenCV
        del flujo principal ya aporta algo de realce). Pensado como ENTRADA extra
        para la votación de binarización, no para reemplazar al gris normalizado.
        """
        if not SKIMAGE_OK:
            return gray
        try:
            # CLAHE de skimage: kernel ~ 1/8 del lado para regiones amplias.
            h, w = gray.shape[:2]
            ksz = max(8, min(h, w) // 8)
            eq = _sk_equalize_adapthist(gray, kernel_size=ksz, clip_limit=0.01)
            eq8 = (np.clip(eq, 0.0, 1.0) * 255.0).astype(np.uint8)
            # Estiramiento por percentiles para recortar extremos de ruido.
            p2, p98 = np.percentile(eq8, (2, 98))
            if p98 - p2 < 5:  # contraste ya plano → no forzar
                return eq8
            stretched = _sk_rescale_intensity(
                eq8, in_range=(float(p2), float(p98)), out_range=(0, 255)
            )
            return stretched.astype(np.uint8)
        except Exception:  # pragma: no cover
            return gray

    @staticmethod
    def _estimate_text_height(gray: np.ndarray) -> int:
        """Estima el alto típico de letra (px) para dimensionar la ventana Sauvola.

        Una binarización Otsu rápida + componentes conexas: la mediana de la
        altura de las componentes "grandes" (las letras dominan en número) es una
        referencia barata del alto de renglón. La ventana de Sauvola debe ser algo
        mayor que el grosor del trazo pero del orden del alto de letra para captar
        la variación de iluminación local sin difuminar la tinta. Devuelve 0 si no
        hay nada claro (deja que el llamador use un valor por defecto).
        """
        try:
            _, b = cv2.threshold(gray, 0, 255,
                                 cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            num, _, stats, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
            if num <= 1:
                return 0
            hs = stats[1:, cv2.CC_STAT_HEIGHT].astype(np.float64)
            ar = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
            hs = hs[ar >= MIN_COMP_AREA]
            if hs.size == 0:
                return 0
            # Mediana del tercio más alto: ignora motas, sigue las letras reales.
            top = np.sort(hs)[::-1][: max(1, hs.size // 3)]
            return int(np.median(top))
        except Exception:  # pragma: no cover
            return 0

    @staticmethod
    def filtered_mask(mask: np.ndarray) -> np.ndarray:
        """Elimina componentes de ruido (demasiado pequeños)."""
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        out = np.zeros_like(mask)
        for i in range(1, num):
            a = int(stats[i, cv2.CC_STAT_AREA])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            if a >= MIN_COMP_AREA and w >= MIN_CHAR_W and h >= MIN_CHAR_H:
                out[labels == i] = 255
        return out

    @staticmethod
    def _denoise_specks(mask: np.ndarray) -> np.ndarray:
        """Borra componentes de ruido (granulado del papel) en fotos.

        Usa el tamaño TÍPICO de los componentes grandes (las letras) como escala:
        cualquier componente mucho más pequeño que la letra mediana es mota de
        textura/sombra y se descarta. Conservador: si no hay componentes grandes
        claros (línea casi vacía), no borra nada para no perder escritura tenue.
        """
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if num <= 2:
            return mask
        areas = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
        heights = stats[1:, cv2.CC_STAT_HEIGHT].astype(np.float64)
        # Referencia de "letra": mediana de las componentes del tercio superior por área.
        big = np.sort(areas)[::-1]
        ref_area = float(np.median(big[: max(1, len(big) // 3)]))
        ref_h = float(np.median(heights[heights >= np.percentile(heights, 60)]))
        if ref_area < 30 or ref_h < 6:
            return mask  # nada claramente "letra" → no arriesgar
        # Umbral de mota: < 6% del área de letra Y baja altura → ruido.
        min_area = max(MIN_COMP_AREA, ref_area * 0.06)
        min_h = max(MIN_CHAR_H, ref_h * 0.30)
        out = np.zeros_like(mask)
        for i in range(1, num):
            a = float(stats[i, cv2.CC_STAT_AREA])
            hh = float(stats[i, cv2.CC_STAT_HEIGHT])
            if a >= min_area or hh >= min_h:
                out[labels == i] = 255
        return out

    @staticmethod
    def _remove_hdashes(mask: np.ndarray) -> np.ndarray:
        """Borra GUIONES horizontales: fragmentos de renglón rayado roto (caso foto).

        En una foto de hoja rayada, la línea del cuaderno no sale entera (como en
        un escaneo limpio que `remove_lines` ya maneja) sino partida en trocitos
        horizontales por la tinta y la deformación de la perspectiva. Esos trocitos
        son demasiado cortos para `remove_lines` (no alcanzan el % de fila) y para
        `_remove_long_lines` (no son tan anchos), así que sobreviven y se reparten
        como "letras" falsas, desalineando todo el renglón.

        Criterio (conservador, sólo camino "papel detectado"): una componente es
        guion si es MUCHO más ancha que alta (≥4×), bastante BAJA respecto al alto
        de letra típico (≤45%) y tiene un ancho mínimo apreciable. Se calcula el
        alto de letra como la mediana de las componentes altas; si no hay letras
        claras no se toca nada (evita comerse escritura tenue).
        """
        _h, w = mask.shape[:2]
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if num <= 2:
            return mask
        heights = stats[1:, cv2.CC_STAT_HEIGHT].astype(np.float64)
        areas = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
        tall = heights[(areas >= MIN_COMP_AREA)]
        if tall.size == 0:
            return mask
        ref_h = float(np.median(np.sort(tall)[::-1][: max(1, tall.size // 3)]))
        if ref_h < 8:
            return mask  # sin un alto de letra fiable, no arriesgar
        min_w = max(8, int(w * 0.03))
        out = mask.copy()
        for i in range(1, num):
            cw = int(stats[i, cv2.CC_STAT_WIDTH])
            ch = int(stats[i, cv2.CC_STAT_HEIGHT])
            # Una letra real nunca es a la vez ≥3× más ancha que alta Y muy baja:
            # las anchas (m, w) son altas; las bajas (guiones, restos de renglón) no
            # son letras. Doble condición → seguro.
            is_dash = (cw >= 3 * max(1, ch)) and (ch <= 0.40 * ref_h) and (cw >= min_w)
            if is_dash:
                out[labels == i] = 0
        return out

    @staticmethod
    def _remove_long_lines(mask: np.ndarray) -> np.ndarray:
        """Borra componentes muy anchos/elongados (borde o pliegue del papel).

        En una foto, el filo y el pliegue del papel binarizan como trazos largos
        que cruzan casi toda la imagen. Ninguna letra suelta es tan ancha, así que
        eliminar las componentes cuyo ancho supera ~45% del ancho de la imagen (o
        que son extremadamente elongadas horizontalmente) limpia esos artefactos
        sin tocar letras. Sólo se usa en el camino "papel detectado" (foto).
        """
        _h, w = mask.shape[:2]
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        out = mask.copy()
        max_w = int(w * 0.45)
        for i in range(1, num):
            cw = int(stats[i, cv2.CC_STAT_WIDTH])
            ch = int(stats[i, cv2.CC_STAT_HEIGHT])
            very_wide = cw >= max_w
            elongated = cw >= 8 * max(1, ch) and cw >= w * 0.18
            if very_wide or elongated:
                out[labels == i] = 0
        return out

    @staticmethod
    def _gate_text_rows(mask: np.ndarray) -> np.ndarray:
        """Conserva el BLOQUE de texto (renglones contiguos) y descarta lo demás.

        En una foto, el borde/pliegue curvo del papel y el granulado generan
        renglones falsos lejos de la escritura. La escritura forma un bloque de
        pocas líneas con MUCHAS componentes pequeñas (letras); el pliegue es un
        bloque con POCAS componentes grandes/elongadas. Aquí:
          1. Marcamos filas con tinta y las agrupamos en bloques contiguos
             (uniendo huecos pequeños = interlínea).
          2. Puntuamos cada bloque por cuántas componentes con forma de LETRA
             contiene (no por masa de tinta, que el pliegue también tiene).
          3. Conservamos el mejor bloque y los cercanos con puntaje comparable.

        Conservador: si no hay un pico de densidad claro, no toca nada (escritura
        muy tenue, p.ej. escaneo gris — que de todos modos no entra por aquí).
        """
        h, w = mask.shape[:2]
        if h < 10:
            return mask
        rowden = (mask > 0).sum(axis=1).astype(np.float32) / max(1, w)
        ksz = max(3, (h // 80) | 1)
        sm = cv2.GaussianBlur(rowden.reshape(-1, 1), (1, ksz), 0).flatten()
        peak = float(sm.max())
        if peak < 0.03:
            return mask
        keep_thr = max(0.014, peak * 0.13)
        keep = sm >= keep_thr
        if not keep.any():
            return mask

        # Agrupar filas marcadas en bloques, uniendo huecos <= interlínea típica.
        gap_join = max(6, h // 30)
        blocks: list[list[int]] = []
        y = 0
        while y < h:
            if keep[y]:
                y0 = y
                while y < h and keep[y]:
                    y += 1
                y1 = y
                if blocks and y0 - blocks[-1][1] <= gap_join:
                    blocks[-1][1] = y1
                else:
                    blocks.append([y0, y1])
            else:
                y += 1
        if len(blocks) <= 1:
            return mask  # un solo bloque → nada que descartar

        # Componentes con forma de letra: ni motas, ni trazos enormes/elongados,
        # ni fragmentos finos del pliegue (baja altura). Usamos la altura típica de
        # las componentes grandes como referencia de "alto de letra": los trozos del
        # pliegue son mucho más bajos que una letra real.
        num, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
        all_h = stats[1:, cv2.CC_STAT_HEIGHT].astype(np.float64) if num > 1 else np.empty(0)
        ref_h = float(np.percentile(all_h, 75)) if all_h.size else 0.0
        min_letter_h = max(MIN_CHAR_H, ref_h * 0.45)
        letters_y: list[float] = []
        for i in range(1, num):
            a = int(stats[i, cv2.CC_STAT_AREA])
            cw = int(stats[i, cv2.CC_STAT_WIDTH])
            ch = int(stats[i, cv2.CC_STAT_HEIGHT])
            if a < 20:
                continue
            if cw >= w * 0.30:            # demasiado ancho → línea/pliegue
                continue
            if cw >= 6 * max(1, ch):      # muy elongado horizontal → trazo
                continue
            if ch < min_letter_h:         # muy bajo → fragmento de pliegue/ruido
                continue
            letters_y.append(float(cents[i][1]))
        letters_y_arr = np.asarray(letters_y) if letters_y else np.empty(0)

        def block_score(b):
            if letters_y_arr.size == 0:
                return float(rowden[b[0]:b[1]].sum())  # fallback por masa
            return int(np.count_nonzero((letters_y_arr >= b[0]) & (letters_y_arr < b[1])))

        best = max(blocks, key=block_score)
        best_score = block_score(best)
        if best_score <= 0:
            return mask
        # "Cercano" = a lo sumo ~1.5x la altura del bloque de texto: renglones del
        # mismo abecedario están pegados; el pliegue queda más lejos y se descarta.
        best_h = best[1] - best[0]
        near = max(h // 12, int(best_h * 1.5))

        def keep_block(b):
            if b is best:
                return True
            # Conservar otro bloque sólo si aporta varias letras (otro renglón
            # real), no un pliegue con unos pocos fragmentos altos.
            if block_score(b) < max(3, best_score * 0.45):
                return False
            return (b[0] - best[1] <= near) and (best[0] - b[1] <= near)

        keep_blocks = [b for b in blocks if keep_block(b)]
        margin = max(4, h // 40)
        band = np.zeros(h, dtype=bool)
        for b in keep_blocks:
            band[max(0, b[0] - margin):min(h, b[1] + margin)] = True
        out = mask.copy()
        out[~band, :] = 0
        # Recorte vertical fino: dejar la banda ceñida a las filas con tinta real
        # (sin colas vacías que vuelvan "alto" un renglón y confundan el split).
        rows_ink = np.where(out.sum(axis=1) > 0)[0]
        if rows_ink.size:
            top = max(0, int(rows_ink[0]))
            bot = min(h, int(rows_ink[-1]) + 1)
            out[:top, :] = 0
            out[bot:, :] = 0
        return out

    def remove_lines(self, mask: np.ndarray) -> np.ndarray:
        """Elimina líneas horizontales de cuaderno preservando trazos verticales."""
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

    # ── Preprocesamiento completo ──────────────────────────────────

    def full_preprocess(
        self, img: np.ndarray, opts
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Preprocesamiento completo: papel + normalización + multi-threshold + limpieza.

        Devuelve (gray_normalizado, thresh_raw, mask_limpia).
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Encuadre: detectar la región del PAPEL cuando no llena el cuadro
        # (fondo oscuro/sombra/mano, p.ej. una foto). None ⇒ escaneo limpio (no-op).
        # Para no crear un borde artificial papel↔relleno que la normalización
        # convierta en un anillo de "tinta", rellenamos el exterior con el brillo
        # MEDIANO del papel (transición suave) en vez de blanco puro. La tinta que
        # igual aparezca fuera del papel se borra al final confinando la máscara.
        paper_mask = self.detect_paper_mask(gray)
        if paper_mask is not None:
            inside = paper_mask > 0
            fill = int(np.median(gray[inside])) if np.any(inside) else 255
            gray = gray.copy()
            gray[~inside] = fill
            # Foto: aplanar pliegues/penumbra anchos del papel ANTES de normalizar.
            gray = self.flatten_shadows(gray)
            logger.info("Papel detectado: %.0f%% del cuadro (relleno exterior=%d)",
                        100.0 * float(np.count_nonzero(paper_mask)) / max(1, paper_mask.size),
                        fill)

        gray = self.normalize_illumination(gray)
        # Mediana: borra la textura/granulado fino del papel (especialmente en
        # fotos con sombra) que la binarización confundiría con tinta, sin comerse
        # los trazos (más gruesos). Suave para no dañar escritura tenue (img3).
        gray = cv2.medianBlur(gray, 3)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        img_w = gray.shape[1]
        tile = max(8, min(32, img_w // 60))
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(tile, tile))
        enhanced = clahe.apply(gray)

        # Ventana de Sauvola. Por defecto se conservan los valores afinados para
        # escaneos limpios (25 / 41), que ya extraen muy bien hojas rayadas y de
        # bajo contraste. SÓLO en el camino "papel detectado" (foto con luz
        # despareja, img2) la dimensionamos en proporción al alto de letra: ahí una
        # ventana mayor (≈1.5×–2.3× la letra) capta la variación de iluminación
        # local sin partir trazos, que es la recomendación para escaneo de
        # documentos. (Medido: img2 sube de 12 a 13 glifos vs. ventana fija.)
        if paper_mask is not None:
            txt_h = self._estimate_text_height(enhanced)
            base = txt_h if txt_h > 0 else 31
            win_s = int(np.clip(int(base * 1.5) | 1, 31, 95))
            win_l = int(np.clip(int(base * 2.3) | 1, 51, 141))
        else:
            win_s, win_l = 25, 41

        # Votación de 5 estrategias de umbralización (sobre el gris realzado cv2).
        _, m1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        m2 = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 8)
        m3 = self.sauvola(enhanced, window=win_s, k=0.14)
        m4 = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 19, 6)
        m5 = self.sauvola(enhanced, window=win_l, k=0.20)

        vote = ((m1 > 0).astype(np.int16) + (m2 > 0).astype(np.int16)
                + (m3 > 0).astype(np.int16) + (m4 > 0).astype(np.int16)
                + (m5 > 0).astype(np.int16))

        mask = np.where(vote >= 2, np.uint8(255), np.uint8(0))
        ink_ratio = np.sum(mask > 0) / max(1, mask.size)

        # Rescate de letras MUY tenues / ink-starved (escritura gris pálida que casi
        # no cruza el umbral): si el consenso deja muy poca tinta, el cuello de
        # botella suele ser de CONTRASTE, no de iluminación. Realzamos con
        # scikit-image (CLAHE adaptativo + estiramiento por percentiles) y volvemos a
        # binarizar; esa máscara recupera trazos pálidos. Se confirma con Otsu del
        # realce para no traer ruido y sólo se incorpora si la cobertura resultante
        # sigue siendo razonable de documento. Conservador (umbral bajo): a cobertura
        # moderada el realce tiende a sumar textura/granulado en vez de letras, así
        # que NO se aplica ahí — evita "muchas componentes pero desalineadas".
        if ink_ratio < 0.012:
            enh2 = self.enhance_contrast(gray)
            faint = self.sauvola(enh2, window=win_s, k=0.12)
            _, otsu2 = cv2.threshold(enh2, 0, 255,
                                     cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            faint = cv2.bitwise_and(faint, otsu2)
            merged = np.where((vote >= 1) | (faint > 0), np.uint8(255), np.uint8(0))
            mr = np.sum(merged > 0) / max(1, merged.size)
            if 0.004 <= mr <= 0.12:
                mask = merged
                logger.debug("Rescate contraste (skimage): ratio %.4f→%.4f",
                             ink_ratio, mr)
            elif ink_ratio < 0.008:
                # Rescate no concluyente y tinta de verdad escasa: relajar el consenso
                # a ≥1 como hacía el flujo previo (mejor algo que nada).
                mask = np.where(vote >= 1, np.uint8(255), np.uint8(0))
                logger.debug("Votación relajada a ≥1 (ratio=%.4f)", ink_ratio)
            # Resto rechazado → conservar la máscara de consenso ≥2 original.

        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

        # Confinar la tinta al papel: aunque rellenamos el fondo, el borde
        # papel→fondo puede dejar un anillo de ruido. Lo recortamos con la máscara
        # y, como es una foto (no escaneo limpio), limpiamos motas más fuerte: el
        # granulado/sombra del papel deja puntos y filamentos sueltos que generan
        # renglones falsos. La escritura fotografiada suele ser gruesa, así que un
        # OPEN moderado la respeta, y borramos componentes finos (ruido) por área.
        if paper_mask is not None:
            mask[paper_mask == 0] = 0
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            mask = self._denoise_specks(mask)

        raw = mask.copy()

        if opts.remove_lines:
            mask = self.remove_lines(mask)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))

        clean = self.filtered_mask(mask)

        # Foto: limpiar artefactos del encuadre que generan renglones falsos y
        # desbaratan el reparto del texto de referencia. Primero borramos los
        # trazos largos (filo/pliegue del papel) y luego descartamos las franjas
        # de filas dispersas (granulado). Sólo en el camino "papel detectado"
        # para no tocar escaneos limpios (que ya funcionan).
        if paper_mask is not None:
            clean = self._remove_hdashes(clean)
            clean = self._remove_long_lines(clean)
            clean = self._gate_text_rows(clean)

        return gray, raw, clean

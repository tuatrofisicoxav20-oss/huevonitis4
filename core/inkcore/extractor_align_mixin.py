"""AlignmentMixin — orquestación de alineación del GlyphExtractor.

Separado de extractor.py (Fase 4.3 — extractor refactor) para mantener los
archivos por debajo de ~420 líneas. Agrupa el método maestro `_align_pos`
(pipeline hybrid_v2 + fallback de 3 etapas + anclaje Tesseract), los wrappers
`_align_*` que delegan a extractor_alignment, y la segmentación por palabras
(`_segment_words`, `_find_word_gaps`, `_wf`) más el benchmark de estrategias
(`_test_all_strategies`).

GlyphExtractor hereda de esta clase. `BBox` se importa de forma diferida dentro
de los métodos para evitar el import circular con extractor.py.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.inkcore.extractor import BBox

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

logger = logging.getLogger(__name__)


class AlignmentMixin:
    """Pipeline de alineación de glifos; mezclado en GlyphExtractor."""

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
    ) -> list[tuple[BBox, str, float]]:
        """Segmenta cada palabra de forma independiente usando los bounds dados."""
        from core.inkcore.extractor import BBox
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

    # ── Helpers de combinación de estrategias (gap-segment vs CNN) ──────

    def _bounds_to_result(
        self, line_mask: np.ndarray, chars: list[str], bounds: list[int],
    ) -> list[tuple[BBox, str, float]]:
        """Convierte n+1 fronteras en la lista (BBox, char, align_score)."""
        from core.inkcore.extractor import BBox
        h, w = line_mask.shape[:2]
        result: list[tuple[BBox, str, float]] = []
        for i, ch in enumerate(chars):
            x1 = bounds[i]
            x2 = min(bounds[i + 1], w)
            bw = max(1, x2 - x1)
            ink = float(np.sum(line_mask[:, x1:x2] > 0))
            cov = ink / max(1, h * bw)
            result.append((BBox(x1, 0, bw, h), ch, min(1.0, max(0.1, cov / 0.18))))
        return result

    def _count_consistent(
        self, line_mask: np.ndarray, chars: list[str], bounds: list[int], line_m,
    ) -> int:
        """Cuántas letras quedarían estructuralmente consistentes con estos cortes.

        Es el mismo filtro duro que aplica _extract_pass (is_consistent sobre la
        extensión vertical del blob refinado), así que predice bien cuántos glifos
        sobrevivirán. Sirve para elegir entre particiones rivales (gaps vs CNN).
        """
        from core.inkcore.extractor_validation import is_consistent
        w = line_mask.shape[1]
        cnt = 0
        for i, ch in enumerate(chars):
            x1 = bounds[i]
            x2 = min(bounds[i + 1], w)
            if x2 <= x1:
                continue
            rx1, ry1, rx2, ry2 = self._refine_char_region(line_mask, x1, x2)
            if not is_consistent(ch, ry1, ry2, line_m):
                continue
            # Exigir cobertura real: una región que pasa is_consistent pero está
            # casi vacía (corte sobre un hueco) no produciría un glifo bueno, así
            # que no debe inflar el puntaje de su estrategia.
            ink = float(np.sum(line_mask[ry1:ry2, rx1:rx2] > 0))
            area = max(1, (ry2 - ry1) * max(1, rx2 - rx1))
            if ink / area >= 0.06:
                cnt += 1
        return cnt

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
        from core.inkcore.extractor import BBox
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

        # ── Segmentación por GAPS reales entre letras (antes que la posicional) ──
        # Para letras separadas (abecedario, imprenta) los espacios entre letras
        # son fronteras mucho más fiables que repartir el ancho por posición, que
        # junta vecinas ('c'+'d'→"cd") y corre las etiquetas. Devuelve None ante
        # escritura ligada sin gaps claros, y ahí seguimos con la posicional.
        from core.inkcore.extractor_gap_segment import segment_by_gaps
        gap_bounds = segment_by_gaps(vpp, x_min, x_max, n)

        # ── Juez de cortes por CNN + gaps reales: elegir el mejor por renglón ──
        # gap-segment es fiable para letras separadas; el CNN (over-segmentación +
        # DP guiado por reconocimiento) ataca la letra ligada sin gaps. Cuando hay
        # clasificador entrenado, calculamos ambas particiones y nos quedamos con
        # la que deja MÁS letras estructuralmente consistentes (la forma coincide
        # con la letra que la posición le asignó). Sin clasificador, gap-segment
        # decide solo, como antes.
        clf = getattr(self, "_char_classifier", None)
        if clf is not None and getattr(clf, "available", False):
            # TODO el bloque va protegido: si cualquier parte del ensemble CNN
            # falla, registramos y caemos al pipeline clásico — nunca devolvemos
            # 0 glifos por un error de la IA.
            try:
                from core.inkcore.extractor_cnn_align import align_by_classifier
                from core.inkcore.extractor_validation import line_metrics
                cnn_bounds = align_by_classifier(line_mask, chars, clf, char_w_avg, self._wf)
                line_m = line_metrics(line_mask)
                candidates: list[tuple[str, list[int]]] = []
                if gap_bounds is not None and len(gap_bounds) == n + 1:
                    candidates.append(("gap-segment", gap_bounds))
                if cnn_bounds is not None and len(cnn_bounds) == n + 1:
                    candidates.append(("cnn-align", cnn_bounds))
                # Ensemble de segmentación: todas las estrategias compiten y el
                # árbitro (consistencia estructural) elige la mejor por renglón.
                # Cada una acierta en regímenes distintos (gaps, ligado,
                # posicional); la unión cubre más casos que cualquiera sola.
                extra = [
                    ("hybrid_v2", lambda: self._align_hybrid_v2(vpp, line_mask, x_min, x_max, n, chars)),
                    ("dp_energy", lambda: self._align_dp_energy(vpp, x_min, x_max, n)),
                    ("cc_first", lambda: self._align_cc_first(line_mask, x_min, x_max, n)),
                    ("vpp_only", lambda: self._align_vpp_only(vpp, x_min, x_max, n)),
                    ("inkflow", lambda: self._align_inkflow(vpp, x_min, x_max, chars)),
                ]
                for nm, fn in extra:
                    try:
                        bd = fn()
                    except Exception:
                        continue
                    if bd is not None and len(bd) == n + 1:
                        candidates.append((nm, bd))
                if candidates:
                    name, chosen = max(
                        candidates,
                        key=lambda c: self._count_consistent(line_mask, chars, c[1], line_m),
                    )
                    logger.info("align '%s': %s elegido (%d letras)", text[:40], name, n)
                    return self._bounds_to_result(line_mask, chars, chosen)
            except Exception as exc:
                logger.warning(
                    "ensemble CNN falló (%s); uso pipeline clásico", exc, exc_info=True,
                )

        if gap_bounds is not None and len(gap_bounds) == n + 1:
            logger.info(
                "gap-segment '%s': %d letras por espacios reales", text[:40], n
            )
            return self._bounds_to_result(line_mask, chars, gap_bounds)

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

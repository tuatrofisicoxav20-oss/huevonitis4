"""ExtractionPipelineMixin — pipeline legacy de extracción del GlyphExtractor.

Separado de extractor.py (Fase 4.3 — extractor refactor) para mantener los
archivos por debajo de ~420 líneas. Agrupa el flujo legacy `_run` (preprocesa,
detecta líneas y reintenta con parámetros relajados), la preparación del texto
de referencia (`_clean_ref`, `_prepare_ref_lines`) y la pasada de extracción por
banda (`_extract_pass`).

GlyphExtractor hereda de esta clase. Los símbolos definidos en extractor.py
(`BBox`, `ExtractionOptions`, `CHAR_PAD`, `_purge_temp_pngs`) se importan de forma
diferida dentro de los métodos para evitar el import circular con extractor.py.
"""
import logging
import re
from pathlib import Path

import config
from core.inkcore.extractor_hashing import (
    dual_dist as _dual_dist,
)
from core.inkcore.extractor_hashing import (
    dual_hash as _dual_hash,
)
from core.models import GlyphEntry

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

logger = logging.getLogger(__name__)


class ExtractionPipelineMixin:
    """Flujo legacy de extracción por bandas; mezclado en GlyphExtractor."""

    # ── Pipeline principal ─────────────────────────────────────────

    def _run(self, path: str, ref_text: str, opts: "ExtractionOptions") -> list[GlyphEntry]:
        from core.inkcore.extractor import ExtractionOptions, _purge_temp_pngs
        from core.inkcore.extractor_preprocess import imread_oriented, orient_by_content
        img = imread_oriented(path)  # F5 — respeta orientación EXIF de fotos de celular
        if img is None:
            return []
        # Paso 2 (5ta tanda) — orientación por contenido/OSD o manual: WhatsApp borra
        # el EXIF al rotar; esto endereza 90/180/270 ANTES del deskew fino.
        img = orient_by_content(img, getattr(opts, "manual_orientation", None))

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
        _purge_temp_pngs(temp_dir)  # higiene: descartar huérfanos de extracciones previas

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
        clean: "np.ndarray",
        line_boxes: list["BBox"],
        ref_lines: list[str],
        median_line_h: float,
        opts: "ExtractionOptions",
        temp_dir: Path,
    ) -> list[GlyphEntry]:
        """Pasada de extracción sobre una máscara y bandas dadas."""
        from core.inkcore.extractor import CHAR_PAD
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

            # Métricas verticales de la línea (x-height/baseline) para validar que
            # la forma de cada glifo coincida con la letra que la posición le asignó.
            from core.inkcore.extractor_validation import is_consistent, line_metrics
            line_m = line_metrics(line_mask)

            for gbox, char, align_score in aligned:
                if counts.get(char, 0) >= opts.max_per_char:
                    continue

                # Refinar límites al blob dominante + diacríticos (punto de i, acentos, ñ)
                rx1, ry1, rx2, ry2 = self._refine_char_region(
                    line_mask, gbox.x, gbox.x2
                )

                # Validación estructural: si la forma contradice claramente la letra
                # esperada ('a' con ascendente = probable 'd' por alineación
                # desplazada), descartar en vez de guardar mal etiquetado.
                if not is_consistent(char, ry1, ry2, line_m):
                    logger.info(
                        "extract: descarto '%s' por forma inconsistente "
                        "(y=%d-%d, alineación desplazada?)", char, ry1, ry2,
                    )
                    continue
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
                # Gate de EXACTITUD: un glifo sólo llega a Gold si está VERIFICADO.
                #  • Si el CNN reconoce el recorte como otra letra con confianza →
                #    Bronze (confusión clara, p.ej. una 'j' con forma de 'z').
                #  • Si el CNN NO ve la letra esperada en su top-3 → tope Silver,
                #    aunque la forma sea "limpia": así una raya/fragmento/esquina
                #    que el modelo no valida deja de salir como Gold (foto mala).
                #  • Gate geométrico (sin CNN o ñ): un trazo tipo raya/fragmento
                #    tampoco puede ser Gold.
                verified_gold = True
                clf = getattr(self, "_char_classifier", None)
                if clf is not None and getattr(clf, "available", False):
                    try:
                        from core.inkcore.ai.char_cnn import char_to_label
                        if char_to_label(char) is not None:  # a-z (la ñ no la maneja)
                            topk = clf.predict_topk(crop, k=3)
                            in_top = bool(topk) and any(c == char.lower() for c, _ in topk)
                            if topk:
                                _top_c, top_p = topk[0]
                                if not in_top and top_p > 0.55:
                                    qs = min(qs, 0.40)  # confusión clara → Bronze
                            # Gold exige que el CNN confirme la letra esperada.
                            verified_gold = in_top
                    except Exception as _gate_exc:
                        logger.debug("gate CNN omitido: %s", _gate_exc)
                # Gate geométrico universal: trazo demasiado fino (raya) o tinta
                # repartida en pedazos (fragmento) no es una letra escrita → no Gold.
                from core.inkcore.quality import classify_tier, is_geometric_garbage
                if is_geometric_garbage(quality.get("sw_score", 1.0),
                                        quality.get("solidity", 1.0)):
                    verified_gold = False
                tier = classify_tier(qs)
                if tier == "Gold" and not verified_gold:
                    tier = "Silver"  # alta calidad pero sin verificar → tope Silver
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

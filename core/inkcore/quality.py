from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import numpy as np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


# ── Umbrales de tier: FUENTE ÚNICA para todo el extractor ──────────────
# Cualquier corte Gold/Silver del proyecto debe pasar por classify_tier; no
# hardcodear estos números en otros módulos (assess_glyph, extraction_pipeline,
# _extract_pass los consumen desde aquí).
TIER_GOLD = 0.75
TIER_SILVER = 0.48


def classify_tier(score: float) -> str:
    """Tier de un glifo por su score final: Gold≥0.75, Silver≥0.48, si no Bronze."""
    if score >= TIER_GOLD:
        return "Gold"
    if score >= TIER_SILVER:
        return "Silver"
    return "Bronze"


def _largest_cc_ratio(mask: "np.ndarray") -> float:
    """Fracción de píxeles de tinta que caen en el componente conexo más grande.

    1.0 = todo el trazo es una sola pieza (o no hay tinta); valores bajos = la
    tinta está repartida en pedazos sueltos (ruido / fragmentos / dos letras).

    Usa cv2 si está disponible (camino normal de la app) y, si no, scipy.ndimage;
    sin ninguno de los dos devuelve 1.0 (no penaliza, comportamiento neutro).
    """
    total = int(mask.sum())
    if total <= 0:
        return 1.0
    m = mask.astype(np.uint8)
    try:
        import cv2  # dependencia normal del proyecto
        num, _lab, stats, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
        if num < 2:
            return 1.0
        largest = int(np.max(stats[1:, cv2.CC_STAT_AREA]))
        return largest / total
    except Exception:
        pass
    try:
        from scipy import ndimage
        labels, num = ndimage.label(m)
        if num < 1:
            return 1.0
        counts = np.bincount(labels.ravel())[1:]
        return int(counts.max()) / total if counts.size else 1.0
    except Exception:
        return 1.0


def assess_glyph(image_path: str) -> dict:
    """Returns quality metrics for a glyph PNG file."""
    if not PIL_OK or not NUMPY_OK:
        return {"score": 0.5, "tier": "Bronze", "ink_coverage": 0.5, "valid": True}
    try:
        img = Image.open(image_path).convert("RGBA")
        arr = np.array(img).astype(np.float32)
        # Presencia de tinta del canal con SEÑAL REAL (mayor rango dinámico):
        # el alpha para glifos del extractor (forma en alpha), o la luminancia
        # invertida para glifos OPACOS (bulk/legacy, alpha=255 uniforme). Medir
        # alpha a ciegas contaba alpha=255 como tinta total → ink_coverage=1.0 y
        # tier Gold inflado para un opaco con poca tinta. (Consistente con
        # bank._glyph_to_gray.)
        alpha = arr[:, :, 3]
        lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        cand_alpha = alpha / 255.0
        cand_lum = 1.0 - lum / 255.0
        if (cand_alpha.max() - cand_alpha.min()) >= (cand_lum.max() - cand_lum.min()):
            presence = cand_alpha
        else:
            presence = cand_lum
        total = presence.size
        mask = presence > 0.25  # 0.25 ≈ el umbral viejo alpha>64
        ink = int(np.sum(mask))
        ink_coverage = ink / total if total > 0 else 0
        w, h = img.size
        aspect = w / h if h > 0 else 1.0
        # F2 — Banda de aspecto ANCHA y tolerante: sin conocer el char esperado no
        # se debe castigar una 'i'/'l'/puntuación (angostas) ni una 'm'/'w'
        # (anchas). Dentro de [0.10, 1.80] no se penaliza; sólo fuera: aspecto
        # extremo (>1.8) sugiere dos letras pegadas o franja de renglón. El
        # componente además pesa POCO en el score (señal débil frente a la forma).
        if 0.10 <= aspect <= 1.80:
            aspect_score = 1.0
        elif aspect > 1.80:
            aspect_score = max(0.0, 1.0 - (aspect - 1.80) / 1.5)
        else:  # línea finísima (aspect < 0.10)
            aspect_score = max(0.0, aspect / 0.10)
        # Tamaño por el lado MAYOR del glifo: una 'i'/'l' es angosta pero NO
        # diminuta (es alta). Medir por min(w,h) la castigaba por angosta; usar el
        # lado mayor sólo descarta motas de verdad pequeñas.
        size_score = min(1.0, max(w, h) / 30)

        # Solidez: fracción de tinta en el blob conexo dominante. Un glifo bien
        # extraído es 1-2 piezas (cuerpo + diacrítico); un recorte de pura mota o
        # de pedazos sueltos reparte la tinta en muchos blobs → fracción baja.
        # Es la señal que separa "letra real" de "ruido con cobertura decente".
        solidity = _largest_cc_ratio(mask)

        # F2 — Pesos: el aspecto pasa a pesar POCO (0.10); ese peso va a la
        # solidez (forma de letra real = 1-2 piezas), que es la señal fuerte que
        # separa una letra limpia de ruido. Así una 'i'/'m' limpia ya no queda
        # bloqueada bajo Gold por su aspecto, sin inflar ruido: las motas y
        # fragmentos siguen cayendo por los castigos de ink/solidez de abajo.
        score = (ink_coverage * 0.20 + aspect_score * 0.10
                 + size_score * 0.20 + solidity * 0.50)

        # Castigos para glifos claramente malos → que caigan a Bronze/baja:
        #  • Vacío / casi vacío (pura mancha mínima o nada de tinta).
        #  • Dos letras pegadas o franja de renglón: aspect muy ancho.
        #  • Tinta dispersa (solidez baja): fragmento o ruido.
        if ink_coverage < 0.02 or ink < 12:
            score = min(score, 0.15)
        if aspect >= 2.0:                       # mucho más ancho que alto
            score *= max(0.30, 1.0 - (aspect - 2.0) * 0.5)
        if solidity < 0.55:                     # sin cuerpo dominante
            score *= 0.40 + 0.60 * (solidity / 0.55)

        score = round(min(1.0, max(0.0, score)), 3)
        tier = classify_tier(score)
        return {"score": score, "tier": tier, "ink_coverage": round(ink_coverage, 3), "valid": True}
    except Exception as e:
        logger.warning(f"Quality assess failed for {image_path}: {e}")
        return {"score": 0.3, "tier": "Bronze", "ink_coverage": 0.3, "valid": False}


def compute_final_quality(
    base_quality: float,
    label_confidence: float | None,
    agreement_score: float,
    config,
) -> float:
    """Combina calidad base, acuerdo entre detectores y confianza del labeler.

    Args:
        base_quality: score raw de assess_glyph() (0-1).
        label_confidence: confianza del labeler ganador (0-1), o None si no hubo labeler.
        agreement_score: fracción de detectores que coincidieron (0-1).
        config: PipelineConfig con label_conf_weight y min_quality.

    Returns:
        Score final clampado a [0, 1].
    """
    final = base_quality * (0.7 + 0.3 * agreement_score)
    if label_confidence is not None:
        weight = getattr(config, "label_conf_weight", 0.3)
        if weight > 0:
            # F3 — boost ACOTADO a [0.85, 1.10]: la confianza del labeler ajusta
            # poco; no puede por sí sola convertir calidad mediocre en Gold.
            boost = 1.0 + weight * (label_confidence - 0.5)
            boost = max(0.85, min(1.10, boost))
            final *= boost
    # F3 — el boost no fabrica Golds desde calidad POBRE: si la calidad base (la
    # forma del glifo, sin acuerdo ni confianza) no alcanza siquiera Silver, el
    # resultado final no puede cruzar el umbral Gold por mucha confianza que haya.
    if base_quality < TIER_SILVER:
        final = min(final, TIER_GOLD - 1e-6)
    return min(1.0, max(0.0, final))

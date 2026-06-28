"""Guardado al banco de los glifos extraídos de una plantilla.

Toma la lista (char, glifo, score) de la extracción y la persiste en el GlyphBank
pasando el gate de captura, conservando el score (con la rebaja del CNN) y la
geometría R1. Separado de template_extract para acotarlo; sólo lo consume la UI y
los tests vía save_template_glyphs_to_bank, que template_extract re-exporta.
"""
from __future__ import annotations

import contextlib
import logging

logger = logging.getLogger(__name__)

try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def _quality_override_from_template(glyph, score, classify_tier) -> dict:
    """Arma el dict {score, tier, ink_coverage} para bank.add_glyph.

    Reutiliza el score de la plantilla (con la rebaja del CNN si la hubo) y mide
    ink_coverage barato del canal alpha del glifo (sin re-evaluar calidad). El
    tier sale de classify_tier con los umbrales del banco. Si algo falla, None
    para que add_glyph caiga a su assess_glyph habitual.
    """
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    s = max(0.0, min(1.0, s))
    ink_cov = 0.5
    try:
        alpha = np.asarray(glyph.getchannel("A"))
        if alpha.size:
            ink_cov = round(float((alpha > 64).mean()), 3)
    except Exception:
        pass
    return {"score": round(s, 3), "tier": classify_tier(s), "ink_coverage": ink_cov}

def save_template_glyphs_to_bank(results, bank, temp_dir=None) -> dict:
    """Guarda los glifos extraídos de la plantilla en el banco dado.

    Escribe cada glifo a un PNG temporal y lo manda a `bank.add_glyph` (que copia
    al banco y persiste). Devuelve {saved, dupes, total}. Pensado para llamarse
    desde la UI con el bank vivo de la app (NO desde un script suelto sobre el
    banco real con la app abierta — colisiona el manifest).

    Se pasa skip_dedup=True a add_glyph: las casillas de la plantilla con
    repeats>1 son intencionalmente la MISMA letra repetida para capturar la
    variación natural de la escritura, y vienen de posiciones distintas de la
    grilla. El dedup perceptual por hamming las rechazaría como duplicados,
    anulando el propósito de repeats y manteniendo el banco artificialmente
    chico — justo esa variación es la que mejora el render. El dedup sigue activo
    en el flujo de imagen suelta (extractor_tab), donde el solapamiento de cajas
    sí puede extraer dos veces el mismo glifo. Por eso saved == total salvo
    errores de I/O, y dupes queda en 0.

    También se pasa quality_override para conservar el score que ya calculó
    extract_from_template (incluida la rebaja a 0.45 del CNN en casillas dudosas)
    en vez de que add_glyph lo recalcule desde cero: así get_best_glyph elige las
    muestras buenas de otras hojas y no se pierde la bandera de baja confianza.
    """
    import tempfile
    from pathlib import Path

    from core.inkcore.glyph_filters import capture_gate, measure_glyph
    from core.inkcore.quality import classify_tier
    if temp_dir is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="tpl_glyphs_"))
    else:
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
    saved = dupes = rejected = 0
    rejects: list[tuple[str, int, str]] = []
    # Gate de captura: los umbrales relativos se calibran con la mediana de lo
    # YA existente en el banco para ese char (medido una vez por char y tanda);
    # con un char nuevo solo aplican los umbrales absolutos de fallback.
    bank_metrics_cache: dict[str, list] = {}
    for i, (ch, glyph, q) in enumerate(results):
        cached = bank_metrics_cache.get(ch)
        if cached is None:
            cached = []
            for e in bank.get_all(char_filter=ch):
                try:
                    with Image.open(e.image_path) as im:
                        cached.append(measure_glyph(im.convert("RGBA")))
                except Exception:
                    continue
            bank_metrics_cache[ch] = cached
        ok, reason = capture_gate(glyph, ch, cached)
        if not ok:
            rejected += 1
            rejects.append((ch, i, reason))
            logger.info("gate de captura: '%s' celda #%d rechazado — %s", ch, i, reason)
            continue
        # ch[0]: un token multi-char NO alfanumérico (caso latente, hoy ninguno —
        # las ligaduras PARES_FRECUENTES son alnum y caen en la rama `ch`) haría
        # reventar `ord(ch)`. Mismo guard que char_to_label contra ligaduras.
        safe = ch if ch.isalnum() else f"u{ord(ch[0])}"
        p = temp_dir / f"{safe}_{i:03d}.png"
        try:
            glyph.save(p)
        except Exception as exc:
            logger.warning("save_template: no se pudo escribir %s: %s", p, exc)
            continue
        # Conservar el score ya calculado por extract_from_template (incluida la
        # rebaja a 0.45 que el CNN aplica a las casillas dudosas) en vez de dejar
        # que add_glyph lo recalcule desde cero: así get_best_glyph prefiere las
        # muestras buenas de otras hojas y la bandera de baja confianza no se
        # pierde. ink_coverage se mide barato del alpha del glifo; el tier sale
        # del score con los mismos umbrales del banco.
        override = _quality_override_from_template(glyph, q, classify_tier)
        # R1: la geometría medida en la extracción viaja en Image.info; acá se
        # persiste al manifest junto con el glifo.
        entry = bank.add_glyph(ch, str(p), skip_dedup=True, quality_override=override,
                               geometry=glyph.info.get("geometry"))
        if entry is None:
            dupes += 1
        else:
            saved += 1
    for f in temp_dir.glob("*.png"):
        with contextlib.suppress(OSError):
            f.unlink()
    if rejects:
        _append_reject_log(rejects)
    logger.info("save_template_glyphs_to_bank: saved=%d dupes=%d rejected=%d total=%d",
                saved, dupes, rejected, len(results))
    return {"saved": saved, "dupes": dupes, "rejected": rejected,
            "total": len(results)}

def _append_reject_log(rejects: list[tuple[str, int, str]]) -> None:
    """extract_rechazados.csv: qué celdas de la tanda rebotó el gate y por qué.

    Vive junto al banco (TIPOGRAFIA_DIR) y es acumulativo por tanda, para que
    el usuario sepa qué casillas de la plantilla debe re-escribir.
    """
    import csv
    import time as _time

    import config as _config
    path = _config.TIPOGRAFIA_DIR / "extract_rechazados.csv"
    new = not path.exists()
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp", "char", "celda", "reason"])
            ts = _time.strftime("%Y-%m-%d %H:%M:%S")
            for ch, idx, reason in rejects:
                w.writerow([ts, ch, idx, reason])
    except OSError as exc:
        logger.warning("no se pudo escribir extract_rechazados.csv: %s", exc)

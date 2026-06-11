"""Métricas geométricas por glifo (Fase R1 — causa raíz R-BUG-04).

El renderer no puede posicionar ni escalar bien un glifo que no sabe su
geometría. Este módulo define cómo se MIDE esa geometría:

  • Camino TEMPLATE (medición real): la celda de la plantilla da el marco de
    referencia — su alto es el "em" de la hoja y la tinta dentro de ella da
    alto/ancho natural, baseline y sidebearings. La medición se ADJUNTA al
    ``Image.info["geometry"]`` del glifo para no cambiar la API
    ``(char, glifo, score)`` de template_extract.
  • Camino LEGACY (estimación heurística): para bancos sin template se estima
    por la identidad del carácter (está etiquetado: es señal más fiable que un
    clustering ciego de alturas) + la x-height mediana del banco.

El baseline de las DESCENDENTES no es observable de una celda sin renglón
impreso: se reconstruye como top de tinta + x-height de referencia de la
misma hoja (las letras se escriben a escala consistente dentro de una hoja).
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# Minúsculas con cola bajo el baseline. La puntuación colgante (coma) y la Q
# se tratan como no-descendentes: el error es de ~1-2 px y no amerita casos.
DESCENDERS = frozenset("gjpqy")

# Chars cuya tinta define la x-height pura (sin astas, puntos ni tildes):
# referencia para reconstruir el baseline de las descendentes de la hoja.
XHEIGHT_REF = frozenset("acemnorsuvwxz")

# Sin x-height de referencia en la hoja/banco: fracción cuerpo/alto típica de
# una descendente manuscrita (~62% cuerpo, ~38% cola).
_DESC_BODY_FRAC = 0.62

# Convención del renderer: la x-height ocupa ~45% del renglón (ver
# RenderOptions.__post_init__). El estimador deriva el em legacy de ahí.
_XHEIGHT_TO_EM = 0.45


def measure_ink_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """bbox (x0, y0, x1, y1) EXCLUSIVO de la tinta (mask > 0), o None si vacía."""
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _alpha_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """bbox de la tinta de un glifo RGBA del banco (forma en el alpha)."""
    if not _PIL_OK:
        return None
    a = np.asarray(img.convert("RGBA").getchannel("A"))
    return measure_ink_bbox(a > 40)


def template_geometry(crop_mask: np.ndarray, ch: str, *,
                      em_px: int, lsb: int, rsb: int) -> dict:
    """Geometría de un glifo extraído del template, en coords del CROP final.

    ``crop_mask`` es la máscara ya autocropped (mismo tamaño 1:1 que el RGBA
    que produce to_rgba_smooth). Para descendentes ``baseline_off`` queda None:
    lo completa finalize_sheet_geometry con la x-height de la hoja completa.
    """
    h, w = crop_mask.shape[:2]
    bbox = measure_ink_bbox(crop_mask)
    if bbox is None:
        ink_top, ink_bottom = 0, h
    else:
        _x0, ink_top, _x1, ink_bottom = bbox
    geo = {
        "nat_h_px": int(h),
        "nat_w_px": int(w),
        "em_px": int(max(1, em_px)),
        "lsb": int(max(0, lsb)),
        "rsb": int(max(0, rsb)),
        "metrics_source": "template",
        # internos para el pase final de hoja (no se persisten):
        "_ink_top": int(ink_top),
        "_ink_h": int(ink_bottom - ink_top),
    }
    # Sin renglón impreso en la celda, el baseline observable es el fondo de la
    # tinta — vale para todo lo que ASIENTA en la línea base. Las descendentes
    # meten su cola debajo: se resuelven con la x-height de la hoja. R10: una
    # LIGADURA ("qu") es descendente si cualquiera de sus letras lo es.
    desciende = any(c in DESCENDERS for c in ch)
    geo["baseline_off"] = None if desciende else int(ink_bottom)
    return geo


def finalize_sheet_geometry(results: list) -> None:
    """Completa el baseline de las descendentes con la x-height de SU hoja.

    ``results`` es la lista (char, glifo_PIL, score) de UNA extracción; las
    geometrías parciales viven en glyph.info["geometry"]. La x-height de la
    hoja es la mediana del alto de tinta de los chars de XHEIGHT_REF extraídos
    en la misma pasada; sin referencia cae a _DESC_BODY_FRAC del alto propio.
    Borra las claves internas (_ink_*) al terminar.
    """
    xheights = [
        g["_ink_h"]
        for ch, glyph, _q in results
        if ch in XHEIGHT_REF and (g := glyph.info.get("geometry"))
    ]
    x_ref = int(np.median(xheights)) if xheights else 0
    for ch, glyph, _q in results:
        geo = glyph.info.get("geometry")
        if not geo:
            continue
        if geo.get("baseline_off") is None:
            body = x_ref if x_ref > 0 else int(geo["_ink_h"] * _DESC_BODY_FRAC)
            geo["baseline_off"] = int(
                min(geo["nat_h_px"], geo["_ink_top"] + body)
            )
        geo.pop("_ink_top", None)
        geo.pop("_ink_h", None)


def estimate_geometry_for_image(img: Image.Image, ch: str,
                                x_height_px: float, em_px: int) -> dict | None:
    """Geometría heurística de un glifo del banco SIN datos de template.

    Clase tipográfica por identidad del char; baseline por fondo de tinta
    (no-descendentes) o top + x-height de referencia (descendentes). Los
    sidebearings quedan en 0 = desconocidos (el renderer usa su gap actual).
    """
    bbox = _alpha_bbox(img)
    if bbox is None:
        return None
    _x0, ink_top, _x1, ink_bottom = bbox
    w, h = img.size
    if any(c in DESCENDERS for c in ch):  # R10: pares descendentes también
        body = x_height_px if x_height_px > 0 else (ink_bottom - ink_top) * _DESC_BODY_FRAC
        baseline = min(h, ink_top + int(round(body)))
    else:
        baseline = ink_bottom
    return {
        "nat_h_px": int(h),
        "nat_w_px": int(w),
        "baseline_off": int(baseline),
        "em_px": int(max(1, em_px)),
        "lsb": 0,
        "rsb": 0,
        "metrics_source": "estimada",
    }


def estimate_bank_geometry(entries: list, *, force: bool = False) -> dict[str, dict]:
    """Estima geometría para los entries de un banco que no la tienen.

    Devuelve {image_path: geometry} SOLO para los que pudo medir; no muta los
    entries (eso lo hace apply_geometry_to_entries, mismo patrón dos-pasos que
    bank_io.backfill_missing_hashes). Con force=True re-estima también los que
    ya tenían métricas ESTIMADAS (nunca pisa las medidas de template).

    La x-height de referencia es la mediana de los altos de tinta de los chars
    de XHEIGHT_REF del banco; el em legacy se deriva con la convención del
    renderer (x-height ≈ 45% del renglón) para que la fracción nat_h/em quede
    en la misma escala que la medición de template.
    """
    if not _PIL_OK:
        return {}
    pending = [
        e for e in entries
        if e.metrics_source == "" or (force and e.metrics_source == "estimada")
    ]
    if not pending:
        return {}

    # Pasada 1: alto de tinta de los chars de x-height (TODOS los del banco,
    # no sólo los pendientes: un banco a medio migrar sigue dando referencia).
    xheights: list[int] = []
    for e in entries:
        if e.char not in XHEIGHT_REF:
            continue
        try:
            with Image.open(e.image_path) as img:
                bbox = _alpha_bbox(img)
            if bbox:
                xheights.append(bbox[3] - bbox[1])
        except Exception as exc:
            logger.debug("estimate_bank_geometry: no se pudo abrir %s: %s",
                         e.image_path, exc)
    x_ref = float(np.median(xheights)) if xheights else 0.0
    em = int(round(x_ref / _XHEIGHT_TO_EM)) if x_ref > 0 else 0

    # Pasada 2: geometría por glifo pendiente.
    out: dict[str, dict] = {}
    for e in pending:
        try:
            with Image.open(e.image_path) as img:
                geo = estimate_geometry_for_image(img.copy(), e.char, x_ref, em)
        except Exception as exc:
            logger.warning("estimate_bank_geometry: %s ilegible: %s",
                           e.image_path, exc)
            continue
        if geo is None:
            continue
        # Sin em de referencia (banco sin x-heights): em propio del glifo según
        # su clase, para que nat_h/em siga siendo una fracción razonable.
        if geo["em_px"] <= 1:
            frac = 0.85 if e.char not in XHEIGHT_REF else _XHEIGHT_TO_EM
            geo["em_px"] = max(1, int(round(geo["nat_h_px"] / frac)))
        out[e.image_path] = geo
    return out


def apply_geometry(entry, geo: dict) -> None:
    """Setea en el entry los campos de geometría conocidos (ignora claves
    internas con guion bajo y claves que GlyphEntry no tenga)."""
    for k, v in geo.items():
        if hasattr(entry, k) and not k.startswith("_"):
            setattr(entry, k, v)


def apply_geometry_to_entries(entries: list, updates: dict[str, dict]) -> int:
    """Aplica {image_path: geometry} a los entries IN PLACE. Devuelve nº aplicado.

    Mismo contrato que bank_io.backfill_missing_hashes: muta y deja el save al
    caller (banco o migrador), que es quien tiene el lock/contexto correcto.
    """
    applied = 0
    for e in entries:
        geo = updates.get(e.image_path)
        if not geo:
            continue
        apply_geometry(e, geo)
        applied += 1
    return applied

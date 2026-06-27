"""Extractor de glifos desde la plantilla por grilla (Fase plantilla).

Dado una foto de la plantilla rellena (`template_sheet`), recupera un glifo por
casilla SIN segmentar: la casilla↔letra es fija. Pasos:

  1. Rectificar: detectar los 4 marcadores de esquina y aplicar una transformación
     de perspectiva al tamaño canónico (TemplateLayout). Así cada casilla cae en
     coordenadas conocidas, aunque la foto venga torcida o en ángulo.
  2. Por cada casilla, recortar el área de escritura (sin borde ni rótulo),
     binarizar la tinta, quitar restos del borde/rótulo (componentes que tocan el
     marco) y autocrop.
  3. Convertir a glifo RGBA en el formato del banco (`to_rgba_smooth`) y evaluar
     calidad. Devuelve (letra, imagen, calidad) por casilla con tinta suficiente.

No depende de la alineación posicional del extractor de renglón: por eso no hay
recortes a la mitad ni etiquetas corridas.
"""
from __future__ import annotations

import logging

from core.inkcore.glyph_metrics import (
    finalize_sheet_geometry,
    measure_ink_bbox,
    template_geometry,
)

# Fiduciales + rectificación/rotación (template_fiducials, acota este módulo).
# Se importan para uso interno y se re-exportan (tests y tools/diag_template_pdf
# importan _detect_fiducials/detect_template_rotation/_detect_rotation_by_cnn).
from core.inkcore.template_fiducials import (  # noqa: F401
    _detect_fiducials,
    _detect_rotation_by_cnn,
    _rectify,
    _rotation_cnn_score,
    _title_band_signal,
    detect_template_rotation,
)

# Operaciones de imagen de bajo nivel (deskew, bbox de grilla, binarización de
# celda, estimación de columnas/filas…). Viven en template_imageops para acotar
# este módulo; se importan para uso interno y se re-exportan (varios tests y
# tools/diag_template_pdf importan estos privados desde acá).
from core.inkcore.template_imageops import (  # noqa: F401
    _autocorr_period,
    _autocrop_mask,
    _cell_ink_mask,
    _clean_cell,
    _clean_cell_grid,
    _deskew,
    _estimate_grid_dims,
    _estimate_skew,
    _grid_content_bbox,
    _rotate_cw,
    _sizable_components,
    _strip_edge_lines,
    _strip_title_band,
)
from core.inkcore.template_save import (  # noqa: F401
    _append_reject_log,
    _quality_override_from_template,
    save_template_glyphs_to_bank,
)
from core.inkcore.template_sheet import TEMPLATE_PRESETS, TemplateLayout

logger = logging.getLogger(__name__)

# Gate anti-corrupción (E2): acuerdo medio mínimo del CNN (P de la letra
# esperada sobre las casillas a-z) para CONFIAR en el mapeo letra↔casilla de
# una página y dejar que sus glifos entren al banco. Calibrado contra el lote
# real de 29 fotos: páginas bien mapeadas dan 0.358-0.450; páginas con el
# layout equivocado (un número etiquetado como letra, acentos cruzados) dan
# 0.038-0.054 — separación de ~6.6×, así que 0.12 discrimina sin falsos
# positivos. Por debajo: página suspect, no se guarda (ver assess_page_agreement).
TEMPLATE_PAGE_MIN_CNN_AGREEMENT = 0.12

try:
    import cv2
    import numpy as np
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

try:
    from PIL import Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def score_layout_cheap(
    gray: np.ndarray, layout: TemplateLayout, *,
    deskewed: np.ndarray | None = None, bbox: tuple | None = None,
) -> dict:
    """Puntúa BARATO qué tan bien la grilla de `layout` calza con la foto.

    Sin CNN, sin to_rgba_smooth, sin assess_quality: sólo binariza y cuenta por
    casilla rotulada. Pensado para elegir el preset correcto entre muchos
    candidatos × 4 rotaciones sin reventar el i5 (<300ms/página/preset). La
    extracción completa (cara) corre sólo sobre el ganador.

    Idea: el preset CORRECTO alinea cada casilla con una celda real de la grilla
    impresa → las casillas con tinta tienen UNA letra (pocas piezas, tinta en un
    rango sano). Un preset con muy pocas columnas mete varias letras por celda
    (tinta alta, >7 piezas); con demasiadas, parte letras (tinta ínfima). Ambos
    desvíos bajan el score.

    `deskewed`/`bbox` se pueden inyectar (el deskew Hough y el bbox son lo caro)
    para reusarlos entre todos los presets de una misma rotación: el orquestador
    los computa UNA vez por rotación. Si no se pasan, se calculan acá.

    Devuelve {"score", "n_inked", "n_healthy", "n_crowded"} — el score en [−0.5,1]
    es (sanas − 0.5·sobrepobladas) / casillas_con_tinta, o 0 si no hay tinta.
    """
    g = deskewed if deskewed is not None else _deskew(gray, _estimate_skew(gray))
    bb = bbox if bbox is not None else _grid_content_bbox(g)
    if bb is None:
        return {"score": 0.0, "n_inked": 0, "n_healthy": 0, "n_crowded": 0}
    gx0, gy0, gx1, gy1 = bb
    xs = np.linspace(gx0, gx1, layout.cols + 1)
    ys = np.linspace(gy0, gy1, layout.rows + 1)
    n_inked = n_healthy = n_crowded = 0
    for i in range(min(layout.n_cells, len(layout.charset) * layout.repeats)):
        if layout.cell_letter(i) is None:
            continue
        r, c = divmod(i, layout.cols)
        x0, x1 = xs[c], xs[c + 1]
        y0, y1 = ys[r], ys[r + 1]
        cw, chh = x1 - x0, y1 - y0
        # Inset 13% para excluir los separadores de la grilla (como _extract_grid).
        ix0, ix1 = int(x0 + 0.13 * cw), int(x1 - 0.13 * cw)
        iy0, iy1 = int(y0 + 0.13 * chh), int(y1 - 0.13 * chh)
        cell = g[iy0:iy1, ix0:ix1]
        if cell.size == 0:
            continue
        thr = cv2.adaptiveThreshold(
            cv2.GaussianBlur(cell, (3, 3), 0), 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12,
        )
        ink_frac = float((thr > 0).mean())
        if ink_frac < 0.002:            # casilla vacía: no cuenta ni a favor ni en contra
            continue
        n_inked += 1
        if ink_frac > 0.25:             # demasiada tinta: celda abarca varias letras
            n_crowded += 1
            continue
        ncomp = _sizable_components(thr)
        if ncomp > 7:                   # muchas piezas: multi-letra / texto
            n_crowded += 1
        else:
            n_healthy += 1
    if n_inked == 0:
        return {"score": 0.0, "n_inked": 0, "n_healthy": 0, "n_crowded": 0}
    score = (n_healthy - 0.5 * n_crowded) / n_inked
    return {"score": score, "n_inked": n_inked,
            "n_healthy": n_healthy, "n_crowded": n_crowded}


def _extract_grid(gray, lay, clf, char_to_label):
    """Extracción para plantillas SIN fiduciales: detecta la grilla en la foto.

    En vez de asumir la geometría canónica (que sólo vale si rectificamos por los
    4 marcadores), deskewa la foto, halla el bbox del contenido y divide en
    lay.cols × lay.rows celdas uniformes, limpiando líneas de grilla por celda.
    Esto evita lo que rompía la ruta vieja (un simple resize desalineaba las
    casillas → recortes sobre líneas y letras partidas). Mismo formato de salida
    que extract_from_template: lista de (letra, glifo_RGBA, score).
    """
    from core.inkcore.glyph_ingest import assess_quality, to_rgba_smooth

    ang = _estimate_skew(gray)
    gray = _deskew(gray, ang)
    # Extrae la grilla TAL CUAL en la orientación recibida (sin auto-rotar por
    # aspecto: eso arreglaba el alto/ancho pero no el arriba/abajo, y dejaba
    # páginas apaisadas dadas vuelta → letras en la casilla equivocada). La
    # orientación correcta la elige extract_from_template_auto probando las 4
    # rotaciones y quedándose con la de mayor acuerdo CNN (señal limpia sobre la
    # extracción de grilla, no sobre la canónica rota).
    bb = _grid_content_bbox(gray)
    if bb is None:
        logger.warning("_extract_grid: sin contenido detectable")
        return []
    gx0, gy0, gx1, gy1 = bb
    n_cols, n_rows = lay.cols, lay.rows
    xs = np.linspace(gx0, gx1, n_cols + 1)
    ys = np.linspace(gy0, gy1, n_rows + 1)
    logger.info("_extract_grid: skew=%.2f° grilla %dx%d bbox=%s", ang, n_cols, n_rows, bb)

    def _crop(r, c, inset):
        x0, x1 = xs[c], xs[c + 1]
        y0, y1 = ys[r], ys[r + 1]
        cw, chh = x1 - x0, y1 - y0
        ix0, ix1 = int(x0 + inset * cw), int(x1 - inset * cw)
        iy0, iy1 = int(y0 + inset * chh), int(y1 - inset * chh)
        return gray[iy0:iy1, ix0:ix1]

    results: list[tuple[str, Image.Image, float]] = []
    for r in range(n_rows):
        for c in range(n_cols):
            i = r * n_cols + c
            ch = lay.cell_letter(i)
            if ch is None:
                continue
            # Inset adaptativo: arranca con 13% (excluye los separadores de la
            # grilla). Si la letra quedó RECORTADA por estar descentrada (p. ej. la
            # 'o' alta cuyo arco superior cae fuera del crop), un inset chico (4%)
            # captura MÁS tinta. Se adopta el inset chico sólo cuando (a) suma
            # ≥15% de tinta y (b) NO agrega componentes: la letra recuperada se
            # conecta a la existente (mismo nº de piezas), mientras que un
            # separador de grilla entraría como pieza NUEVA → se rechaza. Así sólo
            # se beneficia a las casillas recortadas, sin reintroducir grilla en
            # las centradas.
            inset_used = 0.13
            keep = _cell_ink_mask(_crop(r, c, 0.13))
            if keep is None:
                continue
            keep_big = _cell_ink_mask(_crop(r, c, 0.04))
            if (keep_big is not None
                    and (keep_big > 0).sum() >= 1.15 * (keep > 0).sum()
                    and _sizable_components(keep_big) <= _sizable_components(keep)):
                keep = keep_big
                inset_used = 0.04
            mask = _autocrop_mask(keep)
            if mask is None:
                continue
            # Descartar casillas-texto: si la foto captó el título/instrucciones
            # de la plantilla arriba de la grilla, el bbox de contenido lo incluye
            # y la fila 1 cae sobre ese texto. Una línea de título da MUCHAS piezas
            # conexas; una letra real, pocas (≤5). Umbral 8 separa limpio (validado:
            # ninguna letra manuscrita del banco supera 8).
            ncomp = _sizable_components(mask)
            if ncomp >= 8:
                logger.info(
                    "_extract_grid: casilla '%s' descartada (texto/título, %d componentes)",
                    ch, ncomp,
                )
                continue
            glyph = to_rgba_smooth(mask)
            # R1: geometría con la celda detectada como referencia. El "em"
            # descuenta la franja del rótulo en su proporción canónica (la
            # grilla detectada incluye el rótulo impreso dentro de la celda).
            cw_full = float(xs[c + 1] - xs[c])
            ch_full = float(ys[r + 1] - ys[r])
            em = round(ch_full * (1.0 - lay.label_strip / lay.cell_h))
            bb = measure_ink_bbox(keep)
            ins_x = inset_used * cw_full
            glyph.info["geometry"] = template_geometry(
                mask, ch, em_px=em,
                lsb=round(ins_x + bb[0]) if bb else 0,
                rsb=round(cw_full - (ins_x + bb[2])) if bb else 0,
            )
            try:
                q = assess_quality(glyph)
                score = float(q.get("quality_score", q.get("score", 0.5)))
            except Exception:
                score = 0.5
            if clf is not None and char_to_label is not None and char_to_label(ch) is not None:
                try:
                    cnn = clf.score(mask, ch)
                    if cnn is not None and cnn < 0.12:
                        score = min(score, 0.45)
                except Exception:
                    pass
            results.append((ch, glyph, score))
    finalize_sheet_geometry(results)  # R1: baselines de descendentes por hoja
    logger.info("_extract_grid: %d casillas con tinta", len(results))
    return results


def extract_from_template(
    image_path: str, layout: TemplateLayout | None = None, *, pre_rotate: int = 0,
) -> list[tuple[str, Image.Image, float]]:
    """Extrae un glifo por casilla rellena. Lista de (letra, glifo_RGBA, calidad).

    Sólo devuelve casillas con tinta suficiente (las vacías se omiten). No hay
    segmentación: cada casilla se mapea a su letra por posición fija en la grilla.

    `pre_rotate` (0/90/180/270, horario) rota la imagen ANTES de rectificar: lo
    usa el flujo de PDF multipágina para enderezar hojas que el escáner giró 90°
    (ver `extract_from_template_auto`). Default 0 = sin cambios (los tests
    existentes lo invocan sin este argumento).
    """
    if not (_CV2_OK and _PIL_OK):
        logger.warning("extract_from_template: faltan cv2/PIL")
        return []
    from pathlib import Path

    from core.inkcore.glyph_ingest import assess_quality, to_rgba_smooth
    if not Path(image_path).exists():
        logger.warning("extract_from_template: no existe %s", image_path)
        return []
    bgr = cv2.imread(image_path)
    if bgr is None:
        logger.warning("extract_from_template: cv2 no pudo leer %s", image_path)
        return []
    lay = layout or TemplateLayout()
    if pre_rotate % 360:
        bgr = _rotate_cw(bgr, pre_rotate)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Clasificador opcional: la casilla↔letra ya es correcta por construcción,
    # pero el CNN marca como dudosa la casilla donde se escribió OTRA letra (error
    # humano) o quedó ilegible → su score baja y la UI la resalta para revisar.
    clf = None
    char_to_label = None
    try:
        import config as _cfg
        if getattr(_cfg, "USE_CNN_ALIGN", False):
            from core.inkcore.ai.char_cnn import EMNISTCharClassifier, char_to_label
            _c = EMNISTCharClassifier()
            if _c.available:
                clf = _c
    except Exception as _exc:
        logger.info("extract_from_template: CNN no disponible (%s)", _exc)

    # Bifurcación CON / SIN fiduciales. Con marcadores: rectificación por
    # perspectiva exacta y geometría canónica (writing_rect). Sin marcadores
    # (grilla pelada, foto de celular): la canónica fallaba porque _rectify caía
    # a un resize que NO alinea las casillas → recortes sobre líneas y letras
    # partidas. En ese caso detectamos la grilla real en la foto (_extract_grid).
    if _detect_fiducials(gray, lay) is None:
        return _extract_grid(gray, lay, clf, char_to_label)
    canon = _rectify(gray, lay)

    results: list[tuple[str, Image.Image, float]] = []
    n_labeled = min(lay.n_cells, len(lay.letters) * lay.repeats)
    for i in range(n_labeled):
        ch = lay.cell_letter(i)
        if ch is None:
            continue
        wx, wy, ww, wh = lay.writing_rect(i)
        cell = canon[wy:wy + wh, wx:wx + ww]
        geom: dict = {}
        mask = _clean_cell(cell, geom_out=geom)
        if mask is None:
            continue
        glyph = to_rgba_smooth(mask)
        # R1: geometría con el área de escritura de la casilla como referencia
        # (su alto = "em" de la hoja). Viaja en Image.info para no cambiar la
        # API (char, glifo, score); save_template_glyphs_to_bank la persiste.
        bb = geom.get("ink_bbox")
        glyph.info["geometry"] = template_geometry(
            mask, ch, em_px=wh,
            lsb=bb[0] if bb else 0,
            rsb=(ww - bb[2]) if bb else 0,
        )
        try:
            q = assess_quality(glyph)
            score = float(q.get("quality_score", q.get("score", 0.5)))
        except Exception:
            score = 0.5
        # Validación por CNN: si no reconoce la casilla como su letra (ni de
        # lejos), marcarla dudosa bajando el score (solo a-z; la ñ no aplica).
        if clf is not None and char_to_label is not None and char_to_label(ch) is not None:
            try:
                cnn = clf.score(mask, ch)
                if cnn is not None and cnn < 0.12:
                    score = min(score, 0.45)
            except Exception as _exc:
                logger.debug("validación CNN omitida para '%s': %s", ch, _exc)
        results.append((ch, glyph, score))
    # R1: el baseline de las descendentes se reconstruye con la x-height
    # mediana de ESTA hoja (sólo se conoce con la extracción completa).
    finalize_sheet_geometry(results)
    logger.info("extract_from_template: %d/%d casillas con tinta (repeats=%d)",
                len(results), n_labeled, lay.repeats)
    return results


def _has_fiducials(image_path: str, lay: TemplateLayout) -> bool:
    """True si alguna de las 4 rotaciones detecta los 4 marcadores de esquina."""
    if not (_CV2_OK and _PIL_OK):
        return False
    bgr = cv2.imread(image_path)
    if bgr is None:
        return False
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return any(_detect_fiducials(_rotate_cw(gray, angle), lay) is not None
               for angle in (0, 90, 180, 270))


def _page_cnn_scores(results, clf, char_to_label) -> list[float]:
    """P(letra esperada) del CNN por cada casilla a-z extraída de la página.

    Solo a-z (la ñ, dígitos y signos no los cubre el CNN EMNIST). Devuelve la
    lista cruda — el promedio (orientación) y el conteo (gate anti-corrupción)
    la consumen distinto: una página de dígitos con su preset correcto da lista
    VACÍA (no hay a-z), que NO es lo mismo que acuerdo bajo.
    """
    scores: list[float] = []
    for ch, glyph, _s in results:
        if char_to_label(ch) is None:
            continue
        try:
            a = np.asarray(glyph.convert("RGBA"))[:, :, 3]
            mask = (a > 30).astype(np.uint8) * 255
            v = clf.score(mask, ch)
        except Exception:
            v = None
        if v is not None:
            scores.append(float(v))
    return scores


def _grid_cnn_agreement(results, clf, char_to_label) -> float:
    """Acuerdo medio del CNN entre cada casilla a-z y su letra esperada.

    Es la señal para elegir orientación sin fiduciales: la rotación correcta hace
    que cada letra caiga en su casilla → P(letra esperada) alto (~0.4-0.6); una
    rotación equivocada deja letras cruzadas → ~0.02. Diferencia de 10-15×, así
    que discrimina con claridad. Solo cuenta a-z (la ñ no la cubre el CNN).
    """
    scores = _page_cnn_scores(results, clf, char_to_label)
    return sum(scores) / len(scores) if scores else 0.0


def assess_page_agreement(
    results, clf, char_to_label, *, min_agreement: float = TEMPLATE_PAGE_MIN_CNN_AGREEMENT,
) -> tuple[float | None, bool, str]:
    """Gate anti-corrupción: decide si una página es sospechosa de mapeo cruzado.

    Devuelve (page_agreement, suspect, reason). El acuerdo del CNN discrimina
    limpio entre una página bien mapeada (letras en su casilla → P alto) y una
    con el layout equivocado (un '5' manuscrito etiquetado 'g' → P ínfima):
    medido en el lote real, estándar ~0.4-0.6 vs cruzada ~0.02, 10-15× de
    separación. Por debajo de `min_agreement` la página NO debe guardarse: mejor
    fallar ruidosamente que envenenar el banco con etiquetas equivocadas.

    Casos límite, por seguridad:
      - Sin CNN disponible → (None, False, "sin validación CNN"): no se bloquea
        al usuario, pero el reporte avisa que vuela a ciegas.
      - Sin casillas a-z que puntuar (p. ej. una página de dígitos con su preset
        correcto) → (None, False, "sin casillas a-z para validar"): el CNN no
        aplica; la confianza la da la señal estructural del preset (Fase E3),
        no este gate. Esto evita marcar suspect una página legítima de dígitos.
    """
    if clf is None:
        return None, False, "sin validación CNN"
    scores = _page_cnn_scores(results, clf, char_to_label)
    if not scores:
        return None, False, "sin casillas a-z para validar"
    agreement = sum(scores) / len(scores)
    if agreement < min_agreement:
        return agreement, True, (
            f"mapeo letra↔casilla no confiable (acuerdo CNN {agreement:.2f} "
            f"< {min_agreement:.2f})"
        )
    return agreement, False, ""


def _load_template_cnn():
    """(clf, char_to_label) si el CNN EMNIST está disponible, si no (None, None).

    El CNN es señal opcional (orientación + gate anti-corrupción), nunca un
    requisito duro: sin torch/modelo se degrada con aviso, no se rompe.
    """
    try:
        from core.inkcore.ai.char_cnn import EMNISTCharClassifier, char_to_label
        clf = EMNISTCharClassifier()
        if clf.available:
            return clf, char_to_label
    except Exception as exc:
        logger.info("_load_template_cnn: CNN no disponible (%s)", exc)
    return None, None


def extract_from_template_auto_meta(
    image_path: str, layout: TemplateLayout | None = None, *, clf=None, char_to_label=None,
) -> dict:
    """Extrae una página con autorrotación Y el veredicto del gate anti-corrupción.

    Devuelve un dict rico:
        {"results": [(char, glyph, score), ...],   # casillas con tinta
         "rotation": int,                          # rotación horaria aplicada
         "page_agreement": float | None,           # acuerdo CNN medio (a-z)
         "suspect": bool,                          # True = NO guardar (mapeo dudoso)
         "reason": str}                            # por qué es suspect / aviso

    CON fiduciales: orienta por marcadores+título (`detect_template_rotation`).
    SIN fiduciales: prueba las 4 rotaciones con extracción de grilla y se queda
    con la de mayor acuerdo CNN casilla↔letra (la canónica está rota sin
    marcadores, por eso no se usa). En ambos caminos, al final, el gate evalúa el
    acuerdo de la página: una página con el layout equivocado (números/acentos
    extraídos como minúsculas) cae muy por debajo del umbral → suspect=True y la
    UI no la guarda. `clf`/`char_to_label` se pueden inyectar para no recargar el
    modelo por página (lo hace el orquestador de PDF).
    """
    lay = layout or TemplateLayout()
    if clf is None and char_to_label is None:
        clf, char_to_label = _load_template_cnn()

    if _has_fiducials(image_path, lay):
        angle = detect_template_rotation(image_path, lay)
        results = extract_from_template(image_path, lay, pre_rotate=angle)
        rot = angle
    elif clf is None:
        results = extract_from_template(image_path, lay, pre_rotate=0)
        rot = 0
    else:
        best_res, best_score, best_rot = [], -1.0, 0
        for r in (0, 90, 180, 270):
            res = extract_from_template(image_path, lay, pre_rotate=r)
            sc = _grid_cnn_agreement(res, clf, char_to_label)
            if sc > best_score:
                best_score, best_res, best_rot = sc, res, r
        results, rot = best_res, best_rot
        logger.info(
            "extract_from_template_auto: sin fiduciales — rot %d° (acuerdo CNN=%.3f)",
            best_rot, best_score,
        )

    agreement, suspect, reason = assess_page_agreement(results, clf, char_to_label)
    if suspect:
        logger.warning(
            "gate anti-corrupción: página DUDOSA (%s) — %d casillas NO se guardarán",
            reason, len(results),
        )
    return {"results": results, "rotation": rot, "page_agreement": agreement,
            "suspect": suspect, "reason": reason}


def extract_from_template_auto(
    image_path: str, layout: TemplateLayout | None = None,
) -> list[tuple[str, Image.Image, float]]:
    """Wrapper compat: como `extract_from_template_auto_meta` pero devuelve solo
    la lista (char, glifo, score). Conserva la firma histórica que usan los tests
    y cualquier llamador que no necesite el veredicto del gate. El flujo de la UI
    consume la versión `_meta` (o `extract_pdf_pages`) para respetar `suspect`.
    """
    return extract_from_template_auto_meta(image_path, layout)["results"]


# Score estructural mínimo (E3) para CONFIAR en que un preset identificó el
# layout de una página sin fiduciales. Por debajo: "layout no identificado" →
# suspect, no se guarda. Calibrado con el harness contra el lote real.
TEMPLATE_LAYOUT_MIN_SCORE = 0.45

# Pico de autocorrelación mínimo para CONFIAR en la estimación de columnas de
# una hoja non-az (acentos/dígitos). Medido en el lote: las hojas reales dan
# 0.5-0.7; por debajo la periodicidad es ruidosa (hoja a medio llenar) y se cae
# al fallback suspect + reasignación manual.
TEMPLATE_LAYOUT_MIN_AUTOCORR = 0.45


def _unique_geometries(presets: dict) -> dict:
    """(cols, rows) → [nombres de presets con esa geometría].

    El scoring barato sólo ve la estructura, así que presets con igual geometría
    dan idéntico score: se agrupan para puntuar UNA vez por geometría y desempatar
    luego por CNN (las hojas de minúsculas parciales caen todas en 6×16).
    """
    geoms: dict[tuple[int, int], list[str]] = {}
    for name, lay in presets.items():
        geoms.setdefault((lay.cols, lay.rows), []).append(name)
    return geoms


def _downscale(gray: np.ndarray, target_w: int = 800) -> np.ndarray:
    """Reduce a `target_w` de ancho (para scoring estructural barato de rotación)."""
    h, w = gray.shape[:2]
    if w <= target_w:
        return gray
    s = target_w / w
    return cv2.resize(gray, (target_w, max(1, int(h * s))), interpolation=cv2.INTER_AREA)


# Ancho al que se reduce la foto para el ANÁLISIS (rotación + geometría) por
# agreement CNN. El CNN preprocesa a 28×28, así que ~1240px (resolución
# canónica) no le quita señal y acelera ~4× vs los 2481-3508px de la foto. La
# extracción FINAL del ganador corre a resolución completa (calidad de glifos).
_ANALYSIS_WIDTH = 1240


def _rotation_candidates(gray: np.ndarray) -> tuple[int, ...]:
    """Rotaciones plausibles según el aspecto: la hoja canónica es retrato.

    Una foto cargada en retrato (alto>ancho) está derecha o invertida → {0,180};
    una apaisada la giró el escáner 90° → {90,270}. Reduce el barrido de
    agreement de 4 a 2 candidatos (el agreement decide cuál de los 2, ya que la
    estructura no distingue una hoja de su versión 180°).
    """
    h, w = gray.shape[:2]
    return (0, 180) if h >= w else (90, 270)


def _layout_agreement_fast(deskewed, bbox, lay, clf, char_to_label) -> tuple[float, int]:
    """Acuerdo CNN (a-z) de un preset reusando deskew+bbox YA computados.

    No vuelve a deskewar ni a hallar el bbox (lo caro): el orquestador los pasa
    una vez por rotación y esta función sólo proyecta la grilla del preset y
    puntúa las casillas a-z con tinta. Devuelve (agreement, n_casillas_az). Sin
    to_rgba_smooth ni assess_quality — barato, sólo la máscara para el CNN.
    """
    if bbox is None or clf is None:
        return 0.0, 0
    gx0, gy0, gx1, gy1 = bbox
    xs = np.linspace(gx0, gx1, lay.cols + 1)
    ys = np.linspace(gy0, gy1, lay.rows + 1)
    scores: list[float] = []
    n_az = 0
    for i in range(min(lay.n_cells, len(lay.charset) * lay.repeats)):
        ch = lay.cell_letter(i)
        if ch is None or char_to_label(ch) is None:
            continue
        r, c = divmod(i, lay.cols)
        x0, x1 = xs[c], xs[c + 1]
        y0, y1 = ys[r], ys[r + 1]
        cw, chh = x1 - x0, y1 - y0
        ix0, ix1 = int(x0 + 0.13 * cw), int(x1 - 0.13 * cw)
        iy0, iy1 = int(y0 + 0.13 * chh), int(y1 - 0.13 * chh)
        mask = _clean_cell_grid(deskewed[iy0:iy1, ix0:ix1])
        if mask is None:
            continue
        n_az += 1
        v = clf.score(mask, ch)
        if v is not None:
            scores.append(float(v))
    return (sum(scores) / len(scores) if scores else 0.0), n_az


def _extract_page_multilayout(image_path, presets, hint_name, clf, char_to_label,
                              layout_hint=None):
    """Elige el preset por página (barrido rotación×geometría por agreement CNN).

    El scoring ESTRUCTURAL no identifica la geometría de forma fiable (premia
    grillas finas) ni la orientación 0°/180° (la grilla se ve igual invertida).
    La señal confiable es el AGREEMENT CNN: la combinación (rotación, geometría)
    correcta pone cada letra en su casilla → acuerdo alto; distingue además
    minúsculas×1 de ×3 (con ×3 la casilla 1 se rotula 'a' pero contiene 'b').

    Pasos (todo el análisis a resolución reducida; la extracción final del
    ganador a resolución completa):
      1. Candidatos de rotación por aspecto (retrato→{0,180}, apaisada→{90,270}).
      2. Barrido (rotación × geometría a-z única) por agreement, reusando
         deskew+bbox por rotación. Mejor (rot, geom).
      3. Si la geometría ganadora es 6×16 (varias hojas la comparten), desempatar
         el charset por agreement en la rotación ganadora.
      4. Si el mejor agreement supera el umbral del gate → página de LETRAS:
         extracción completa + gate.
      5. Si no → no es página de letras (acentos/dígitos, que el CNN no puntúa):
         NO se extrae completo (sería caro e inútil; igual quedaría suspect). Se
         devuelve suspect con el preset tentativo por estructura para que el
         usuario reasigne a mano (E5) y recién ahí se extraiga.

    Devuelve el dict rico de la página. Ver `extract_pdf_pages`.
    """
    bgr = cv2.imread(image_path)
    if bgr is None:
        return {"results": [], "preset": None, "rotation": -1, "layout_score": 0.0,
                "page_agreement": None, "suspect": True, "reason": "no se pudo leer la imagen"}
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    small_base = _downscale(gray, _ANALYSIS_WIDTH)

    # Identificación en dos pasos para acotar el cómputo (deskew+bbox es lo caro):
    #   (1) ROTACIÓN: se prueba el preset de referencia (minúsculas×1, 27 casillas
    #       a-z, el más informativo) en las 2 rotaciones candidatas. El contenido
    #       manuscrito está en la orientación correcta aunque la página no sea de
    #       minúsculas, así que su agreement marca la rotación.
    #   (2) GEOMETRÍA/CHARSET: en la rotación ganadora se prueba el resto de
    #       presets a-z (los de 6×16 —aeiosnr/ltcdmp/resto— sólo difieren en el
    #       charset y sólo el correcto da agreement alto).
    az_names = [n for n, lay in presets.items()
                if any(char_to_label(c) for c in lay.charset)]
    ref_name = "minusculas_x1" if "minusculas_x1" in presets else (az_names[0] if az_names else None)

    cache: dict[int, tuple] = {}
    win_rot, ref_agr = _rotation_candidates(small_base)[0], -1.0
    if ref_name is not None:
        for rot in _rotation_candidates(small_base):
            g = _rotate_cw(small_base, rot)
            dk = _deskew(g, _estimate_skew(g))
            bb = _grid_content_bbox(dk)
            cache[rot] = (dk, bb)
            agr, n_az = _layout_agreement_fast(dk, bb, presets[ref_name], clf, char_to_label)
            if n_az >= 5 and agr > ref_agr:
                ref_agr, win_rot = agr, rot

    dk, bb = cache.get(win_rot, (None, None))
    if dk is None:
        g = _rotate_cw(small_base, win_rot)
        dk = _deskew(g, _estimate_skew(g))
        bb = _grid_content_bbox(dk)
        cache[win_rot] = (dk, bb)
    best = (ref_agr, ref_name) if ref_name is not None else (-1.0, None)
    for name in az_names:
        if name == ref_name:
            continue
        agr, n_az = _layout_agreement_fast(dk, bb, presets[name], clf, char_to_label)
        if n_az < 5:
            continue
        if agr > best[0]:
            best = (agr, name)

    if best[1] is not None and best[0] >= TEMPLATE_PAGE_MIN_CNN_AGREEMENT:
        win_agr, win_name = best
        results = extract_from_template(image_path, presets[win_name], pre_rotate=win_rot)
        agr2, suspect, reason = assess_page_agreement(results, clf, char_to_label)
        agreement = agr2 if agr2 is not None else win_agr
        if suspect:
            logger.warning("multilayout %s: DUDOSA (%s)", win_name, reason)
        else:
            logger.info("multilayout: preset=%s rot=%d° agreement=%.3f n=%d",
                        win_name, win_rot, agreement, len(results))
        return {"results": results, "preset": win_name, "rotation": win_rot,
                "layout_score": round(win_agr, 3), "page_agreement": agreement,
                "suspect": suspect, "reason": reason}

    # No es página de letras: puede ser acentos (6 columnas) o dígitos (9). El
    # CNN no valida esos caracteres, pero la GEOMETRÍA sí los distingue: se estima
    # el nº de columnas por autocorrelación de la tinta (no depende de ver las
    # líneas) y se elige el preset non-az cuyas columnas coincidan.
    win_rot = _rotation_candidates(small_base)[0]
    g = _rotate_cw(small_base, win_rot)
    dk, bb = cache.get(win_rot, (None, None))
    if dk is None:
        dk = _deskew(g, _estimate_skew(g))
        bb = _grid_content_bbox(dk)
    non_az = {n: lay for n, lay in presets.items()
              if not any(char_to_label(c) for c in lay.charset)}

    # Si el usuario pasó un layout_hint que es ÉL MISMO non-az (p. ej. una hoja
    # de dígitos+puntuación generada desde la UI), ese hint es mejor señal que la
    # autocorrelación de columnas: la geometría no distingue charsets non-az del
    # mismo nº de columnas (numeros+signos vs digitos_signos comparten ~10 cols),
    # y el CNN no puede validar estos caracteres. El usuario sabe qué plantilla
    # imprimió → se respeta su hint y se extrae con él. Gate: solo cuando el hint
    # es non-az; las páginas de letras ya retornaron arriba por agreement CNN.
    if layout_hint is not None and not any(
            char_to_label(c) for c in layout_hint.charset):
        results = extract_from_template(image_path, layout_hint, pre_rotate=win_rot)
        if results:
            logger.info("multilayout: non-az por layout_hint del usuario "
                        "(charset=%r) rot=%d n=%d",
                        layout_hint.charset, win_rot, len(results))
            return {"results": results, "preset": "layout_hint", "rotation": win_rot,
                    "layout_score": 0.0, "page_agreement": None, "suspect": False,
                    "reason": ("extraída con el layout que generaste (dígitos/"
                               "signos): el CNN no valida estos caracteres, "
                               "revisá los glifos antes de guardar")}

    dims = _estimate_grid_dims(dk, bb)
    if dims is not None and non_az:
        cols, rows, conf = dims
        # Match por nº de columnas (la señal robusta) Y filas (con tolerancia
        # amplia: las filas son menos precisas con casillas vacías). Exigir AMBAS
        # evita que una página densa de letras (p. ej. un combo mixto 10×20, que
        # el agreement no pudo identificar) se confunda con digitos_signos (9×16)
        # sólo por compartir ~9-10 columnas y se GUARDE mal (suspect=False
        # envenenaría el banco). Sin el match de filas, 10 cols ≈ 9 cols bastaba.
        # Acentos=6×12, dígitos=9×16: ambas dimensiones bien separadas.
        matches = [(n, lay) for n, lay in non_az.items()
                   if abs(lay.cols - cols) <= 1 and abs(lay.rows - rows) <= 3]
        if len(matches) == 1 and conf >= TEMPLATE_LAYOUT_MIN_AUTOCORR:
            win_name = matches[0][0]
            results = extract_from_template(image_path, presets[win_name], pre_rotate=win_rot)
            if results:
                logger.info("multilayout: non-az auto-identificada preset=%s "
                            "(cols=%d, autocorr=%.2f) n=%d",
                            win_name, cols, conf, len(results))
                return {"results": results, "preset": win_name, "rotation": win_rot,
                        "layout_score": round(conf, 3), "page_agreement": None,
                        "suspect": False,
                        "reason": ("identificada por geometría (acentos/dígitos): "
                                   "el CNN no valida estos caracteres, revisá los "
                                   "glifos antes de guardar")}

    # Fallback (autocorrelación ambigua o sin match único): preset tentativo por
    # estructura y suspect, para que el usuario reasigne a mano (E5).
    best_struct = None
    for name, lay in non_az.items():
        sc = score_layout_cheap(g, lay, deskewed=dk, bbox=bb)
        if best_struct is None or sc["score"] > best_struct[0]:
            best_struct = (sc["score"], name)
    win_name = best_struct[1] if best_struct else max(presets, key=lambda n: presets[n].n_cells)
    struct_score = best_struct[0] if best_struct else 0.0
    reason = ("no parece página de letras (posibles acentos/dígitos, que el CNN "
              "no valida) — elegí el preset a mano para extraer y guardar")
    logger.warning("multilayout: página no-letras → tentativo=%s (suspect, sin extraer)",
                   win_name)
    return {"results": [], "preset": win_name, "rotation": win_rot,
            "layout_score": round(struct_score, 3), "page_agreement": None,
            "suspect": True, "reason": reason}


def extract_pdf_pages(
    image_paths: list[str], *, layout_hint: TemplateLayout | None = None,
    presets: dict | None = None, clf=None, char_to_label=None,
) -> list[dict]:
    """Orquestador multi-layout (E3): elige el preset correcto POR PÁGINA.

    Un PDF puede mezclar hojas de layouts distintos (minúsculas, acentos,
    dígitos…). Aplicar UN solo layout a todas envenena el banco (un número
    etiquetado como letra). Acá cada página se puntúa contra los presets
    conocidos con scoring estructural BARATO (4 rotaciones × geometrías únicas),
    se extrae completa sólo con el preset ganador y se valida con el gate
    anti-corrupción. El snapshot del usuario (`layout_hint`) se respeta SOLO
    cuando la página no es de letras a-z y el hint es él mismo non-az (dígitos/
    signos): ahí la geometría no distingue charsets del mismo nº de columnas y el
    CNN no valida, así que el hint del usuario es la señal fiable. Para páginas
    de letras manda el agreement CNN (el hint no impone).

    Devuelve un dict por página:
        {"results": [(char, glyph, score), ...],
         "preset": str | None,          # nombre del preset elegido
         "rotation": int,               # rotación horaria aplicada
         "layout_score": float,         # score estructural del ganador
         "page_agreement": float | None,# acuerdo CNN (a-z) del ganador
         "suspect": bool,               # True = NO guardar
         "reason": str}
    """
    if clf is None and char_to_label is None:
        clf, char_to_label = _load_template_cnn()
    presets = presets or TEMPLATE_PRESETS
    # Resolver el hint a un nombre de preset (si coincide con uno registrado).
    hint_name = None
    if layout_hint is not None:
        for name, lay in presets.items():
            if lay.charset == layout_hint.charset and lay.repeats == layout_hint.repeats:
                hint_name = name
                break
    out = []
    for path in image_paths:
        try:
            out.append(_extract_page_multilayout(path, presets, hint_name, clf,
                                                 char_to_label, layout_hint=layout_hint))
        except Exception as exc:
            logger.error("extract_pdf_pages %s: %s", path, exc, exc_info=True)
            out.append({"results": [], "preset": None, "rotation": -1,
                        "layout_score": 0.0, "page_agreement": None,
                        "suspect": True, "reason": f"error: {exc}"})
    return out



"""B12: tests de fusión de detectores."""
import pytest


def _make_bbox(x, y, w, h):
    """BBox sintético compatible con fusion.py (solo necesita x,y,w,h)."""
    class _B:
        pass
    b = _B()
    b.x, b.y, b.w, b.h = x, y, w, h
    return b


def test_iou_zero_no_overlap():
    from core.inkcore.glyph_detectors.fusion import iou
    assert iou(0, 0, 10, 10, 20, 20, 10, 10) == 0.0


def test_iou_full_overlap():
    from core.inkcore.glyph_detectors.fusion import iou
    assert iou(0, 0, 10, 10, 0, 0, 10, 10) == pytest.approx(1.0)


def test_iou_partial():
    from core.inkcore.glyph_detectors.fusion import iou
    # a=[0,10)x[0,10), b=[5,15)x[5,15) → inter=25, union=200-25=175
    v = iou(0, 0, 10, 10, 5, 5, 10, 10)
    assert 0.0 < v < 1.0
    assert v == pytest.approx(25 / 175, abs=1e-4)


def test_fuse_union_single_detector():
    from core.inkcore.glyph_detectors.fusion import fuse
    dets = {"det_a": [_make_bbox(0, 0, 10, 10), _make_bbox(20, 0, 10, 10)]}
    result = fuse(dets, strategy="union", iou_threshold=0.5)
    assert len(result) == 2
    for fb in result:
        assert "det_a" in fb.sources
        assert fb.agreement_score == pytest.approx(1.0)


def test_fuse_union_dedup_high_iou():
    from core.inkcore.glyph_detectors.fusion import fuse
    # Dos detectores ven casi la misma caja → debe fusionarse en 1
    dets = {
        "det_a": [_make_bbox(0, 0, 10, 10)],
        "det_b": [_make_bbox(1, 1, 10, 10)],
    }
    result = fuse(dets, strategy="union", iou_threshold=0.3)
    assert len(result) == 1
    assert set(result[0].sources) == {"det_a", "det_b"}
    assert result[0].agreement_score == pytest.approx(1.0)


def test_fuse_union_no_dedup_low_iou():
    from core.inkcore.glyph_detectors.fusion import fuse
    # Dos detectores ven cajas distintas → deben mantenerse por separado
    dets = {
        "det_a": [_make_bbox(0, 0, 10, 10)],
        "det_b": [_make_bbox(50, 0, 10, 10)],
    }
    result = fuse(dets, strategy="union", iou_threshold=0.5)
    assert len(result) == 2


# F8 — REESCRITO. El criterio viejo de intersección anclaba en det_names[0] y
# exigía que TODOS los detectores coincidieran (devolvía vacío si el ancla no
# veía nada). El nuevo es consenso simétrico: sobrevive un bbox visto por
# >= ceil(n/2) detectores distintos, sin privilegiar a ninguno. Con n=2 el
# quórum es 1 (por eso "requires_both" ya no aplica); el caso interesante es
# n>=3, donde el quórum es la mayoría.
def test_fuse_intersection_consensus_majority():
    from core.inkcore.glyph_detectors.fusion import fuse
    # 3 detectores. Una caja vista por 2/3 (quórum=ceil(3/2)=2) sobrevive;
    # una caja solitaria vista por 1/3 se descarta.
    dets = {
        "det_a": [_make_bbox(0, 0, 10, 10), _make_bbox(200, 0, 10, 10)],
        "det_b": [_make_bbox(1, 1, 10, 10)],   # coincide con la 1ra de det_a
        "det_c": [_make_bbox(500, 0, 10, 10)],  # solitaria, nadie más la ve
    }
    result = fuse(dets, strategy="intersection", iou_threshold=0.3)
    # Solo la caja en x≈0 (vista por det_a + det_b = 2 detectores) sobrevive.
    assert len(result) == 1
    assert set(result[0].sources) == {"det_a", "det_b"}


def test_fuse_intersection_drops_lone_detection():
    from core.inkcore.glyph_detectors.fusion import fuse
    # 3 detectores, cada uno ve una caja distinta → ninguna alcanza quórum 2.
    dets = {
        "det_a": [_make_bbox(0, 0, 10, 10)],
        "det_b": [_make_bbox(100, 0, 10, 10)],
        "det_c": [_make_bbox(200, 0, 10, 10)],
    }
    result = fuse(dets, strategy="intersection", iou_threshold=0.5)
    assert len(result) == 0


def test_fuse_intersection_matching():
    from core.inkcore.glyph_detectors.fusion import fuse
    dets = {
        "det_a": [_make_bbox(0, 0, 10, 10)],
        "det_b": [_make_bbox(0, 0, 10, 10)],  # misma caja → quórum 1 con n=2
    }
    result = fuse(dets, strategy="intersection", iou_threshold=0.5)
    assert len(result) == 1
    assert result[0].agreement_score == pytest.approx(1.0)


def test_fuse_cascade_fills_gaps():
    from core.inkcore.glyph_detectors.fusion import fuse
    # Primario en x=0-10, secundario en x=50-60 (hueco real, sin solapamiento)
    dets = {
        "primary": [_make_bbox(0, 0, 10, 10)],
        "secondary": [_make_bbox(50, 0, 10, 10)],
    }
    result = fuse(dets, strategy="cascade", iou_threshold=0.5)
    # Primario debe estar + secundario que llena el hueco
    assert len(result) == 2


def test_fuse_cascade_secondary_not_duplicate():
    from core.inkcore.glyph_detectors.fusion import fuse
    # Secundario solapado en 2D con el primario → no debe añadirse
    dets = {
        "primary": [_make_bbox(0, 0, 10, 10)],
        "secondary": [_make_bbox(2, 2, 10, 10)],  # cov ≈ 0.64 > 0.3
    }
    result = fuse(dets, strategy="cascade", iou_threshold=0.5)
    # Solo debe quedar el primario; el secundario tiene >30% overlap real
    assert len(result) == 1


def test_cascade_region_mask_descarta_ruido_fuera_de_region():
    """Fase 4 — con classic_cv + neuronal, cascade filtra cajas de classic_cv
    que caen fuera de toda región neuronal (ruido de fondo)."""
    from core.inkcore.glyph_detectors.fusion import fuse
    dets = {
        # classic_cv: 2 caracteres dentro de la palabra + 1 mancha de ruido lejos.
        "classic_cv": [
            _make_bbox(5, 5, 8, 12),    # dentro de la región
            _make_bbox(15, 5, 8, 12),   # dentro de la región
            _make_bbox(200, 200, 8, 12),  # RUIDO: fuera de toda región
        ],
        # easyocr: una caja de palabra que cubre los 2 caracteres reales.
        "easyocr": [_make_bbox(0, 0, 40, 20)],
    }
    result = fuse(dets, strategy="cascade", iou_threshold=0.5)
    # Quedan los 2 caracteres dentro de la región; el ruido se descarta.
    assert len(result) == 2
    # Las cajas neuronales NO se emiten como glifos (no debe aparecer la 40x20).
    assert all(b.w < 30 for b in result)


def test_cascade_region_mask_sin_region_no_filtra():
    """Si el neuronal no devolvió regiones, no se filtra (conservador)."""
    from core.inkcore.glyph_detectors.fusion import fuse
    dets = {
        "classic_cv": [_make_bbox(5, 5, 8, 12), _make_bbox(200, 200, 8, 12)],
        "easyocr": [],  # el neuronal no detectó nada
    }
    result = fuse(dets, strategy="cascade", iou_threshold=0.5)
    # Sin regiones → se conservan TODAS las cajas de classic_cv.
    assert len(result) == 2


def test_cascade_region_mask_fallback_si_filtra_todo():
    """Si el filtro dejaría TODO fuera (regiones mal puestas), devuelve classic_cv
    sin filtrar en vez de vacío."""
    from core.inkcore.glyph_detectors.fusion import fuse
    dets = {
        "classic_cv": [_make_bbox(5, 5, 8, 12), _make_bbox(15, 5, 8, 12)],
        # región neuronal en otra zona: ningún carácter cae dentro.
        "easyocr": [_make_bbox(500, 500, 40, 20)],
    }
    result = fuse(dets, strategy="cascade", iou_threshold=0.5)
    assert len(result) == 2  # fallback: no perdemos caracteres reales


def test_fuse_cascade_multiline_same_column():
    """F8 — caso multi-línea: dos letras de líneas distintas comparten columna X.

    El criterio viejo (set de columnas X de todo el renglón) marcaba la letra de
    la línea 2 como 'ya cubierta' por la de la línea 1 y la descartaba. Con el
    solapamiento 2D, al no haber solape vertical, el secundario SÍ se conserva.
    """
    from core.inkcore.glyph_detectors.fusion import fuse
    dets = {
        # primario: una letra arriba (línea 1)
        "primary": [_make_bbox(0, 0, 10, 10)],
        # secundario: letra distinta, MISMA columna X pero línea 2 (y=50)
        "secondary": [_make_bbox(0, 50, 10, 10)],
    }
    result = fuse(dets, strategy="cascade", iou_threshold=0.5)
    assert len(result) == 2  # NO se descarta la de la segunda línea

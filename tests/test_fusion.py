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


def test_fuse_intersection_requires_both():
    from core.inkcore.glyph_detectors.fusion import fuse
    # det_a ve caja en x=0, det_b NO la ve → intersección debe ser vacía
    dets = {
        "det_a": [_make_bbox(0, 0, 10, 10)],
        "det_b": [_make_bbox(100, 0, 10, 10)],
    }
    result = fuse(dets, strategy="intersection", iou_threshold=0.5)
    assert len(result) == 0


def test_fuse_intersection_matching():
    from core.inkcore.glyph_detectors.fusion import fuse
    dets = {
        "det_a": [_make_bbox(0, 0, 10, 10)],
        "det_b": [_make_bbox(0, 0, 10, 10)],  # misma caja
    }
    result = fuse(dets, strategy="intersection", iou_threshold=0.5)
    assert len(result) == 1
    assert result[0].agreement_score == pytest.approx(1.0)


def test_fuse_cascade_fills_gaps():
    from core.inkcore.glyph_detectors.fusion import fuse
    # Primario en x=0-10, secundario en x=50-60 (hueco real)
    dets = {
        "primary": [_make_bbox(0, 0, 10, 10)],
        "secondary": [_make_bbox(50, 0, 10, 10)],
    }
    result = fuse(dets, strategy="cascade", iou_threshold=0.5)
    # Primario debe estar + secundario que llena el hueco
    assert len(result) == 2


def test_fuse_cascade_secondary_not_duplicate():
    from core.inkcore.glyph_detectors.fusion import fuse
    # Secundario en la misma zona que el primario → no debe añadirse
    dets = {
        "primary": [_make_bbox(0, 0, 10, 10)],
        "secondary": [_make_bbox(2, 2, 10, 10)],  # solapado
    }
    result = fuse(dets, strategy="cascade", iou_threshold=0.5)
    # Solo debe quedar el primario; el secundario tiene >30% overlap
    assert len(result) == 1

"""
Fusión de detecciones de múltiples detectores de glifos.
Estrategias: union, intersection, cascade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FusedBBox:
    x: int
    y: int
    w: int
    h: int
    sources: list[str] = field(default_factory=list)
    agreement_score: float = 1.0  # fracción de detectores que lo vieron


def iou(ax: int, ay: int, aw: int, ah: int,
        bx: int, by: int, bw: int, bh: int) -> float:
    """Intersection-over-Union entre dos bboxes (xywh)."""
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax + aw, bx + bw)
    iy2 = min(ay + ah, by + bh)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _bbox_iou(a: "BBox | FusedBBox", b: "BBox | FusedBBox") -> float:
    return iou(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h)


def _merge_bbox(a: FusedBBox, bx: int, by: int, bw: int, bh: int,
                source: str) -> FusedBBox:
    """Unión geométrica de dos bboxes."""
    x1 = min(a.x, bx)
    y1 = min(a.y, by)
    x2 = max(a.x + a.w, bx + bw)
    y2 = max(a.y + a.h, by + bh)
    sources = list(a.sources)
    if source not in sources:
        sources.append(source)
    return FusedBBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1, sources=sources)


def _dedup_within(boxes: list[FusedBBox], iou_thr: float) -> list[FusedBBox]:
    """Elimina duplicados dentro de un mismo grupo por IoU."""
    kept: list[FusedBBox] = []
    for box in sorted(boxes, key=lambda b: b.w * b.h, reverse=True):
        if any(_bbox_iou(box, k) >= iou_thr for k in kept):
            continue
        kept.append(box)
    return kept


def fuse(
    detections: dict[str, list],
    strategy: str,
    iou_threshold: float,
) -> list[FusedBBox]:
    """
    Fusiona detecciones de múltiples detectores.

    Args:
        detections: {detector_name: [BBox, ...]}
        strategy: "union" | "intersection" | "cascade"
        iou_threshold: IoU mínimo para considerar que dos bboxes se refieren
                       al mismo carácter.

    Returns:
        Lista de FusedBBox ordenada de izquierda a derecha, arriba a abajo.
    """
    n_detectors = max(1, len(detections))

    if strategy == "union":
        return _fuse_union(detections, iou_threshold, n_detectors)
    elif strategy == "intersection":
        return _fuse_intersection(detections, iou_threshold, n_detectors)
    elif strategy == "cascade":
        return _fuse_cascade(detections, iou_threshold, n_detectors)
    else:
        logger.warning("Estrategia de fusión desconocida '%s', usando union", strategy)
        return _fuse_union(detections, iou_threshold, n_detectors)


def _fuse_union(detections: dict[str, list], iou_thr: float,
                n_detectors: int) -> list[FusedBBox]:
    """Unión: todas las cajas con dedup por IoU. Calcula agreement_score."""
    # Construir grupos: cada detección arranca como FusedBBox propio
    groups: list[FusedBBox] = []

    for det_name, bboxes in detections.items():
        for b in bboxes:
            # Buscar grupo existente con IoU suficiente
            merged = False
            for i, g in enumerate(groups):
                if _bbox_iou(b, g) >= iou_thr:
                    groups[i] = _merge_bbox(g, b.x, b.y, b.w, b.h, det_name)
                    merged = True
                    break
            if not merged:
                groups.append(FusedBBox(
                    x=b.x, y=b.y, w=b.w, h=b.h, sources=[det_name]
                ))

    # Calcular agreement_score
    for g in groups:
        g.agreement_score = len(set(g.sources)) / n_detectors

    groups.sort(key=lambda b: (b.y, b.x))
    return groups


def _fuse_intersection(detections: dict[str, list], iou_thr: float,
                       n_detectors: int) -> list[FusedBBox]:
    """Intersección: solo sobrevive una caja si TODOS los detectores la vieron."""
    if n_detectors <= 1:
        return _fuse_union(detections, iou_thr, n_detectors)

    det_names = list(detections.keys())
    # Anclar en el primer detector, luego verificar que cada otro también lo ve
    anchor_name = det_names[0]
    anchor_boxes = detections[anchor_name]

    result: list[FusedBBox] = []
    for ab in anchor_boxes:
        matched_by: list[str] = [anchor_name]
        final_box = FusedBBox(x=ab.x, y=ab.y, w=ab.w, h=ab.h, sources=[anchor_name])
        for other_name in det_names[1:]:
            other_boxes = detections[other_name]
            best_iou = 0.0
            best_b = None
            for ob in other_boxes:
                v = _bbox_iou(ab, ob)
                if v > best_iou:
                    best_iou = v
                    best_b = ob
            if best_iou >= iou_thr and best_b is not None:
                matched_by.append(other_name)
                final_box = _merge_bbox(final_box, best_b.x, best_b.y,
                                        best_b.w, best_b.h, other_name)

        if len(matched_by) == n_detectors:
            final_box.agreement_score = 1.0
            result.append(final_box)

    result.sort(key=lambda b: (b.y, b.x))
    return result


def _fuse_cascade(detections: dict[str, list], iou_thr: float,
                  n_detectors: int) -> list[FusedBBox]:
    """Cascade: el primer detector marca regiones primarias.
    El segundo solo llena los huecos (columnas sin detección primaria).
    Útil para usar CRAFT como complemento de classic_cv.
    """
    det_names = list(detections.keys())
    if not det_names:
        return []

    primary_name = det_names[0]
    primary = [FusedBBox(x=b.x, y=b.y, w=b.w, h=b.h, sources=[primary_name],
                         agreement_score=1.0 / n_detectors)
               for b in detections[primary_name]]

    if len(det_names) < 2:
        return sorted(primary, key=lambda b: (b.y, b.x))

    # Encontrar "huecos" horizontales donde el primario no detectó nada.
    # Un hueco es un rango X sin cobertura del primario.
    if primary:
        covered_x: set[int] = set()
        for b in primary:
            for x in range(b.x, b.x + b.w):
                covered_x.add(x)
    else:
        covered_x = set()

    secondary_name = det_names[1]
    secondary_fills: list[FusedBBox] = []
    for b in detections[secondary_name]:
        # Solo añadir si la mayor parte del bbox está en un hueco
        overlap = sum(1 for x in range(b.x, b.x + b.w) if x in covered_x)
        coverage = overlap / max(1, b.w)
        if coverage < 0.3:  # < 30% solapado con primario → es un hueco real
            secondary_fills.append(
                FusedBBox(x=b.x, y=b.y, w=b.w, h=b.h,
                          sources=[secondary_name],
                          agreement_score=1.0 / n_detectors)
            )

    all_boxes = primary + secondary_fills
    all_boxes.sort(key=lambda b: (b.y, b.x))
    return all_boxes

"""R16 — vectorize: glifo raster (banco Huevonitis) -> polilíneas de esqueleto.

Ruta NUEVA y AISLADA: solo lee PNGs + _manifest.json del banco, no toca nada.

Pipeline por glifo:
  alpha>40 -> mask bool
  -> (limpieza: cerrar huecos de 1px, quitar motas < MIN_BLOB_AREA px)
  -> skimage.morphology.skeletonize
  -> sknw.build_sknw (grafo: nodos=uniones/extremos, aristas con 'pts')
  -> poda de espolones (aristas hoja mas cortas que SPUR_LEN px)
  -> aristas -> polilíneas (x,y) en píxeles
  -> fusión de cadenas (une polilíneas por extremos en nodos de grado 2 tras la poda)
  -> simplificación RDP (tol ~0.8 px)
  -> orden greedy nearest-neighbor (minimiza salto pluma-arriba; puede invertir trazos)

Determinista: no usa RNG.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import cv2
import numpy as np
import sknw
from PIL import Image
from rdp import rdp
from skimage.morphology import binary_closing, remove_small_objects, skeletonize

ALPHA_THR = 40          # regla del banco: alpha>40 = tinta
MIN_BLOB_AREA = 12      # motas mas chicas se descartan (ruido de extracción)
SPUR_LEN = 4.0          # px: piso de poda de espolones (se adapta al grosor del trazo)
RDP_TOL = 0.8           # px: tolerancia de simplificación

Polyline = list  # list[(x, y)]


# ---------------------------------------------------------------- esqueleto

def skeletonize_glyph(mask: np.ndarray) -> list[Polyline]:
    """mask bool (H,W) -> lista de polilíneas [(x,y),...] en coords de píxel.

    Orden de salida: greedy nearest-neighbor para minimizar pen-up travel.
    """
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return []

    # limpieza suave: cierra poros de 1px que parten el esqueleto, quita motas
    with warnings.catch_warnings():  # skimage deprecó min_size/binary_closing
        warnings.simplefilter("ignore", FutureWarning)
        mask = binary_closing(mask, footprint=np.ones((3, 3), bool))
        mask = remove_small_objects(mask, min_size=MIN_BLOB_AREA)
    if not mask.any():
        return []

    skel = skeletonize(mask)
    if not skel.any():
        return []

    graph = sknw.build_sknw(skel.astype(np.uint8))

    # grosor típico del trazo (2×dist mediana del esqueleto al borde):
    # los espolones del esqueleto miden ~medio grosor, así que podamos
    # todo espolón hoja mas corto que ~0.9×grosor (con piso SPUR_LEN).
    dist = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
    stroke_w = 2.0 * float(np.median(dist[skel])) if skel.any() else 2.0
    spur_len = max(SPUR_LEN, 0.9 * stroke_w)

    polys: list[np.ndarray] = []  # cada una (N,2) en (row, col)
    if graph.number_of_edges() == 0:
        # glifo degenerado: puntos sueltos (ej. el punto de la 'i', diéresis)
        for _n, data in graph.nodes(data=True):
            o = data["o"]
            polys.append(np.array([o, o], dtype=float))
    else:
        # 1) poda ITERATIVA de espolones: aristas hoja cortas (ramas espurias);
        #    tras quitar una, otro nodo puede volverse hoja -> repetir
        multi = graph.is_multigraph()
        while graph.number_of_edges() > 1:
            edge_iter = (graph.edges(keys=True, data=True) if multi
                         else ((u, v, None, d) for u, v, d in graph.edges(data=True)))
            drop = None
            for u, v, k, data in edge_iter:
                # exactamente un extremo es hoja -> espolón
                # (si ambos son hoja es un trazo entero corto: se conserva)
                if data["weight"] < spur_len and (graph.degree(u) == 1) != (graph.degree(v) == 1):
                    drop = (u, v, k) if multi else (u, v)
                    break
            if drop is None:
                break
            graph.remove_edge(*drop)

        for u, v, data in graph.edges(data=True):
            pts = np.asarray(data["pts"], dtype=float)
            if len(pts) == 0:
                pts = np.array([graph.nodes[u]["o"], graph.nodes[v]["o"]], dtype=float)
            else:
                # sknw a veces no incluye los centros de nodo: anclar extremos
                pts = np.vstack([graph.nodes[u]["o"], pts, graph.nodes[v]["o"]])
            polys.append(pts)

        # nodos aislados que quedaron (componentes de 1 px)
        for _n, data in graph.nodes(data=True):
            if graph.degree(_n) == 0:
                o = data["o"]
                polys.append(np.array([o, o], dtype=float))

    # 2) fusionar cadenas: unir polilíneas que comparten extremo cuando ese
    #    extremo solo conecta 2 trazos (grado 2 efectivo tras la poda)
    polys = _merge_chains(polys)

    # 3) (row,col) -> (x,y) + simplificar
    out: list[Polyline] = []
    for p in polys:
        xy = p[:, ::-1]  # (col,row) = (x,y)
        if len(xy) > 2:
            xy = rdp(xy, epsilon=RDP_TOL)
        out.append([(float(x), float(y)) for x, y in np.atleast_2d(xy)])

    # 4) orden greedy nearest-neighbor con inversión opcional
    return _order_strokes(out)


def _merge_chains(polys: list[np.ndarray]) -> list[np.ndarray]:
    """Une polilíneas encadenadas por extremos compartidos exactamente entre 2."""
    def key(pt):
        return (round(pt[0], 1), round(pt[1], 1))

    changed = True
    polys = [p for p in polys if len(p)]
    while changed:
        changed = False
        ends: dict[tuple, list[tuple[int, bool]]] = {}
        for i, p in enumerate(polys):
            ends.setdefault(key(p[0]), []).append((i, False))
            ends.setdefault(key(p[-1]), []).append((i, True))
        for _k, lst in ends.items():
            if len(lst) != 2:
                continue
            (i, i_end), (j, j_end) = lst
            if i == j:
                continue  # lazo cerrado
            a, b = polys[i], polys[j]
            a = a if i_end else a[::-1]          # a termina en k
            b = b if not j_end else b[::-1]      # b empieza en k
            merged = np.vstack([a, b[1:]])
            polys = [p for idx, p in enumerate(polys) if idx not in (i, j)]
            polys.append(merged)
            changed = True
            break
    return polys


def _order_strokes(strokes: list[Polyline]) -> list[Polyline]:
    """Greedy nearest-neighbor desde el trazo más arriba-izquierda; invierte
    trazos si conviene. Determinista."""
    if len(strokes) <= 1:
        return strokes
    remaining = list(strokes)
    # arranque: extremo más cercano a (0,0) (arriba-izquierda, como la pluma)
    start_i = min(range(len(remaining)),
                  key=lambda i: min(_d2((0, 0), remaining[i][0]), _d2((0, 0), remaining[i][-1])))
    cur = remaining.pop(start_i)
    if _d2((0, 0), cur[-1]) < _d2((0, 0), cur[0]):
        cur = cur[::-1]
    ordered = [cur]
    pos = cur[-1]
    while remaining:
        best, best_d, best_rev = 0, math.inf, False
        for i, s in enumerate(remaining):
            d0, d1 = _d2(pos, s[0]), _d2(pos, s[-1])
            if d0 < best_d:
                best, best_d, best_rev = i, d0, False
            if d1 < best_d:
                best, best_d, best_rev = i, d1, True
        s = remaining.pop(best)
        if best_rev:
            s = s[::-1]
        ordered.append(s)
        pos = s[-1]
    return ordered


def _d2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


# ---------------------------------------------------------------- banco

class StrokeBank:
    """Acceso de solo-lectura al banco de glifos para vectorización."""

    def __init__(self, bank_dir: str | Path):
        self.dir = Path(bank_dir)
        with open(self.dir / "_manifest.json", encoding="utf-8") as f:
            manifest = json.load(f)
        self.by_char: dict[str, list[dict]] = {}
        for g in manifest:
            self.by_char.setdefault(g["char"], []).append(g)

    def entries(self, char: str) -> list[dict]:
        return self.by_char.get(char, [])


def load_stroke_glyph(char: str, bank: StrokeBank, index: int = 0) -> dict:
    """Carga un glifo del banco y devuelve sus trazos normalizados a em.

    Coordenadas normalizadas: x_em = x_px/em_px, y_em = (y_px - baseline_off)/em_px
    => y_em = 0 en la línea base, negativo hacia arriba del renglón NO — acá
    y crece hacia abajo como en imagen, así que la tinta sobre la baseline
    queda con y_em < 0. Igual que el raster: al render con font_size F,
    px = em * F  (altura_render = font_size * alto_tinta/em_px se cumple
    porque dividimos TODO por em_px del glifo).
    """
    entry = bank.entries(char)[index]
    img = Image.open(entry["image_path"]).convert("RGBA")
    alpha = np.asarray(img)[:, :, 3]
    mask = alpha > ALPHA_THR

    # bbox de tinta: el manifest mide nat_h/baseline_off sobre la tinta
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return {"char": char, "strokes": [], "entry": entry}
    y0, x0 = ys.min(), xs.min()

    strokes_px = skeletonize_glyph(mask)
    em = float(entry["em_px"])
    base = float(entry["baseline_off"])  # px desde el tope de la tinta a la baseline
    strokes_em = [
        [((x - x0) / em, ((y - y0) - base) / em) for x, y in s]
        for s in strokes_px
    ]
    return {
        "char": char,
        "strokes": strokes_em,        # coords em: x desde borde izq de tinta, y=0 en baseline
        "strokes_px": strokes_px,     # coords de píxel del PNG (debug)
        "adv_em": (xs.max() + 1 - x0) / em,   # ancho de tinta en em
        "h_em": (ys.max() + 1 - y0) / em,     # alto de tinta en em (= nat_h_px/em_px)
        "entry": entry,
    }

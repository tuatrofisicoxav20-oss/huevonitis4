"""Filtros de calidad de glifos — compartidos por la purga del banco y el gate de captura.

Hallazgos de reconocimiento (Fase 0 del plan de purga) que fijan el diseño:

  • Las imágenes del banco son RGBA del extractor: tinta BLANCA con la forma
    viviendo SOLO en el canal alpha (BUG-18). Toda métrica parte de
    _glyph_to_gray (bank_hashing), nunca de la luminancia directa.
  • El banco guarda crop ajustado a la tinta + ~6 px de padding, CLAMPEADO a la
    celda de origen: tinta tocando el borde es común y legítima (descendentes).
    Por eso CLIPPED no usa el anillo ciego de 1 px (mataría ~37% de glifos
    buenos) sino la heurística de corte antinatural: una línea recta de tinta
    sobre el borde que abarque ≥ CLIP_EDGE_FRACTION del lado.
  • Para duplicados se reutiliza el hash del repo (_dhash 256 bits + _hamming +
    _dup_thresholds por carácter) — no se inventa otro hash. El umbral
    "Hamming ≤ 4 sobre 64 bits" del plan se mapea al umbral strict por carácter.
  • OpenCV ya es dependencia core: componentes conexos vía cv2.
  • La metadata de baseline (baseline_off/em_px) está vacía en el banco actual
    (nat_h_px=0), así que la alineación usa la aproximación por centroide.

Los umbrales relativos se calibran contra la mediana de la población de cada
carácter; con menos de FALLBACK_MIN_SAMPLES muestras solo aplican los umbrales
absolutos de fallback.
"""
import logging
import math
from dataclasses import dataclass, field
from statistics import median, mode

import numpy as np

from core.inkcore.bank_hashing import _dhash, _glyph_to_gray, _hamming

try:
    from PIL import Image
    PIL_OK = True
except ImportError:  # pragma: no cover
    PIL_OK = False

logger = logging.getLogger(__name__)

# ── CONFIG único: todos los umbrales de purga/gate viven aquí ───────────────
CONFIG = {
    # Filtros duros
    "MIN_BBOX_PX": 5,                # SPECK absoluto (bbox de tinta < 5×5 px)
    "MIN_AREA_VS_MEDIAN": 0.10,      # SPECK relativo (área bbox < 10% mediana del char)
    "GHOST_REL": 0.30, "GHOST_ABS": 0.03,   # densidad: AND para no matar '.' legítimos
    "BLOB_REL": 2.50, "BLOB_ABS": 0.55,
    # Guard de forma para BLOB absoluto (modo fallback, sin mediana): un trazo
    # delgado ('i', 'l', '-') o un punto llenan su bbox con densidad ~1.0 sin
    # ser manchones. Solo es BLOB si además es cuadradote Y grande.
    "BLOB_ASPECT_RANGE": (0.45, 2.2), "BLOB_MIN_DIM_ABS": 20,
    "CLIP_EDGE_FRACTION": 0.30,      # corte recto en borde ≥ 30% del lado
    "NOISE_COMPONENT_FRACTION": 0.03,  # comps con < 3% de la tinta no cuentan
    "FRAG_TOLERANCE": 1, "FRAG_HARD_EXCESS": 2,
    "ASPECT_LOG_MAX": 2.2,           # |log(aspect/mediana)| > log(2.2) → kill
    "AREA_OUTLIER_HI": 4.0, "AREA_OUTLIER_LO": 0.25,
    # Score 0-100
    "WEIGHTS": {"alineacion": 0.30, "binarizacion": 0.20,
                "trazo": 0.20, "tamano": 0.15, "similitud": 0.15},
    "QUALITY_FLOOR": 50.0,
    "TOP_K": 30,
    # Banda de similitud (distancia hamming normalizada al centroide del char)
    "SIM_BAND_LO": 0.02, "SIM_BAND_HI": 0.35,
    # Guards y fusibles
    "MIN_SURVIVORS": 3,
    "FUSE_GLOBAL_KILL_RATE": 0.85,
    "FUSE_RECAPTURE_CHAR_RATE": 0.40,
    # Mínimo de muestras para calibrar umbrales relativos a la mediana
    "FALLBACK_MIN_SAMPLES": 5,
}

# Componentes conexos esperados cuando la población del char no alcanza para
# calcular la moda (tabla de fallback del plan).
_FALLBACK_COMPONENTS = {
    **dict.fromkeys("ij", 2),
    **dict.fromkeys("áéíóúñü", 2),
    **dict.fromkeys("¡!¿?:;", 2),
    "%": 3, '"': 2, "=": 2,
}


def expected_components(char: str) -> int:
    return _FALLBACK_COMPONENTS.get(char.lower(), 1)


# ── Métricas por glifo ───────────────────────────────────────────────────────

@dataclass
class GlyphMetrics:
    """Mediciones crudas de un glifo (sobre la máscara de tinta del alpha)."""
    img_w: int = 0
    img_h: int = 0
    bbox_w: int = 0
    bbox_h: int = 0
    bbox_area: int = 0
    ink_px: int = 0
    density: float = 0.0       # tinta / área del bbox
    aspect: float = 1.0        # bbox_w / bbox_h
    n_components: int = 0      # tras ignorar ruido (< NOISE_COMPONENT_FRACTION)
    edge_cut: str = ""         # lado con corte recto ("top"/"bottom"/...) o ""
    centroid_dev: float = 0.0  # desvío vertical del centroide vs centro del bbox (norm.)
    midband: float = 0.0       # fracción de grises sucios (banda media) en la tinta
    roughness: float = 0.0     # perímetro² / tinta (rugosidad del contorno)
    dhash: str = ""
    empty: bool = False        # sin tinta detectable


def _count_components(mask: np.ndarray, ink_px: int, noise_fraction: float) -> int:
    """Componentes conexos descartando motas con menos de noise_fraction de la tinta."""
    m8 = mask.astype(np.uint8)
    try:
        import cv2
        n, _labels, stats, _ = cv2.connectedComponentsWithStats(m8, connectivity=8)
        sizes = [int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n)]
    except ImportError:  # pragma: no cover - cv2 es dependencia core
        from scipy import ndimage
        labels, n = ndimage.label(m8)
        sizes = [int(s) for s in ndimage.sum(m8, labels, range(1, n + 1))]
    floor_px = max(1, int(ink_px * noise_fraction))
    return sum(1 for s in sizes if s >= floor_px)


def _max_run(line: np.ndarray) -> int:
    """Longitud de la racha más larga de True en un vector booleano."""
    best = cur = 0
    for v in line:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def _edge_cut_side(mask: np.ndarray, fraction: float) -> str:
    """Detecta un corte antinatural: línea recta de tinta pegada a un borde.

    Los finales de trazo naturales no forman rachas rectas largas sobre el
    borde de la imagen; un trazo cercenado por el recorte de la celda sí.
    """
    sides = {
        "top": mask[0, :], "bottom": mask[-1, :],
        "left": mask[:, 0], "right": mask[:, -1],
    }
    for name, line in sides.items():
        side_len = len(line)
        if side_len >= CONFIG["MIN_BBOX_PX"] and _max_run(line) >= side_len * fraction:
            return name
    return ""


def measure_glyph(img: "Image.Image", cfg: dict = CONFIG) -> GlyphMetrics:
    """Mide un glifo RGBA/L del banco. Toda la tinta sale de _glyph_to_gray."""
    gray_img = _glyph_to_gray(img)
    gray = np.asarray(gray_img, dtype=np.uint8)
    mask = gray < 128
    m = GlyphMetrics(img_w=img.width, img_h=img.height)
    ys, xs = np.where(mask)
    if xs.size == 0:
        m.empty = True
        return m
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    m.bbox_w, m.bbox_h = x1 - x0 + 1, y1 - y0 + 1
    m.bbox_area = m.bbox_w * m.bbox_h
    m.ink_px = int(mask.sum())
    m.density = m.ink_px / m.bbox_area
    m.aspect = m.bbox_w / m.bbox_h
    m.n_components = _count_components(mask, m.ink_px, cfg["NOISE_COMPONENT_FRACTION"])
    m.edge_cut = _edge_cut_side(mask, cfg["CLIP_EDGE_FRACTION"])
    cy = float(ys.mean())
    m.centroid_dev = abs(cy - (y0 + y1) / 2.0) / max(1, m.bbox_h)
    # Grises sucios: píxeles ni claramente fondo ni claramente tinta
    mid = np.logical_and(gray > 51, gray < 204)
    near_ink = gray < 230
    m.midband = float(mid.sum()) / max(1, int(near_ink.sum()))
    # Rugosidad: perímetro (borde de la máscara) al cuadrado sobre tinta
    inner = np.zeros_like(mask)
    inner[1:-1, 1:-1] = (mask[1:-1, 1:-1] & mask[:-2, 1:-1] & mask[2:, 1:-1]
                         & mask[1:-1, :-2] & mask[1:-1, 2:])
    perimeter = int(mask.sum() - inner.sum())
    m.roughness = (perimeter ** 2) / max(1, m.ink_px)
    m.dhash = _dhash(img)
    return m


# ── Estadística por carácter ────────────────────────────────────────────────

@dataclass
class CharStats:
    """Medianas/moda de la población de un carácter (calibran los filtros)."""
    n: int = 0
    med_area: float = 0.0
    med_density: float = 0.0
    med_aspect: float = 1.0
    med_h: float = 0.0
    med_roughness: float = 0.0
    mode_components: int = 1
    hash_centroid: str = ""
    fallback: bool = True      # True → población chica: solo umbrales absolutos
    expected_comp: int = 1
    sim_dists: list = field(default_factory=list)


def compute_char_stats(char: str, metrics: list[GlyphMetrics],
                       cfg: dict = CONFIG) -> CharStats:
    valid = [m for m in metrics if not m.empty]
    st = CharStats(n=len(valid))
    st.expected_comp = expected_components(char)
    if not valid:
        return st
    st.med_area = median(m.bbox_area for m in valid)
    st.med_density = median(m.density for m in valid)
    st.med_aspect = median(m.aspect for m in valid)
    st.med_h = median(m.bbox_h for m in valid)
    st.med_roughness = median(m.roughness for m in valid)
    try:
        st.mode_components = mode(m.n_components for m in valid)
    except Exception:
        st.mode_components = st.expected_comp
    st.fallback = len(valid) < cfg["FALLBACK_MIN_SAMPLES"]
    if not st.fallback:
        st.expected_comp = st.mode_components
    # Centroide de hashes: bit mayoritario por posición
    hashes = [m.dhash for m in valid if m.dhash]
    if hashes:
        bits = np.array([[c == "1" for c in h] for h in hashes])
        st.hash_centroid = "".join(
            "1" if v else "0" for v in (bits.mean(axis=0) >= 0.5))
        st.sim_dists = [_hamming(h, st.hash_centroid) for h in hashes]
    return st


# ── Filtros duros (reason codes) ────────────────────────────────────────────

def hard_filter_reason(m: GlyphMetrics, st: CharStats,
                       cfg: dict = CONFIG) -> tuple[str, str] | None:
    """Devuelve (reason_code, detalle) si el glifo debe morir, o None si pasa.

    Con población chica (st.fallback) solo aplican los umbrales absolutos.
    """
    if m.empty:
        return ("SPECK", "sin tinta detectable")
    # SPECK — basura microscópica
    if m.bbox_w < cfg["MIN_BBOX_PX"] and m.bbox_h < cfg["MIN_BBOX_PX"]:
        return ("SPECK", f"bbox {m.bbox_w}x{m.bbox_h} < {cfg['MIN_BBOX_PX']}px")
    if not st.fallback and m.bbox_area < st.med_area * cfg["MIN_AREA_VS_MEDIAN"]:
        return ("SPECK", f"área {m.bbox_area} < 10% de mediana {st.med_area:.0f}")
    # GHOST / BLOB — densidad fuera de rango (AND relativo+absoluto)
    if st.fallback:
        if m.density < cfg["GHOST_ABS"]:
            return ("GHOST", f"densidad {m.density:.3f} < {cfg['GHOST_ABS']}")
        a_lo, a_hi = cfg["BLOB_ASPECT_RANGE"]
        if (m.density > cfg["BLOB_ABS"] and a_lo <= m.aspect <= a_hi
                and max(m.bbox_w, m.bbox_h) >= cfg["BLOB_MIN_DIM_ABS"]):
            return ("BLOB", f"densidad {m.density:.3f} > {cfg['BLOB_ABS']}")
    else:
        if (m.density < st.med_density * cfg["GHOST_REL"]
                and m.density < cfg["GHOST_ABS"]):
            return ("GHOST", f"densidad {m.density:.3f} < 0.3×med {st.med_density:.3f}")
        if (m.density > st.med_density * cfg["BLOB_REL"]
                and m.density > cfg["BLOB_ABS"]):
            return ("BLOB", f"densidad {m.density:.3f} > 2.5×med {st.med_density:.3f}")
    # CLIPPED — corte recto antinatural pegado al borde
    if m.edge_cut:
        return ("CLIPPED", f"corte recto en borde '{m.edge_cut}'")
    # FRAGMENTED — componentes conexos incorrectos
    exp = st.expected_comp
    if m.n_components > exp + cfg["FRAG_HARD_EXCESS"]:
        return ("FRAGMENTED", f"{m.n_components} comps > esperados {exp}+2")
    if exp == 1 and m.n_components >= 3:
        return ("FRAGMENTED", f"{m.n_components} comps con 1 esperado")
    # OUTLIER_SHAPE — proporción/tamaño imposible (solo con población calibrada)
    if not st.fallback:
        if st.med_aspect > 0 and abs(math.log(m.aspect / st.med_aspect)) > math.log(
                cfg["ASPECT_LOG_MAX"]):
            return ("OUTLIER_SHAPE",
                    f"aspect {m.aspect:.2f} vs mediana {st.med_aspect:.2f}")
        if st.med_area > 0:
            ratio = m.bbox_area / st.med_area
            if ratio > cfg["AREA_OUTLIER_HI"] or ratio < cfg["AREA_OUTLIER_LO"]:
                return ("OUTLIER_SHAPE", f"área {ratio:.2f}× la mediana")
    return None


# ── Score de calidad 0-100 ──────────────────────────────────────────────────

def quality_score(m: GlyphMetrics, st: CharStats,
                  cfg: dict = CONFIG) -> tuple[float, dict]:
    """Score 0-100 ponderado; devuelve (score, componentes) para auditoría.

    Sin población calibrada los componentes relativos valen 0.7 (neutros).
    """
    w = cfg["WEIGHTS"]
    neutral = 0.7
    if m.empty:
        return 0.0, {}
    # Alineación: altura vs mediana + desvío del centroide vertical
    if not st.fallback and st.med_h > 0:
        s_h = max(0.0, 1.0 - abs(m.bbox_h - st.med_h) / st.med_h)
        s_c = max(0.0, 1.0 - m.centroid_dev * 2.0)
        align = (s_h + s_c) / 2.0
    else:
        align = neutral
    # Limpieza de binarización: grises sucios; si es binaria pura, rugosidad
    if m.midband > 0.001:
        binar = max(0.0, 1.0 - m.midband / 0.5)
    elif not st.fallback and st.med_roughness > 0:
        binar = max(0.0, min(1.0, st.med_roughness / max(1e-6, m.roughness)))
    else:
        binar = neutral
    # Integridad de trazo
    diff = abs(m.n_components - st.expected_comp)
    trazo = 1.0 if diff == 0 else (0.5 if diff <= cfg["FRAG_TOLERANCE"] else 0.0)
    # Consistencia de tamaño
    if not st.fallback and st.med_area > 0 and m.bbox_area > 0:
        r = m.bbox_area / st.med_area
        tam = min(r, 1.0 / r)
    else:
        tam = neutral
    # Banda de similitud: ni clon del centroide ni alienígena
    if st.hash_centroid and m.dhash:
        d = _hamming(m.dhash, st.hash_centroid) / max(1, len(st.hash_centroid))
        lo, hi = cfg["SIM_BAND_LO"], cfg["SIM_BAND_HI"]
        if d < lo:
            sim = 0.8  # penalización suave: estar cerca del promedio no es delito
        elif d <= hi:
            sim = 1.0
        else:
            sim = max(0.0, 1.0 - (d - hi) / hi)
    else:
        sim = neutral
    parts = {"alineacion": align, "binarizacion": binar, "trazo": trazo,
             "tamano": tam, "similitud": sim}
    score = 100.0 * sum(w[k] * v for k, v in parts.items())
    return round(score, 2), parts


# ── Gate de captura (Fase 7: endurecer el extractor) ────────────────────────

def capture_gate(glyph: "Image.Image", char: str,
                 bank_metrics_for_char: list[GlyphMetrics] | None,
                 cfg: dict = CONFIG) -> tuple[bool, str]:
    """Gate en el momento de captura: lo que no pasa, no entra al banco.

    Los umbrales relativos usan la mediana de lo YA existente en el banco para
    ese carácter; si el carácter es nuevo (o hay pocas muestras) solo aplican
    los absolutos de fallback. Devuelve (ok, "REASON: detalle").
    """
    m = measure_glyph(glyph, cfg)
    st = compute_char_stats(char, bank_metrics_for_char or [], cfg)
    verdict = hard_filter_reason(m, st, cfg)
    if verdict is None:
        return True, ""
    return False, f"{verdict[0]}: {verdict[1]}"

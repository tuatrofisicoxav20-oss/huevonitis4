"""Pase de tinta y papel del render (Fase R6 — D1/D2/D8/D10, I2 light).

La composición deja de ser un paste plano de color sólido:

  • value_noise_field: campo de ruido suave (grid aleatorio chico + resize
    BICUBIC — sin dependencia de Perlin) que modula el alpha DENTRO del
    trazo (D2): la tinta respira, no por letra (eso era el tell #5) sino por
    zona, como la carga real de un bolígrafo.
  • jitter_ink_color: micro-variación HSV del color por glifo (D1) — V±3%,
    S±4%: ninguna pluma deposita exactamente el mismo color dos veces.
  • apply_paper: compone la CAPA de tinta sobre el papel con MULTIPLY (D10):
    la tinta oscurece el papel y su textura se ve a través del trazo, en vez
    de taparlo con un color opaco. Sangrado opcional (D8): blur sub-píxel del
    alpha antes de componer.

separar tinta de papel (I2) es lo que permite que R7 cambie el papel sin
tocar la tinta y viceversa.
"""
from __future__ import annotations

import colorsys
import random

import numpy as np

try:
    from PIL import Image, ImageFilter
    PIL_OK = True
except ImportError:
    PIL_OK = False

from core.inkcore.renderer_noise import tnorm


def value_noise_field(w: int, h: int, rng: random.Random,
                      cell_px: int = 48, lo: float = 0.88,
                      hi: float = 1.0) -> np.ndarray:
    """Campo (h, w) float32 en [lo, hi]: ruido de baja frecuencia.

    Grid aleatorio de ~cell_px por celda interpolado con BICUBIC al tamaño de
    página — la frecuencia queda a escala de trazos/palabras, no de píxel.
    """
    gw = max(2, w // max(8, cell_px))
    gh = max(2, h // max(8, cell_px))
    grid = np.array([[rng.random() for _ in range(gw)] for _ in range(gh)],
                    dtype=np.float32)
    img = Image.fromarray(grid).resize((w, h), Image.BICUBIC)
    field = np.asarray(img, dtype=np.float32)
    field = np.clip(field, 0.0, 1.0)
    return lo + field * (hi - lo)


def jitter_ink_color(base_hex: str, rng: random.Random,
                     s_jitter: float = 0.04, v_jitter: float = 0.03) -> str:
    """Color de tinta con micro-variación HSV por glifo (D1). Devuelve hex."""
    from PIL import ImageColor
    try:
        r, g, b = ImageColor.getrgb(base_hex)[:3]
    except (ValueError, TypeError):
        r, g, b = (26, 26, 46)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if s_jitter > 0:
        s = min(1.0, max(0.0, s + tnorm(rng, 0.0, s_jitter * 0.6,
                                        -s_jitter, s_jitter)))
    if v_jitter > 0:
        v = min(1.0, max(0.0, v + tnorm(rng, 0.0, v_jitter * 0.6,
                                        -v_jitter, v_jitter)))
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r2 * 255):02x}{int(g2 * 255):02x}{int(b2 * 255):02x}"


def _ink_texture_v2(a: np.ndarray, options, rng: random.Random):
    """Textura intra-trazo (R11). Recibe el alpha (float [0,1]) de la región con
    tinta y devuelve ``(a, ink_scale)``:

      • a: alpha modulado — grosor variable (dilatación por ruido) + densidad
        fina A LO LARGO del trazo (value-noise de alta frecuencia).
      • ink_scale: mapa (h, w) float en (0, 1] para OSCURECER el color de tinta
        donde el coverage local es alto (apozamiento, D-pool); None si apagado.

    Solo toca valores de alpha/color, nunca geometría: shape y baseline intactos.
    """
    h, w = a.shape
    fs = max(1, int(getattr(options, "font_size", 40)))
    ink_scale = None  # multiplicador del COLOR de tinta: <1 oscurece, >1 aclara

    # --- grosor variable: dilatación ligera mezclada por campo de baja frecuencia.
    #     ESTO sí toca el alpha (ancho del trazo); apagado por default.
    wj = max(0.0, getattr(options, "ink_width_jitter", 0.0))
    if wj > 0:
        rad = max(1, round(fs * 0.05 * min(1.0, wj)))
        a_img = Image.fromarray((np.clip(a, 0.0, 1.0) * 255).astype(np.uint8))
        dil = np.asarray(a_img.filter(ImageFilter.MaxFilter(rad * 2 + 1)),
                         dtype=np.float32) / 255.0
        lf = value_noise_field(w, h, rng, cell_px=max(8, int(fs * 0.5)),
                               lo=0.0, hi=1.0)
        a = a + (dil - a) * lf * wj

    # --- densidad fina A LO LARGO del trazo: la tinta real varía en OSCURIDAD,
    #     no en ancho — unas zonas depositan más (pool), otras saltan (dry). Por
    #     eso se modula el COLOR, no el alpha: modular alpha sobre trazos ya finos
    #     solo los adelgaza/aclara y BAJA la variación. El campo va centrado algo
    #     por debajo de 1.0 (lo<1, hi>1) → más zonas oscuras que claras, sin
    #     aplanar. cell ∝ font_size (escala de trazo, no de zona como en R6).
    fstr = max(0.0, getattr(options, "ink_texture_fine_strength", 0.0))
    if fstr > 0:
        frac = max(0.05, getattr(options, "ink_texture_fine_cell_frac", 0.15))
        cell = max(3, int(fs * frac))
        field = value_noise_field(w, h, rng, cell_px=cell,
                                  lo=1.0 - fstr, hi=1.0 + fstr * 0.5)
        ink_scale = field

    # --- apozamiento: coverage local (alpha difuminado) → oscurece el COLOR donde
    #     se acumula tinta (cruces, vueltas, núcleo grueso). El interior del trazo
    #     ya está saturado en alpha, así que la acumulación se modela en color.
    pool = max(0.0, getattr(options, "ink_pooling", 0.0))
    if pool > 0:
        sigma = max(0.6, fs * 0.08)
        a_img = Image.fromarray((np.clip(a, 0.0, 1.0) * 255).astype(np.uint8))
        cov = np.asarray(a_img.filter(ImageFilter.GaussianBlur(sigma)),
                         dtype=np.float32) / 255.0
        pool_scale = 1.0 - pool * np.clip(cov, 0.0, 1.0)
        ink_scale = pool_scale if ink_scale is None else ink_scale * pool_scale

    return np.clip(a, 0.0, 1.0), ink_scale


def apply_ink_blobs(img: Image.Image, rng: random.Random, *,
                    font_size: float, strength: float) -> Image.Image:
    """R17b — bolitas de tinta en los EXTREMOS del trazo (pen-down / pen-up).

    El delator de tinta que más repitió el jurado: "no hay charco de tinta en
    arranques/paradas, ni la gota inicial del bolígrafo". Un bolígrafo real
    deposita un pequeño POOL donde la punta se apoya al empezar el trazo (y a
    veces al levantar). Se detectan los extremos del trazo con el esqueleto
    (píxeles con UN solo vecino) y se SUMA un blob gaussiano al alpha:
    engrosa+solidifica localmente el trazo, como un charco redondeado.

    Sólo AGREGA alpha (np.clip suma) → NUNCA puede cortar el trazo: cero
    riesgo de romper legibilidad por adelgazamiento. CLAMPS: no corre en glifos
    diminutos (puntuación/diacríticos), el radio se acota a 0.085·font_size y
    el blob se ancla al semiancho local (dt) para no desbordar. Sin skimage/cv2
    devuelve el glifo intacto. Determinista desde el rng recibido (el caller le
    pasa uno PROPIO sembrado del contenido, patrón de apply_pen_skips)."""
    try:
        import cv2
        from scipy.ndimage import convolve
        from skimage.morphology import skeletonize
    except ImportError:
        return img
    a = np.asarray(img.getchannel("A"), dtype=np.uint8)
    h, w = a.shape
    fs = max(8.0, float(font_size))
    if min(h, w) < 0.16 * fs:
        return img                      # puntuación/diacríticos: no tocar
    m = (a > 110).astype(np.uint8)
    if m.sum() < 0.01 * fs * fs:
        return img                      # tinta insuficiente
    try:
        skel = skeletonize(m > 0)
    except Exception:
        return img
    if skel.sum() < 3:
        return img
    # extremos = píxeles del esqueleto con exactamente 1 vecino esqueleto.
    k = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    nbr = convolve(skel.astype(np.uint8), k, mode="constant", cval=0)
    ep = np.argwhere(skel & (nbr == 1))
    if len(ep) == 0:
        return img
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    af = a.astype(np.float32)
    # nº de bolitas ∝ strength (1 casi siempre; 2 con strength alto). Se
    # eligen extremos al azar; el pen-down real cae más en el PRIMER trazo,
    # pero sin orden de trazo se muestrea uniforme (sesgo leve hacia arriba).
    order = list(range(len(ep)))
    rng.shuffle(order)
    n_blobs = 1 + (1 if (len(ep) > 1 and rng.random() < min(0.9, strength * 1.6)) else 0)
    for idx in order[:n_blobs]:
        cy, cx = float(ep[idx][0]), float(ep[idx][1])
        hw = max(1.0, float(dt[int(cy), int(cx)]))
        r = min(0.085 * fs, max(1.5, hw * rng.uniform(1.4, 2.3)))
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        blob = np.exp(-d2 / max(1.0, 2.0 * (0.55 * r) ** 2))
        # amplitud ∝ strength; el blob llena hasta opaco cerca del centro y se
        # difumina hacia el papel (feather), extendiendo un pelo el extremo.
        af = np.clip(af + blob * 255.0 * min(1.0, 0.55 + strength), 0.0, 255.0)
    out = np.asarray(img.convert("RGBA")).copy()
    out[..., 3] = af.astype(np.uint8)
    return Image.fromarray(out)


def apply_pen_skips(img: Image.Image, rng: random.Random, *,
                    font_size: float) -> Image.Image:
    """R14 (Track B) — micro-skip de bolígrafo: una bolita sin tinta sobre la
    CRESTA del trazo (máximos del distance transform ≈ centro del trazo).

    El dropout es un dip gaussiano del alpha (deja residuo tenue, como el
    patinazo real de una pluma, no un agujero limpio) con radio ∝ semiancho
    local. CLAMPS de legibilidad: no corre en glifos diminutos (puntuación),
    ni en trazos con semiancho < 1.6 px (los cortaría), y el radio se acota
    a 0.06·font_size. Sin cv2 devuelve el glifo intacto. Determinista desde
    el rng recibido (el caller le pasa uno PROPIO sembrado del contenido)."""
    try:
        import cv2
    except ImportError:
        return img
    a = np.asarray(img.getchannel("A"), dtype=np.uint8)
    h, w = a.shape
    fs = max(8.0, float(font_size))
    if min(h, w) < 0.15 * fs:
        return img          # puntuación/diacríticos: no tocar
    m = (a > 127).astype(np.uint8)
    if m.sum() < 0.004 * fs * fs:
        return img          # tinta insuficiente: un skip la borraría
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    d_max = float(dt.max())
    if d_max < 1.6:
        return img          # trazo demasiado fino: cortaría, no despintaría
    ys, xs = np.nonzero(dt >= max(1.2, 0.55 * d_max))
    if len(xs) < 8:
        return img
    i = rng.randrange(len(xs))
    cx, cy = float(xs[i]), float(ys[i])
    d0 = float(dt[int(cy), int(cx)])
    r = min(0.06 * fs, d0 * rng.uniform(1.3, 2.2))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    dip = 0.82 * np.exp(-d2 / max(1.0, (0.6 * r) ** 2))
    out = np.asarray(img.convert("RGBA")).copy()
    out[..., 3] = np.clip(a.astype(np.float32) * (1.0 - dip),
                          0, 255).astype(np.uint8)
    return Image.fromarray(out)


# ── R15 — tinta en ESPACIO DE TRAZO ─────────────────────────────────────────
# El look impreso del relleno viene de modular un blob plano con campos 2D
# isotrópicos. Estas funciones construyen un campo de ORIENTACIÓN del trazo
# (gradiente del distanceTransform → normal; la tangente es su perpendicular)
# y modulan ancho/densidad/color en coordenadas de trazo. Sin cv2 devuelven
# el glifo intacto (nunca rompen el render).

def _stroke_orientation(alpha_u8: np.ndarray):
    """(m, dt, nx, ny) del glifo: máscara binaria, semiancho local y campo
    normal unitario. El dt se suaviza antes del gradiente: el dt crudo es
    cónico y su gradiente tirita justo en la cresta (donde más importa)."""
    import cv2
    m = (alpha_u8 > 127).astype(np.uint8)
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    dts = cv2.GaussianBlur(dt, (0, 0), 1.2)
    gy, gx = np.gradient(dts)
    n = np.sqrt(gx * gx + gy * gy) + 1e-6
    return m, dt, gx / n, gy / n


def _aniso_noise(s_along: np.ndarray, s_cross: np.ndarray | None,
                 cell_along: float, cell_cross: float,
                 rng: random.Random) -> np.ndarray:
    """Ruido suave en [-1, 1] muestreado en COORDENADAS DE TRAZO.

    Textura tileable 128² (grid 32² interpolado ×4) leída con cv2.remap en
    (s_along/cell_along, s_cross/cell_cross): longitudes de onda distintas
    por eje = anisotropía real, alineada a la tangente aunque el trazo
    curve (s_* son proyecciones locales, continuas sobre el glifo).
    s_cross=None → 1D efectivo (constante cruzando el trazo)."""
    import cv2
    grid = np.array([[rng.uniform(-1.0, 1.0) for _ in range(32)]
                     for _ in range(32)], dtype=np.float32)
    tex = cv2.resize(grid, (128, 128), interpolation=cv2.INTER_CUBIC)
    mapy = ((s_along / max(0.5, cell_along)) * 4.0) % 128
    if s_cross is None:
        mapx = np.zeros_like(s_along)
    else:
        mapx = ((s_cross / max(0.5, cell_cross)) * 4.0) % 128
    return cv2.remap(tex, mapx.astype(np.float32), mapy.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def stroke_width_along(img: Image.Image, rng: random.Random, options,
                       font_size: float) -> Image.Image:
    """Ancho variable A LO LARGO del trazo (R15): dilata donde la pluma fue
    lenta, adelgaza donde fue rápida, simétrico al centro (mezcla hacia el
    MaxFilter/MinFilter del alpha modulada por ruido 1D a lo largo).

    CLAMP por dt: la erosión se anula progresivamente donde el semiancho
    local (dt dilatado) baja de ~2.2 px — trazos finos y puntuación sólo
    pueden ENGROSAR, nunca romperse."""
    wj = min(0.25, max(0.0, getattr(options, "ink_width_along", 0.0)))
    if wj <= 0:
        return img
    try:
        import cv2
    except ImportError:
        return img
    a8 = np.asarray(img.getchannel("A"), dtype=np.uint8)
    h, w = a8.shape
    fs = max(8.0, float(font_size))
    m, dt, nx, ny = _stroke_orientation(a8)
    if m.sum() < 25 or float(dt.max()) < 1.4:
        return img
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    s_along = xx * (-ny) + yy * nx
    n1 = _aniso_noise(s_along, None, 0.5 * fs, 1.0, rng)

    rad = max(1, round(fs * 0.02))
    a_img = Image.fromarray(a8)
    dil = np.asarray(a_img.filter(ImageFilter.MaxFilter(rad * 2 + 1)),
                     dtype=np.float32)
    ero = np.asarray(a_img.filter(ImageFilter.MinFilter(rad * 2 + 1)),
                     dtype=np.float32)
    a = a8.astype(np.float32)
    pos = np.clip(n1, 0.0, 1.0) * wj
    neg = np.clip(-n1, 0.0, 1.0) * wj
    # semiancho local = dt dilatado (vale también en el borde del trazo);
    # sin margen suficiente, la erosión se apaga suave.
    hw = cv2.dilate(dt, np.ones((rad * 2 + 1, rad * 2 + 1), np.uint8))
    neg *= np.clip((hw - 2.2) / 2.0, 0.0, 1.0)
    a = a + (dil - a) * pos - (a - ero) * neg
    out = np.asarray(img.convert("RGBA")).copy()
    out[..., 3] = np.clip(a, 0, 255).astype(np.uint8)
    return Image.fromarray(out)


def stroke_space_shading(img: Image.Image, rng: random.Random, options,
                         font_size: float) -> Image.Image:
    """Densidad/color de pluma en espacio de trazo (R15), sobre el glifo ya
    bordeado: shading 1D a lo largo + textura "riel" anisotrópica + pooling
    donde dt es alto + hue por densidad. SOLO toca el RGB (la geometría y el
    alpha del borde R12 quedan intactos): cero riesgo de cortar trazos."""
    along = min(0.4, max(0.0, getattr(options, "ink_along_darkness", 0.0)))
    streak = min(0.4, max(0.0, getattr(options, "ink_streak_strength", 0.0)))
    pool = min(0.4, max(0.0, getattr(options, "ink_pool_boost", 0.0)))
    hue = min(0.3, max(0.0, getattr(options, "ink_hue_by_density", 0.0)))
    if along <= 0 and streak <= 0 and pool <= 0:
        return img
    try:
        import cv2  # noqa: F401  (lo usan los helpers)
    except ImportError:
        return img
    a8 = np.asarray(img.getchannel("A"), dtype=np.uint8)
    h, w = a8.shape
    fs = max(8.0, float(font_size))
    m, dt, nx, ny = _stroke_orientation(a8)
    if m.sum() < 25:
        return img
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    s_along = xx * (-ny) + yy * nx
    s_cross = xx * nx + yy * ny

    density = np.zeros((h, w), np.float32)
    if along > 0:
        # depósito a lo largo: onda larga (~0.8·em), la carga de la pluma
        # respira por tramos de trazo, no por zona de página.
        density += along * _aniso_noise(s_along, None, 0.8 * fs, 1.0, rng)
    if streak > 0:
        aniso = min(8.0, max(1.0, getattr(options, "ink_streak_aniso", 4.0)))
        cross_cell = max(1.2, 0.03 * fs)
        density += streak * _aniso_noise(s_along, s_cross,
                                         cross_cell * aniso, cross_cell, rng)
    if pool > 0:
        dmax = max(1.0, float(dt.max()))
        density += pool * (dt / dmax) ** 1.5
    density = np.clip(density, -0.85, 0.85)

    rgba = np.asarray(img.convert("RGBA")).astype(np.float32)
    rgb = rgba[..., :3]
    d_pos = np.clip(density, 0.0, None)[..., None]
    d_neg = np.clip(-density, 0.0, None)[..., None]
    # denso = más oscuro (multiplicativo, como el pooling R11); tenue = el
    # color sube hacia el papel (la composición MULTIPLY lo deja pasar).
    rgb = rgb * (1.0 - 0.55 * d_pos) + (255.0 - rgb) * 0.35 * d_neg
    if hue > 0:
        # denso → azul de carga (satura el canal frío); tenue → gris (la
        # tinta rala pierde color antes que luminancia).
        gray = rgb.mean(axis=2, keepdims=True)
        rgb = rgb + (gray - rgb) * (hue * 2.0 * d_neg)
        tint = rgb * np.array([0.82, 0.90, 1.12], np.float32)
        rgb = rgb + (tint - rgb) * (hue * 2.0 * d_pos)
    rgba[..., :3] = np.clip(rgb, 0.0, 255.0)
    return Image.fromarray(rgba.astype(np.uint8))


def apply_paper(ink: Image.Image, paper: Image.Image, options,
                rng: random.Random) -> Image.Image:
    """Compone la capa de tinta (RGBA) sobre el papel (RGB) → página RGB.

    Pipeline: densidad intra-trazo (value noise sobre el alpha, D2) →
    sangrado (blur sub-píxel del alpha, D8) → composición MULTIPLY (D10).
    La identidad ``paper·(1-a) + paper·(tinta/255)·a = paper·(1-a·(1-t))``
    deja UN solo producto de página completa, y todo se opera únicamente
    sobre el bbox con tinta (los márgenes de una hoja son ~40% del área).
    """
    if not PIL_OK:
        return paper
    out = paper.convert("RGB")
    bbox = ink.getbbox()
    if bbox is None:
        return out
    # margen para que el bleed no se corte en el borde del bbox
    pad = int(4 + 2 * max(0.0, getattr(options, "ink_bleed", 0.0)))
    x0 = max(0, bbox[0] - pad)
    y0 = max(0, bbox[1] - pad)
    x1 = min(ink.width, bbox[2] + pad)
    y1 = min(ink.height, bbox[3] + pad)
    region = ink.crop((x0, y0, x1, y1))
    a = np.asarray(region.getchannel("A"), dtype=np.float32) / 255.0

    strength = max(0.0, getattr(options, "ink_texture_strength", 0.0))
    if strength > 0:
        # cell ∝ font_size: la "respiración" va a escala de trazo, y escala
        # sola con el supersampling (font_size ya viene multiplicado).
        cell = max(16, int(options.font_size * 1.2))
        field = value_noise_field(x1 - x0, y1 - y0, rng, cell_px=cell,
                                  lo=1.0 - strength, hi=1.0)
        a *= field

    # R11 — textura intra-trazo (densidad fina + grosor + apozamiento). Gateada
    # por ink_texture_v2; con False, apply_paper queda EXACTO como en R6.
    v2 = bool(getattr(options, "ink_texture_v2", False))
    ink_scale = None
    if v2:
        a, ink_scale = _ink_texture_v2(a, options, rng)

    bleed = max(0.0, getattr(options, "ink_bleed", 0.0))
    if bleed > 0:
        # Halo ADITIVO, no blur destructivo: el GaussianBlur directo resta
        # densidad al núcleo de los trazos finos (1-2 px) y, sumado al value
        # noise y al LANCZOS del supersampling, dejaba la tinta gris pálida.
        # El sangrado real EXPANDE el borde sin despintar el centro:
        # a = max(a, blur(a)·0.85).
        a_img = Image.fromarray((np.clip(a, 0.0, 1.0) * 255).astype(np.uint8))
        a_img = a_img.filter(ImageFilter.GaussianBlur(bleed))
        a_blur = np.asarray(a_img, dtype=np.float32) / 255.0
        halo = a_blur * 0.85
        # R11 — borde irregular: modular el halo con ruido para que la tinta
        # feathee desigual hacia el papel (un borde matemáticamente limpio
        # delata la impresión). 0 = halo uniforme de R6.
        edge = max(0.0, getattr(options, "ink_edge_irregularity", 0.0))
        if v2 and edge > 0:
            nfield = value_noise_field(x1 - x0, y1 - y0, rng,
                                       cell_px=max(3, int(options.font_size * 0.12)),
                                       lo=1.0 - edge, hi=1.0)
            halo = halo * nfield
        np.maximum(a, halo, out=a)

    # R15 — showthrough: la tinta real nunca es 100% opaca sobre fibra; un
    # cap del alpha efectivo deja pasar esa fracción del grano del papel
    # BAJO el trazo (solo recorta el interior saturado; los bordes y trazos
    # tenues quedan como están). Gateado por el master de R15.
    if bool(getattr(options, "ink_stroke_space", False)):
        st = min(0.2, max(0.0, getattr(options, "ink_paper_showthrough", 0.0)))
        if st > 0:
            np.minimum(a, 1.0 - st, out=a)

    p = np.asarray(out.crop((x0, y0, x1, y1)), dtype=np.float32)
    t = np.asarray(region.convert("RGB"), dtype=np.float32) / 255.0
    if ink_scale is not None:
        # R11: la densidad intra-trazo y el apozamiento se modelan en el COLOR
        # de tinta (factor MULTIPLY): <1 más oscuro (pool), >1 más claro (dry).
        # Clip a [0,1] porque el campo fino puede pasar de 1.0 (zonas secas).
        t = np.clip(t * ink_scale[..., None], 0.0, 1.0)
    np.subtract(1.0, t, out=t)
    t *= a[..., None]
    np.subtract(1.0, t, out=t)
    p *= t
    out.paste(Image.fromarray(np.clip(p, 0.0, 255.0).astype(np.uint8)),
              (x0, y0))
    return out

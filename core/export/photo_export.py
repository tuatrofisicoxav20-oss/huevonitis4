"""Export "📷 Foto de tarea" (Fase R7 — F4/F2/I4; v2 en R14 Track C).

Una página renderizada perfecta delata su origen digital. Este export la hace
pasar por una FOTO de celular de la hoja: iluminación direccional (nadie
fotografía con luz perfectamente pareja), viñeta suave de lente, grano
gaussiano leve del sensor, y JPEG q=85 a resolución típica de cámara de
teléfono (~3000 px el lado largo) — los artefactos de compresión son parte
del disfraz.

R14 (Track C) — v2: los tells que quedaban eran de CAPTURA, no de tinta. Una
foto de tarea real muestra la hoja APOYADA en un escritorio (margen de fondo +
sombra de contacto), con perspectiva imperfecta (keystone), luz cálida de
interior, alguna sombra local (mano/teléfono), foco desparejo y ruido ISO
correlacionado. Todo va detrás de kwargs con defaults PLANOS: sin pasarlos,
la foto es byte-idéntica a la de R7 (rollback total, regla dura #2).

Determinista: todo el ruido sale del rng inyectado (regla del proyecto). Los
efectos nuevos consumen RNG SOLO cuando están activos, así los defaults no
corren el stream. El skew de la hoja NO se aplica aquí: es parte del render
(scan_skew en RenderOptions); el caller renderiza con esa opción y exporta.
"""
from __future__ import annotations

import colorsys
import logging
import random
from pathlib import Path

import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFilter
    PIL_OK = True
except ImportError:
    PIL_OK = False

logger = logging.getLogger(__name__)

PHOTO_LONG_SIDE = 3000
PHOTO_JPEG_QUALITY = 85


def _illumination_field(w: int, h: int, rng: random.Random) -> np.ndarray:
    """Gradiente de luz direccional + viñeta de lente, en [≈0.86, ≈1.06].

    La dirección de la luz es aleatoria (ventana/lámpara en cualquier lado);
    la viñeta oscurece esquinas como una lente real de celular.
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xx /= max(1, w - 1)
    yy /= max(1, h - 1)

    ang = rng.uniform(0.0, 2.0 * np.pi)
    # Proyección sobre la dirección de la luz, centrada: [-0.5, 0.5]
    proj = (xx - 0.5) * np.cos(ang) + (yy - 0.5) * np.sin(ang)
    strength = rng.uniform(0.05, 0.09)
    light = 1.0 + proj * 2.0 * strength  # ±strength extremo a extremo

    # Viñeta: caída radial suave hacia las esquinas (hasta -8%).
    r2 = (xx - 0.5) ** 2 + (yy - 0.5) ** 2   # 0 centro, 0.5 esquina
    vignette = 1.0 - (r2 / 0.5) * rng.uniform(0.05, 0.08)

    return light * vignette


def _shadow_blob_field(w: int, h: int, rng: random.Random,
                       strength: float) -> np.ndarray:
    """Sombra LOCAL de baja frecuencia (mano/teléfono entre la luz y la hoja).

    El campo de R7 es global y suave; una foto real casi siempre tiene además
    una mancha de sombra blanda en alguna zona. Gaussiana 2D con centro,
    radio y profundidad sorteados; multiplicador en (1-strength, 1].
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xx /= max(1, w - 1)
    yy /= max(1, h - 1)
    cx = rng.uniform(0.15, 0.85)
    cy = rng.uniform(0.15, 0.85)
    rad = rng.uniform(0.22, 0.42)          # radio como fracción del lado
    depth = strength * rng.uniform(0.65, 1.0)
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    return 1.0 - depth * np.exp(-d2 / (2.0 * rad * rad))


def _upsample_noise(np_rng, w: int, h: int, cell: int,
                    sigma: float) -> np.ndarray:
    """Ruido gaussiano CORRELACIONADO: grid grueso (~cell px por celda)
    interpolado BICUBIC al tamaño final. El ruido ISO real de un sensor +
    demosaico no es blanco por píxel: tiene granos de varios px."""
    gw = max(2, w // max(2, cell))
    gh = max(2, h // max(2, cell))
    grid = np_rng.normal(0.0, sigma, size=(gh, gw)).astype(np.float32)
    img = Image.fromarray(grid, mode="F").resize((w, h), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32)


def _procedural_desk(w: int, h: int, rng: random.Random) -> Image.Image:
    """Superficie de escritorio procedural: tono madera/mesa con veta suave.

    Base HSV cálida sorteada + value-noise de baja frecuencia + veta fina
    estirada en X (grano de madera). Suficiente para el margen de fondo de
    una foto de tarea (queda mayormente en sombra/desenfoque perceptual)."""
    np_rng = np.random.default_rng(rng.getrandbits(32))
    hue = rng.uniform(0.05, 0.10)
    sat = rng.uniform(0.28, 0.52)
    val = rng.uniform(0.30, 0.52)
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    base = np.array([r, g, b], dtype=np.float32) * 255.0

    # Mancha de tono de baja frecuencia (la mesa no es de color plano).
    low = _upsample_noise(np_rng, w, h, cell=max(32, min(w, h) // 6), sigma=1.0)
    # Veta: grid alto y angosto → al estirarlo queda un grano alargado en X.
    gw = max(2, w // max(2, min(w, h) // 3))
    gh = max(2, h // 14)
    grain_grid = np_rng.normal(0.0, 1.0, size=(gh, gw)).astype(np.float32)
    grain = np.asarray(Image.fromarray(grain_grid, mode="F")
                       .resize((w, h), Image.BICUBIC), dtype=np.float32)
    tone = 1.0 + 0.05 * np.clip(low, -2.0, 2.0) + 0.03 * np.clip(grain, -2.0, 2.0)
    arr = base[None, None, :] * tone[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _load_desk(desk_background, w: int, h: int,
               rng: random.Random) -> Image.Image:
    """Escritorio para el fondo: "procedural" (o path inexistente) → sintético;
    path a imagen → cover-resize + crop centrado al tamaño pedido."""
    if isinstance(desk_background, (str, Path)) and str(desk_background) != "procedural":
        p = Path(desk_background)
        if p.exists():
            try:
                desk = Image.open(p).convert("RGB")
                s = max(w / desk.width, h / desk.height)
                desk = desk.resize((max(w, round(desk.width * s)),
                                    max(h, round(desk.height * s))),
                                   Image.LANCZOS)
                x0 = (desk.width - w) // 2
                y0 = (desk.height - h) // 2
                return desk.crop((x0, y0, x0 + w, y0 + h))
            except Exception as exc:
                logger.warning("desk_background %s ilegible (%s); procedural", p, exc)
    return _procedural_desk(w, h, rng)


def _compose_desk(img: Image.Image, rng: random.Random, desk_background,
                  margin_frac: float) -> Image.Image:
    """Apoya la hoja sobre un escritorio: margen de fondo visible, SOMBRA DE
    CONTACTO suave desplazada (la hoja flota fracciones de mm sobre la mesa)
    y una leve sombra de borde sobre la propia hoja (no es perfectamente
    plana). El margen es chico: una foto de tarea encuadra la hoja."""
    m = max(8, round(min(img.size) * margin_frac))
    W, H = img.width + 2 * m, img.height + 2 * m
    desk = _load_desk(desk_background, W, H, rng)

    # Sombra de contacto: rectángulo de la hoja, apenas crecido y desplazado
    # (la luz nunca cae perfectamente cenital), con blur ancho.
    dx = rng.uniform(-0.30, 0.30) * m
    dy = rng.uniform(0.10, 0.45) * m
    grow = m * 0.12
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).rectangle(
        [m + dx - grow, m + dy - grow,
         m + img.width + dx + grow, m + img.height + dy + grow], fill=255)
    sh = sh.filter(ImageFilter.GaussianBlur(m * 0.30))
    darr = np.asarray(desk, dtype=np.float32)
    darr *= 1.0 - (np.asarray(sh, dtype=np.float32) / 255.0)[..., None] * 0.42
    desk = Image.fromarray(np.clip(darr, 0, 255).astype(np.uint8))

    # Sombra de borde de la hoja: las orillas se oscurecen ~4% con rampa corta
    # (el papel se curva mínimamente y deja de mirar de frente a la luz).
    e = max(2.0, min(img.size) * 0.012)
    fx = np.minimum(np.arange(img.width, dtype=np.float32),
                    np.arange(img.width, dtype=np.float32)[::-1]) / e
    fy = np.minimum(np.arange(img.height, dtype=np.float32),
                    np.arange(img.height, dtype=np.float32)[::-1]) / e
    ramp = np.minimum(np.clip(fx, 0.0, 1.0)[None, :],
                      np.clip(fy, 0.0, 1.0)[:, None])
    sarr = np.asarray(img, dtype=np.float32) * (0.96 + 0.04 * ramp)[..., None]
    sheet = Image.fromarray(np.clip(sarr, 0, 255).astype(np.uint8))

    desk.paste(sheet, (m, m))
    return desk


def _persp_coeffs(dst_pts, src_pts) -> list[float]:
    """Coeficientes PERSPECTIVE de PIL que mandan src_pts → dst_pts.

    PIL evalúa la homografía del REVÉS (por cada píxel de salida busca su
    origen), por eso el sistema se arma con (dst → src)."""
    mat = []
    for (x, y), (X, Y) in zip(dst_pts, src_pts, strict=True):
        mat.append([x, y, 1, 0, 0, 0, -X * x, -X * y])
        mat.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
    a = np.asarray(mat, dtype=np.float64)
    b = np.asarray(src_pts, dtype=np.float64).reshape(8)
    return list(np.linalg.solve(a, b))


def _apply_keystone(img: Image.Image, rng: random.Random,
                    strength: float) -> Image.Image:
    """Perspectiva imperfecta de cámara: cada esquina se desplaza hasta
    ±strength del lado correspondiente (una foto de mano nunca deja la hoja
    como rectángulo perfecto). El fondo expuesto se rellena con el color
    mediano del borde (papel o escritorio, lo que haya)."""
    w, h = img.size
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [(x + rng.uniform(-strength, strength) * w,
            y + rng.uniform(-strength, strength) * h) for x, y in src]
    arr = np.asarray(img)
    border = np.concatenate([arr[0].reshape(-1, 3), arr[-1].reshape(-1, 3),
                             arr[:, 0].reshape(-1, 3), arr[:, -1].reshape(-1, 3)])
    fill = tuple(int(v) for v in np.median(border, axis=0))
    coeffs = _persp_coeffs(dst, src)
    return img.transform((w, h), Image.PERSPECTIVE, coeffs,
                         resample=Image.BICUBIC, fillcolor=fill)


def _scale_channel(ch: Image.Image, factor: float) -> Image.Image:
    """Escala un canal alrededor del centro conservando el tamaño del lienzo
    (aberración cromática: la lente magnifica R y B distinto que G)."""
    w, h = ch.size
    nw = max(1, round(w * factor))
    nh = max(1, round(h * factor))
    scaled = ch.resize((nw, nh), Image.BICUBIC)
    if factor >= 1.0:
        x0 = (nw - w) // 2
        y0 = (nh - h) // 2
        return scaled.crop((x0, y0, x0 + w, y0 + h))
    out = ch.copy()
    out.paste(scaled, ((w - nw) // 2, (h - nh) // 2))
    return out


def export_photo(page: Image.Image, path: str | Path,
                 rng: random.Random | None = None,
                 long_side: int = PHOTO_LONG_SIDE,
                 quality: int = PHOTO_JPEG_QUALITY, *,
                 keystone_strength: float = 0.0,
                 desk_background: str | Path | None = None,
                 desk_margin_frac: float = 0.045,
                 wb_warmth: float = 0.0,
                 shadow_blob: float = 0.0,
                 focus_gradient: float = 0.0,
                 motion_blur: float = 0.0,
                 iso_noise: float = 0.0,
                 chromatic_aberration: float = 0.0,
                 quality_range: tuple[int, int] | None = None) -> Path:
    """Guarda una página como JPEG estilo "foto de celular". Devuelve el path.

    R14 (Track C) — efectos nuevos, todos OPT-IN (defaults planos = foto R7
    byte-idéntica; consumen RNG sólo si están activos):

      keystone_strength: desplazamiento máx de cada esquina como fracción del
        lado (homografía). Tell que ataca: hoja-rectángulo-perfecto. Rango
        útil 0.008-0.02; clamp 0.04 (más ya se ve "escaneo torcido", no foto).
      desk_background: None = sin fondo; "procedural" = mesa sintética; path
        = foto de mesa del usuario. Compone la hoja con sombra de contacto y
        margen de escritorio (tell: la hoja "flota" en la nada).
      desk_margin_frac: margen de escritorio visible como fracción del lado
        menor (clamp 0.02-0.12: una foto de tarea encuadra la hoja).
      wb_warmth: ganancia RGB cálida 0..0.15 (luz interior; el auto-WB del
        teléfono nunca corrige del todo).
      shadow_blob: profundidad 0..0.35 de una sombra local blanda (mano o
        teléfono) además de la viñeta global (tell: luz demasiado limpia).
      focus_gradient: σ máx (px) del desenfoque hacia UNA esquina sorteada
        0..6 (clamp): plano focal nunca perfectamente paralelo a la hoja.
      motion_blur: largo (px) de un blur lineal muy leve 0..6 (pulso).
        Necesita cv2; sin cv2 se omite con log (nunca rompe el export).
      iso_noise: σ extra (niveles de 8 bits) de ruido CORRELACIONADO en luma
        + croma (grano de varios px, como ISO alto real). 0..4. El grano
        fino por píxel de R7 sigue corriendo siempre (no se toca).
      chromatic_aberration: magnificación relativa de R vs B (0..0.003):
        franjas sub-píxel de color en bordes de alto contraste.
      quality_range: (lo, hi) → la calidad JPEG se sortea uniforme en ese
        rango (q∈[82,88] típico de galería/WhatsApp); None = `quality` fijo.
    """
    if not PIL_OK:
        raise RuntimeError("Pillow no disponible para exportar foto")
    rng = rng or random.Random()
    path = Path(path)

    img = page.convert("RGB")
    # Resolución de cámara de teléfono: lado largo ~3000 px.
    scale = long_side / max(img.size)
    if abs(scale - 1.0) > 0.01:
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)

    # R14 — escena: primero la hoja se apoya en el escritorio, después la
    # cámara la mira con perspectiva imperfecta (el keystone deforma la
    # ESCENA completa, hoja y fondo juntos, como una cámara real).
    if desk_background is not None:
        img = _compose_desk(img, rng, desk_background,
                            min(0.12, max(0.02, desk_margin_frac)))
    ks = min(0.04, max(0.0, keystone_strength))
    if ks > 0:
        img = _apply_keystone(img, rng, ks)

    arr = np.asarray(img, dtype=np.float32)
    field = _illumination_field(img.width, img.height, rng)
    blob = min(0.35, max(0.0, shadow_blob))
    if blob > 0:
        field = field * _shadow_blob_field(img.width, img.height, rng, blob)
    arr *= field[..., None]

    warm = min(0.15, max(0.0, wb_warmth))
    if warm > 0:
        # Luz cálida de interior: sube R (y apenas G), baja B. Ganancia por
        # canal, como el WB del sensor — no un overlay.
        arr[..., 0] *= 1.0 + 0.9 * warm
        arr[..., 1] *= 1.0 + 0.25 * warm
        arr[..., 2] *= 1.0 - 0.9 * warm

    # Efectos de LENTE (foco/pulso/aberración): operan a nivel imagen. Sólo
    # se paga el round-trip a uint8 si alguno está activo.
    fg = min(6.0, max(0.0, focus_gradient))
    mb = min(6.0, max(0.0, motion_blur))
    ca = min(0.003, max(0.0, chromatic_aberration))
    if fg > 0 or mb > 0 or ca > 0:
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        if fg > 0:
            # Gradiente de foco: nítido en una esquina sorteada, más suave
            # hacia la opuesta (el plano focal nunca es paralelo a la hoja).
            corner = rng.randrange(4)
            cx = float(corner in (1, 2))
            cy = float(corner >= 2)
            blurred = img.filter(ImageFilter.GaussianBlur(fg))
            yy, xx = np.mgrid[0:img.height, 0:img.width].astype(np.float32)
            xx /= max(1, img.width - 1)
            yy /= max(1, img.height - 1)
            wgt = (((xx - cx) ** 2 + (yy - cy) ** 2) / 2.0)[..., None]
            a0 = np.asarray(img, dtype=np.float32)
            a1 = np.asarray(blurred, dtype=np.float32)
            img = Image.fromarray(np.clip(a0 * (1.0 - wgt) + a1 * wgt,
                                          0, 255).astype(np.uint8))
        if mb > 0:
            try:
                import cv2
                length = max(3, round(mb) | 1)
                ang = rng.uniform(0.0, np.pi)
                kern = np.zeros((length, length), np.float32)
                c = length // 2
                dx = round(float(np.cos(ang)) * c)
                dy = round(float(np.sin(ang)) * c)
                cv2.line(kern, (c - dx, c - dy), (c + dx, c + dy), 1.0, 1)
                kern /= max(1.0, kern.sum())
                img = Image.fromarray(
                    cv2.filter2D(np.asarray(img), -1, kern))
            except ImportError:
                logger.debug("motion_blur pedido pero cv2 no está; se omite")
        if ca > 0:
            r, g, b = img.split()
            img = Image.merge("RGB", (_scale_channel(r, 1.0 + ca), g,
                                      _scale_channel(b, 1.0 - ca)))
        arr = np.asarray(img, dtype=np.float32)

    # Grano del sensor: gaussiano leve por píxel. Generador numpy seedeado
    # desde el rng inyectado (determinismo sin pagar el loop Python).
    np_rng = np.random.default_rng(rng.getrandbits(32))
    arr += np_rng.normal(0.0, 2.2, size=arr.shape).astype(np.float32)

    iso = min(4.0, max(0.0, iso_noise))
    if iso > 0:
        # Ruido ISO correlacionado: luma en granos de ~3 px + croma más
        # gruesa y suave (el demosaico mancha el color en parches).
        h_, w_ = arr.shape[:2]
        luma = _upsample_noise(np_rng, w_, h_, cell=3, sigma=iso)
        arr += luma[..., None]
        for c in range(3):
            arr[..., c] += _upsample_noise(np_rng, w_, h_, cell=7,
                                           sigma=iso * 0.6)

    if quality_range is not None:
        lo, hi = int(quality_range[0]), int(quality_range[1])
        quality = rng.randint(min(lo, hi), max(lo, hi))

    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, "JPEG", quality=quality, optimize=True)
    return path


def export_photo_pages(pages: list, base_path: str | Path,
                       rng: random.Random | None = None,
                       **photo_kwargs) -> list[Path]:
    """Exporta N páginas como fotos: base.jpg o base_p1.jpg, base_p2.jpg…

    Los kwargs nuevos de R14 (keystone_strength, desk_background, …) se
    reenvían tal cual a export_photo; cada página sortea su propia
    realización (mismo rng compartido → el "estilo" de sesión se hereda)."""
    rng = rng or random.Random()
    base = Path(base_path)
    stem = base.with_suffix("")
    paths: list[Path] = []
    for i, page in enumerate(pages, start=1):
        out = base if len(pages) == 1 else Path(f"{stem}_p{i}.jpg")
        paths.append(export_photo(page, out.with_suffix(".jpg"), rng,
                                  **photo_kwargs))
    return paths

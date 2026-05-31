"""Hashing perceptual del banco de glifos (extraído de bank.py en v4.2).

Estas funciones viven aparte para mantener bank.py por debajo de ~420 líneas.
bank.py las re-importa, así que `from core.inkcore.bank import _dhash` (y el
resto) sigue funcionando igual que antes — los tests dependen de eso.
"""

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


def _glyph_to_gray(img: "Image.Image") -> "Image.Image":
    """Devuelve el glifo como imagen 'L' con trazo OSCURO sobre fondo CLARO.

    La forma de un glifo puede estar codificada de dos maneras distintas:

      • Glifos del extractor: tinta BLANCA (RGB=255) sobre transparente, con la
        forma viviendo enteramente en el canal alpha (así se ven sobre el fondo
        oscuro de la UI). Pegarlos sobre blanco da una imagen 100% blanca → el
        hash colapsa a un valor degenerado (todo ceros) y el dedup rechaza TODO.
      • Glifos opacos (bulk/legacy): tinta oscura en RGB con alpha=255.

    Elegimos el canal con SEÑAL REAL (mayor rango dinámico) entre el alpha y la
    luminancia invertida, en vez de adivinar por un umbral de alpha. El criterio
    viejo (alpha.min() < 250 → usa alpha) fallaba para un glifo del extractor sin
    zonas transparentes (alpha uniforme 255): caía en la rama de luminancia, y
    como su RGB es blanco uniforme daba presencia 0 → imagen toda blanca → hash
    degenerado → dedup colapsado otra vez. Comparar el rango de cada candidato
    funciona en ambos formatos y nunca elige un canal plano si el otro tiene forma.
    """
    import numpy as _np
    arr = _np.asarray(img.convert("RGBA"), dtype=_np.float32)
    alpha = arr[:, :, 3]
    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    cand_alpha = alpha / 255.0                 # forma en alpha (extractor)
    cand_lum = 1.0 - lum / 255.0               # forma en luminancia (opaco)
    spread_alpha = float(cand_alpha.max() - cand_alpha.min())
    spread_lum = float(cand_lum.max() - cand_lum.min())
    presence = cand_alpha if spread_alpha >= spread_lum else cand_lum
    gray = ((1.0 - presence) * 255.0).clip(0, 255).astype(_np.uint8)
    return Image.fromarray(gray)  # array 2D uint8 → modo "L"


def _avg_hash(img: "Image.Image", size: int = 16) -> str:
    """Hash promedio (legacy). Mantenido como fallback; usa _glyph_to_gray ahora."""
    import numpy as _np
    gray = _glyph_to_gray(img).resize((size, size), Image.Resampling.LANCZOS)
    arr = _np.asarray(gray, dtype=_np.uint8)
    avg = float(arr.mean())
    bits = (arr > avg).flatten()
    return "".join("1" if b else "0" for b in bits)


def _dhash(img: "Image.Image", size: int = 16) -> str:
    """Difference hash — más estable que avg_hash frente a cambios de brillo.

    Compara cada píxel con su vecino derecho. Más discriminativo entre glifos
    visualmente distintos del mismo carácter.
    """
    import numpy as _np
    gray = _glyph_to_gray(img).resize((size + 1, size), Image.Resampling.LANCZOS)
    arr = _np.asarray(gray, dtype=_np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    return "".join("1" if b else "0" for b in diff.flatten())


def _hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b, strict=False)) + abs(len(a) - len(b))


def _dup_thresholds(ch: str) -> tuple[int, int]:
    if ch in ".,;:!¡?¿|'`":
        return 3, 7
    if ch in "iltI1íì":
        return 5, 10
    if ch in "mwMW":
        return 9, 16
    return 7, 13

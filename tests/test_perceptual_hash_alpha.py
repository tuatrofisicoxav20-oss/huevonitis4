"""Test de regresión del bug histórico del perceptual hash de glifos.

Bug original: los glifos del extractor son tinta BLANCA (RGB=255) con la forma
viviendo SOLO en el canal alpha. Si el hashing descarta el alpha y pega sobre
blanco, la imagen queda 100% blanca → el hash colapsa a un valor degenerado
(todos los bits iguales) y el dedup toma glifos distintos como duplicados.

Este test construye 3 glifos visualmente diferentes EN ESE FORMATO (el que
disparaba el bug), calcula su _dhash canónico (y _avg_hash de paso) y verifica
que NO sean degenerados ni iguales. El repo no versiona un banco real con PNGs,
así que se sintetizan glifos en el formato exacto del extractor.

Si los 3 hashes salen idénticos o all-ones/all-zeros → el bug sigue vivo.
"""

import pytest

from core.inkcore.bank_hashing import _avg_hash, _dhash

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


def _glyph_alpha(draw_shape) -> Image.Image:
    """Glifo en formato extractor: RGB blanco uniforme, forma en el canal alpha."""
    size = 64
    rgb = Image.new("RGB", (size, size), (255, 255, 255))      # tinta blanca
    alpha = Image.new("L", (size, size), 0)                    # todo transparente
    draw_shape(ImageDraw.Draw(alpha))                          # dibuja la forma en alpha (255)
    rgb.putalpha(alpha)
    return rgb  # RGBA, forma SOLO en alpha


def _is_degenerate(h: str) -> bool:
    return not h or h.count("0") == len(h) or h.count("1") == len(h)


# 3 formas claramente distintas
def _shape_T(d):  # barra vertical + horizontal
    d.rectangle([28, 8, 36, 56], fill=255)
    d.rectangle([12, 8, 52, 16], fill=255)


def _shape_O(d):  # anillo
    d.ellipse([10, 10, 54, 54], fill=255)
    d.ellipse([22, 22, 42, 42], fill=0)


def _shape_diag(d):  # diagonal gruesa
    d.line([10, 54, 54, 10], fill=255, width=10)


def test_perceptual_hash_no_degenera_ni_colapsa_con_forma_en_alpha(capsys):
    glyphs = {
        "T": _glyph_alpha(_shape_T),
        "O": _glyph_alpha(_shape_O),
        "/": _glyph_alpha(_shape_diag),
    }

    dhashes = {name: _dhash(img.convert("RGBA")) for name, img in glyphs.items()}
    ahashes = {name: _avg_hash(img.convert("RGBA")) for name, img in glyphs.items()}

    print("\n=== _dhash (canónico, el que usa el banco) ===")
    for name, h in dhashes.items():
        print(f"  {name!r}: ones={h.count('1'):>3}/{len(h)}  {h}")
    print("=== _avg_hash (legacy/fallback) ===")
    for name, h in ahashes.items():
        print(f"  {name!r}: ones={h.count('1'):>3}/{len(h)}  {h}")

    # 1) Ninguno degenerado (all-zeros o all-ones) → el bug haría all-iguales.
    for name, h in dhashes.items():
        assert not _is_degenerate(h), f"_dhash de {name!r} degenerado (BUG VIVO): {h}"
    # 2) Los 3 son distintos entre sí (no colapsan al mismo valor).
    assert len(set(dhashes.values())) == 3, f"_dhash colapsó (BUG VIVO): {dhashes}"

    with capsys.disabled():
        pass  # los prints quedan visibles con -s

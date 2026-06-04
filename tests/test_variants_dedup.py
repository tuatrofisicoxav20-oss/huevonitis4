"""Fase 5 — variantes por glifo + comportamiento del dedup.

Bloquea el hallazgo medido: el dedup NO se come variantes genuinamente distintas
(formas diferentes del mismo char entran todas), pero SÍ rechaza casi-idénticos.
Y `variant_distribution()` cuenta bien las variantes por carácter.
"""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PIL") is None, reason="Pillow no instalado"
)


def _make_alpha_glyph(path: Path, shape: str = "ellipse", px: int = 48) -> bool:
    """Glifo estilo-extractor: forma en el canal alpha (RGB blanco). Cada forma
    produce un hash perceptual distinto."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (px, px), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    ink = (255, 255, 255, 255)
    if shape == "ellipse":
        d.ellipse([8, 8, px - 8, px - 8], outline=ink, width=4)
    elif shape == "rect":
        d.rectangle([6, 12, px - 6, px - 12], outline=ink, width=4)
    elif shape == "line":
        d.line([4, 4, px - 4, px - 4], fill=ink, width=5)
    elif shape == "cross":
        d.line([px // 2, 4, px // 2, px - 4], fill=ink, width=4)
        d.line([4, px // 2, px - 4, px // 2], fill=ink, width=4)
    img.save(path)
    return True


@pytest.fixture
def bank():
    from core.inkcore.bank import GlyphBank
    return GlyphBank()


def test_variantes_distintas_no_se_rechazan(bank, tmp_path):
    """Cuatro formas distintas del MISMO char deben entrar todas (el dedup no se
    come variantes legítimas con el umbral strict actual)."""
    kept = 0
    for shape in ("ellipse", "rect", "line", "cross"):
        p = tmp_path / f"e_{shape}.png"
        _make_alpha_glyph(p, shape)
        if bank.add_glyph("e", str(p)) is not None:
            kept += 1
    assert kept == 4, f"el dedup se comió variantes distintas (entraron {kept}/4)"
    assert bank.variant_distribution()["e"] == 4


def test_casi_identico_si_se_rechaza(bank, tmp_path):
    """Una copia byte-a-byte del mismo glifo CON forma sí se deduplica."""
    p1 = tmp_path / "a1.png"
    _make_alpha_glyph(p1, "ellipse")
    p2 = tmp_path / "a2.png"
    shutil.copy2(p1, p2)
    assert bank.add_glyph("a", str(p1)) is not None
    assert bank.add_glyph("a", str(p2)) is None  # casi-idéntico → rechazado
    assert bank.variant_distribution()["a"] == 1


def test_variant_distribution_cuenta_y_filtra_por_tier(bank, tmp_path):
    """variant_distribution agrega por char y respeta tier_filter."""
    for shape in ("ellipse", "rect", "line"):
        p = tmp_path / f"o_{shape}.png"
        _make_alpha_glyph(p, shape)
        bank.add_glyph("o", str(p))
    p = tmp_path / "x_e.png"
    _make_alpha_glyph(p, "cross")
    bank.add_glyph("x", str(p))

    dist = bank.variant_distribution()
    assert dist.get("o") == 3
    assert dist.get("x") == 1
    # Ordenado por frecuencia descendente.
    assert next(iter(dist.keys())) == "o"

    # tier_filter: contar solo un tier no debe exceder el total.
    only_gold = bank.variant_distribution(tier_filter="Gold")
    assert only_gold.get("o", 0) <= 3


def test_variant_distribution_banco_vacio(bank):
    assert bank.variant_distribution() == {}

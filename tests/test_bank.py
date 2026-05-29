"""Tests for GlyphBank: add/dedup/remove/reload with tmp_path."""
import shutil
from pathlib import Path

import pytest


def _make_test_png(path: Path, px: int = 20):
    """Create a tiny solid-white RGBA PNG for testing."""
    try:
        from PIL import Image
        img = Image.new("RGBA", (px, px), (0, 0, 0, 255))
        img.save(path)
        return True
    except ImportError:
        return False


@pytest.fixture
def bank(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    return GlyphBank()


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_add_glyph(bank, tmp_path):
    src = tmp_path / "glyph.png"
    if not _make_test_png(src):
        pytest.skip("PIL not available")
    entry = bank.add_glyph("a", str(src))
    assert entry is not None
    assert entry.char == "a"
    assert Path(entry.image_path).exists()


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_add_and_reload(bank, tmp_path):
    src = tmp_path / "glyph_b.png"
    if not _make_test_png(src):
        pytest.skip("PIL not available")
    bank.add_glyph("b", str(src))
    from core.inkcore.bank import GlyphBank
    bank2 = GlyphBank()
    entries = bank2.get_all(char_filter="b")
    assert len(entries) >= 1
    assert entries[0].char == "b"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_remove_glyph(bank, tmp_path):
    src = tmp_path / "glyph_c.png"
    if not _make_test_png(src):
        pytest.skip("PIL not available")
    entry = bank.add_glyph("c", str(src))
    assert entry is not None
    bank.remove_glyph(entry)
    entries = bank.get_all(char_filter="c")
    assert len(entries) == 0
    assert not Path(entry.image_path).exists()


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_dedup_identical_images(bank, tmp_path):
    """Adding the same image twice should be deduplicated."""
    src1 = tmp_path / "dup1.png"
    src2 = tmp_path / "dup2.png"
    if not _make_test_png(src1, px=30):
        pytest.skip("PIL not available")
    shutil.copy2(src1, src2)
    bank.add_glyph("d", str(src1))
    result2 = bank.add_glyph("d", str(src2))
    # Identical images should be rejected as duplicates
    assert result2 is None


def _make_alpha_glyph(path: Path, shape: str = "ellipse", px: int = 48):
    """Crea un glifo estilo-extractor: tinta BLANCA con la forma en el alpha.

    Reproduce el formato real que rompía el dedup: RGB=255 en toda la imagen,
    forma codificada solo en el canal alpha (0=fondo, 255=trazo).
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    img = Image.new("RGBA", (px, px), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    ink = (255, 255, 255, 255)
    if shape == "ellipse":
        d.ellipse([8, 8, px - 8, px - 8], outline=ink, width=4)
    elif shape == "rect":
        d.rectangle([6, 12, px - 6, px - 12], outline=ink, width=4)
    elif shape == "line":
        d.line([4, 4, px - 4, px - 4], fill=ink, width=5)
    img.save(path)
    return True


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_dhash_not_degenerate_for_alpha_ink(tmp_path):
    """El glifo del extractor (tinta en alpha) debe producir un hash con señal.

    Regresión del bug: _flatten_rgba pegaba RGB blanco sobre blanco → imagen
    toda blanca → _dhash todo ceros → el dedup rechazaba todo.
    """
    from PIL import Image

    from core.inkcore.bank import _dhash
    p = tmp_path / "ell.png"
    assert _make_alpha_glyph(p, "ellipse")
    h = _dhash(Image.open(p).convert("RGBA"))
    assert set(h) != {"0"}, "el hash colapsó a todo ceros (bug del dedup)"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_distinct_alpha_glyphs_accepted(bank, tmp_path):
    """Dos muestras VISUALMENTE distintas del mismo char deben aceptarse ambas.

    Antes del fix la segunda se rechazaba con hamming=0 (todos los hashes eran
    iguales), impidiendo acumular muestras en el banco.
    """
    p1, p2 = tmp_path / "g1.png", tmp_path / "g2.png"
    if not _make_alpha_glyph(p1, "ellipse"):
        pytest.skip("PIL not available")
    _make_alpha_glyph(p2, "rect")
    r1 = bank.add_glyph("a", str(p1))
    r2 = bank.add_glyph("a", str(p2))
    assert r1 is not None
    assert r2 is not None
    assert len(bank.get_all(char_filter="a")) == 2


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed"
)
def test_backfill_recomputes_degenerate_hash(bank, tmp_path):
    """Un hash degenerado ('000…0') guardado por el _dhash roto debe sanearse al load."""
    p = tmp_path / "g.png"
    if not _make_alpha_glyph(p, "ellipse"):
        pytest.skip("PIL not available")
    entry = bank.add_glyph("a", str(p))
    assert entry is not None
    entry.perceptual_hash = "0" * 256
    bank.save()
    from core.inkcore.bank import GlyphBank
    bank2 = GlyphBank()
    e2 = bank2.get_all(char_filter="a")[0]
    assert set(e2.perceptual_hash) != {"0"}, "el backfill no recomputó el hash degenerado"


def test_coverage_empty(bank):
    cov = bank.coverage()
    assert cov["total_glyphs"] == 0
    assert cov["unique_chars"] == 0


def test_bank_manifest_written(bank, tmp_path):
    import config
    # v4.2: el manifest vive en tipografia/{profile_id}/_manifest.json
    manifest = config.TIPOGRAFIA_DIR / config.DEFAULT_PROFILE_ID / "_manifest.json"
    assert manifest.exists()

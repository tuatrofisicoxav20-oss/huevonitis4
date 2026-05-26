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


def test_coverage_empty(bank):
    cov = bank.coverage()
    assert cov["total_glyphs"] == 0
    assert cov["unique_chars"] == 0


def test_bank_manifest_written(bank, tmp_path):
    import config
    # v4.2: el manifest vive en tipografia/{profile_id}/_manifest.json
    manifest = config.TIPOGRAFIA_DIR / config.DEFAULT_PROFILE_ID / "_manifest.json"
    assert manifest.exists()

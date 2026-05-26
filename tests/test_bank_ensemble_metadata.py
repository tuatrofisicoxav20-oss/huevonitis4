"""D1: bank preserva metadatos del pipeline ensemble."""
from PIL import Image


def test_add_glyph_with_ensemble_metadata(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path)

    from core.inkcore.bank import GlyphBank

    src = tmp_path / "test.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(src)

    bank = GlyphBank()
    bank.bank_dir = tmp_path / "bank"
    bank.bank_dir.mkdir(exist_ok=True)
    bank.manifest_file = bank.bank_dir / "manifest.json"
    bank._entries = []

    entry = bank.add_glyph(
        "a", str(src),
        predicted_char="a",
        label_confidence=0.92,
        detector_sources=["classic_cv", "craft"],
        quality_override={"score": 0.88, "tier": "Gold", "ink_coverage": 0.45},
    )

    assert entry is not None
    assert entry.predicted_char == "a"
    assert entry.label_confidence == 0.92
    assert "craft" in entry.detector_sources
    assert entry.tier == "Gold"
    assert abs(entry.quality_score - 0.88) < 1e-9


def test_add_glyph_legacy_signature_unchanged(tmp_path, monkeypatch):
    """Callers legacy add_glyph(char, path) siguen funcionando."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path)

    from core.inkcore.bank import GlyphBank

    src = tmp_path / "test2.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(src)

    bank = GlyphBank()
    bank.bank_dir = tmp_path / "bank2"
    bank.bank_dir.mkdir(exist_ok=True)
    bank.manifest_file = bank.bank_dir / "manifest.json"
    bank._entries = []

    entry = bank.add_glyph("b", str(src))

    assert entry is not None
    assert entry.char == "b"
    assert entry.predicted_char is None
    assert entry.label_confidence is None
    assert entry.detector_sources == []


def test_add_glyph_persists_metadata_on_reload(tmp_path, monkeypatch):
    """Metadatos persisten tras reload del banco."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path)

    from core.inkcore.bank import GlyphBank

    src = tmp_path / "test3.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(src)

    bank = GlyphBank()
    bank.bank_dir = tmp_path / "bank3"
    bank.bank_dir.mkdir(exist_ok=True)
    bank.manifest_file = bank.bank_dir / "manifest.json"
    bank._entries = []

    bank.add_glyph(
        "c", str(src),
        predicted_char="c",
        label_confidence=0.75,
        detector_sources=["classic_cv"],
        quality_override={"score": 0.6, "tier": "Silver", "ink_coverage": 0.3},
    )

    bank2 = GlyphBank()
    bank2.bank_dir = bank.bank_dir
    bank2.manifest_file = bank.manifest_file
    bank2._entries = []
    bank2.load()

    assert bank2._entries, "reload devolvió lista vacía"
    e = bank2._entries[-1]
    assert e.predicted_char == "c"
    assert e.detector_sources == ["classic_cv"]
    assert e.tier == "Silver"

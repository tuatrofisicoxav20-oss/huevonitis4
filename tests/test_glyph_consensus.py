"""Salto 2 — consenso entre instancias + medoide en get_best_glyph."""
import pytest

from core.inkcore.glyph_consensus import (
    demote_session_outliers,
    medoid_index,
    outlier_flags,
)
from core.models import GlyphEntry

# Hashes sintéticos de 64 bits: un cluster casi idéntico + 1 outlier evidente.
GOOD = ["0" * 64, "0" * 63 + "1", "0" * 62 + "11", "1" + "0" * 63]
OUTLIER = "1" * 64


def test_outlier_flags_detects_obvious_outlier():
    hashes = GOOD + [OUTLIER]
    flags = outlier_flags(hashes)
    assert flags[-1] is True          # el outlier se marca
    assert not any(flags[:-1])        # las 4 buenas no


def test_medoid_is_one_of_the_cluster():
    hashes = GOOD + [OUTLIER]
    mi = medoid_index(hashes)
    assert mi != len(hashes) - 1      # nunca el outlier
    assert hashes[mi] in GOOD


def test_no_flags_in_small_group():
    # 3 elementos (< MIN_GROUP=4): no hay evidencia para marcar nada.
    flags = outlier_flags(["0" * 64, "1" * 64, "0" * 32 + "1" * 32])
    assert not any(flags)


def test_demote_session_outliers_lowers_tier():
    glyphs = [GlyphEntry(char="a", tier="Gold") for _ in range(4)]
    glyphs.append(GlyphEntry(char="a", tier="Gold"))  # será el outlier
    hashes = GOOD + [OUTLIER]
    n = demote_session_outliers(glyphs, hashes)
    assert n == 1
    assert glyphs[-1].tier == "Silver"          # outlier degradado
    assert all(g.tier == "Gold" for g in glyphs[:-1])  # las buenas intactas


def test_demote_groups_by_char_independently():
    # Dos chars distintos; el outlier de 'a' no afecta a 'b'.
    glyphs = [GlyphEntry(char="a", tier="Gold") for _ in range(4)]
    glyphs.append(GlyphEntry(char="a", tier="Gold"))
    glyphs += [GlyphEntry(char="b", tier="Gold") for _ in range(2)]
    hashes = GOOD + [OUTLIER] + ["0" * 64, "0" * 64]
    demote_session_outliers(glyphs, hashes)
    assert glyphs[4].tier == "Silver"
    assert glyphs[5].tier == "Gold" and glyphs[6].tier == "Gold"


def test_get_best_glyph_medoid_deterministic(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()
    from core.inkcore.bank import GlyphBank

    bank = GlyphBank()
    entries = []
    for h in GOOD + [OUTLIER]:
        e = GlyphEntry(char="a", tier="Gold", image_path=f"/x/{h[:6]}.png")
        e.perceptual_hash = h
        entries.append(e)
    with_lock = bank._by_char.setdefault("a", [])
    with_lock.extend(entries)

    # Determinista: misma medoide siempre, y NUNCA el outlier.
    first = bank.get_best_glyph("a")
    for _ in range(10):
        assert bank.get_best_glyph("a") is first
    assert first.perceptual_hash in GOOD

    # variation=True puede devolver cualquiera del grupo (incluido el outlier),
    # pero no debe crashear y siempre es del grupo.
    got = {bank.get_best_glyph("a", variation=True).perceptual_hash for _ in range(50)}
    assert got.issubset(set(GOOD + [OUTLIER]))

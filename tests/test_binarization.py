"""Salto 5 — multibinarización adaptativa."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from core.inkcore import binarization as B


def _mask_with_squares(n, size=20, gap=15, h=120):
    """Mask binaria (tinta=255) con n cuadrados separados (n componentes)."""
    w = gap + n * (size + gap)
    m = np.zeros((h, w), np.uint8)
    for k in range(n):
        x = gap + k * (size + gap)
        m[40:40 + size, x:x + size] = 255
    return m


def test_letter_cc_count_counts_separated_squares():
    assert B._letter_cc_count(_mask_with_squares(6)) == 6


def test_letter_cc_count_excludes_page_blob():
    # Una mask casi toda blanca (umbral colapsado) NO cuenta como letras.
    m = np.full((100, 100), 255, np.uint8)
    assert B._letter_cc_count(m) == 0


def test_best_binary_rejects_degenerate(monkeypatch):
    """Si una candidata está invertida (95% tinta), best_binary NO la elige."""
    gray = np.full((120, 200), 240, np.uint8)
    inverted = np.full((120, 200), 255, np.uint8)   # 100% tinta = degenerada
    good = _mask_with_squares(5, h=120)
    # recortar 'good' al tamaño de gray para comparar limpio
    good = good[:120, :200] if good.shape[1] >= 200 else np.pad(
        good, ((0, 0), (0, 200 - good.shape[1])))

    monkeypatch.setattr(B, "candidate_masks",
                        lambda g: [("inv", inverted), ("good", good)])
    name, mask = B.best_binary(gray)
    assert name == "good"
    ink = mask.mean() / 255.0
    assert B.INK_MIN <= ink <= B.INK_MAX


def test_best_binary_prefers_more_letters(monkeypatch):
    gray = np.zeros((120, 400), np.uint8)
    few = _mask_with_squares(3)[:120, :400]
    many = _mask_with_squares(8)[:120, :400]
    few = np.pad(few, ((0, 0), (0, max(0, 400 - few.shape[1]))))[:120, :400]
    many = np.pad(many, ((0, 0), (0, max(0, 400 - many.shape[1]))))[:120, :400]
    monkeypatch.setattr(B, "candidate_masks",
                        lambda g: [("few", few), ("many", many)])
    name, _ = B.best_binary(gray)
    assert name == "many"


def test_candidate_masks_returns_several():
    gray = np.full((100, 300), 230, np.uint8)
    gray[40:70, 30:60] = 200
    cands = B.candidate_masks(gray)
    names = {c[0] for c in cands}
    # al menos Otsu+CLAHE y los dos adaptativos
    assert "otsu_clahe" in names
    assert "adaptive_31_10" in names
    assert len(cands) >= 3

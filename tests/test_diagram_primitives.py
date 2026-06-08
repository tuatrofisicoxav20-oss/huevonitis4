"""Tests de diagram_primitives.HandDraw (Fase 6): wobble, trazo y reproducibilidad."""
import random

import numpy as np
import pytest
from PIL import Image, ImageDraw

from core.inkcore.diagram_primitives import HandDraw


def _canvas(w=400, h=200):
    img = Image.new("RGB", (w, h), "white")
    return img, ImageDraw.Draw(img)


def _ink_count(img):
    return int((np.asarray(img.convert("L")) < 128).sum())


def test_line_tiene_wobble(img=None):
    img, d = _canvas()
    HandDraw(width=2, wobble=3.0).line(d, (10, 100), (390, 100))
    a = np.asarray(img.convert("L"))
    ys = [np.where(a[:, x] < 128)[0].mean() for x in range(a.shape[1]) if (a[:, x] < 128).any()]
    assert np.std(ys) > 0  # no es una recta perfecta


def test_arrow_dibuja_cabeza():
    """La flecha pone más tinta cerca de la punta que una línea pelada."""
    li, ld = _canvas()
    HandDraw(width=2, wobble=0.0).line(ld, (10, 100), (300, 100))
    ai, ad = _canvas()
    HandDraw(width=2, wobble=0.0).arrow(ad, (10, 100), (300, 100))
    assert _ink_count(ai) > _ink_count(li)


@pytest.mark.parametrize("draw_call", [
    lambda hd, d: hd.rect(d, (20, 20, 380, 180)),
    lambda hd, d: hd.circle(d, (200, 100), 80),
    lambda hd, d: hd.ellipse(d, (20, 40, 380, 160)),
    lambda hd, d: hd.brace(d, 200, 20, 180, depth=18, facing="left"),
])
def test_primitivas_dibujan_tinta(draw_call):
    img, d = _canvas()
    draw_call(HandDraw(width=2, wobble=1.5), d)
    assert _ink_count(img) > 0


def test_reproducible_con_rng():
    img1, d1 = _canvas()
    img2, d2 = _canvas()
    HandDraw(width=2, wobble=3.0, rng=random.Random(7)).rect(d1, (20, 20, 380, 180))
    HandDraw(width=2, wobble=3.0, rng=random.Random(7)).rect(d2, (20, 20, 380, 180))
    assert np.array_equal(np.asarray(img1), np.asarray(img2))

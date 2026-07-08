"""R15 — tinta en espacio de trazo. Contratos:

  • GATE: ink_stroke_space=False ⇒ los knobs R15 no tocan un byte del glifo
    (rollback byte-idéntico a R12/R14 probado además contra main con
    ink_boost=0.7 y pen_skip_prob=0 al aterrizar el commit).
  • Determinismo: mismo rng/contenido ⇒ mismo glifo, con todo activo.
  • Invariancia geométrica: el paso NO cambia tamaño ni baseline.
  • Clamps: un trazo fino no se erosiona; el shading no toca el alpha.
  • Showthrough: bajo la tinta queda pasando grano de papel (cap del alpha).
"""
import random
from pathlib import Path

import pytest

try:
    import numpy as np
    from PIL import Image, ImageDraw
    _PIL = True
except ImportError:
    _PIL = False

from tests.test_render_realism import _make_stub_bank

# Rollback R15 (el default del master es True y ink_boost cambió de 0.7 a
# 0.92): esta combinación reproduce R12/R14 exacto.
R15_OFF = dict(ink_stroke_space=False, ink_boost=0.7, pen_skip_prob=0.0)


def _renderer(tmp_path):
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(_make_stub_bank(tmp_path))


def _glyph(tmp_path, ch="o", rng_seed=3, **kw):
    from core.inkcore.renderer import RenderOptions
    r = _renderer(tmp_path)
    e = r._select_entry(ch)
    assert e and Path(e.image_path).exists()
    opts = RenderOptions(seed=1, **kw)
    out = r._load_glyph(e.image_path, opts, ch, geo=r._geo(e), rotation=0.0,
                        rng=random.Random(rng_seed))
    assert out is not None
    return out


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_gate_off_ignora_knobs_r15(tmp_path):
    """Con el master en False, subir los knobs R15 al tope no cambia nada."""
    base, b_base = _glyph(tmp_path, **R15_OFF)
    hot, b_hot = _glyph(tmp_path, **{**R15_OFF, "ink_along_darkness": 0.4,
                                     "ink_width_along": 0.25,
                                     "ink_streak_strength": 0.4,
                                     "ink_pool_boost": 0.4,
                                     "ink_hue_by_density": 0.3})
    assert b_base == b_hot
    assert np.array_equal(np.asarray(base), np.asarray(hot))


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_determinismo_y_geometria(tmp_path):
    """Master ON: dos cargas idénticas ⇒ mismos bytes; y el paso R15 no mueve
    ni el tamaño del lienzo ni el baseline respecto al master OFF."""
    on1, b1 = _glyph(tmp_path, ink_stroke_space=True)
    on2, b2 = _glyph(tmp_path, ink_stroke_space=True)
    assert b1 == b2
    assert np.array_equal(np.asarray(on1), np.asarray(on2))

    off, b_off = _glyph(tmp_path, **R15_OFF)
    assert on1.size == off.size
    assert b1 == b_off
    # y el efecto existe: los píxeles SÍ cambian con el master on
    assert not np.array_equal(np.asarray(on1), np.asarray(off))


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_width_along_no_rompe_trazos_finos():
    """Un trazo de ~2 px de ancho queda intacto (dt.max < 1.4: el clamp
    apaga el paso entero antes de arriesgar un corte)."""
    from core.inkcore.renderer_ink import stroke_width_along

    class _O:
        ink_width_along = 0.25

    thin = Image.new("RGBA", (60, 12), (0, 0, 0, 0))
    ImageDraw.Draw(thin).line([(4, 6), (56, 6)], fill=(26, 26, 46, 255),
                              width=2)
    out = stroke_width_along(thin, random.Random(1), _O(), 40.0)
    assert np.array_equal(np.asarray(out), np.asarray(thin))


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_shading_solo_toca_color():
    """El shading modula RGB; el canal alpha sale byte-idéntico (cero riesgo
    de legibilidad por forma)."""
    from core.inkcore.renderer_ink import stroke_space_shading

    class _O:
        ink_along_darkness = 0.3
        ink_streak_strength = 0.3
        ink_streak_aniso = 4.0
        ink_pool_boost = 0.3
        ink_hue_by_density = 0.2

    bar = Image.new("RGBA", (80, 26), (0, 0, 0, 0))
    ImageDraw.Draw(bar).rectangle([4, 8, 76, 18], fill=(26, 26, 46, 255))
    out = stroke_space_shading(bar, random.Random(1), _O(), 40.0)
    a0 = np.asarray(bar.getchannel("A"))
    a1 = np.asarray(out.getchannel("A"))
    assert np.array_equal(a0, a1)
    rgb0 = np.asarray(bar)[..., :3][a0 > 0]
    rgb1 = np.asarray(out)[..., :3][a0 > 0]
    assert not np.array_equal(rgb0, rgb1), "no moduló el color"
    assert rgb1.std() > rgb0.std(), "la densidad no varía dentro del trazo"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_showthrough_deja_pasar_papel(tmp_path):
    """Con el master on, el punto MÁS oscuro bajo la tinta es más claro que
    sin showthrough: el grano del papel pasa por debajo del trazo."""
    import random as _r

    from core.inkcore.renderer import RenderOptions
    from core.inkcore.renderer_ink import apply_paper

    ink = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    ImageDraw.Draw(ink).rectangle([20, 20, 100, 40], fill=(26, 26, 46, 255))
    paper = Image.new("RGB", (120, 60), (235, 232, 225))

    def _min_lum(**kw):
        opts = RenderOptions(seed=1, ink_texture_strength=0.0, ink_bleed=0.0,
                             ink_texture_v2=False, **kw)
        page = apply_paper(ink, paper, opts, _r.Random(2))
        return np.asarray(page.convert("L"))[20:41, 20:101].min()

    con = _min_lum(ink_stroke_space=True, ink_paper_showthrough=0.08)
    sin = _min_lum(ink_stroke_space=False)
    assert con > sin

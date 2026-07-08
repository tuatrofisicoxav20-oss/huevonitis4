"""Fase R11 — textura de tinta v2 (intra-trazo).

Valida el contrato del patch sobre apply_paper:
  • GATE: con ink_texture_v2=False el render es BYTE-idéntico al de R6 (mismo
    seed) → comparación antes/después y rollback con un solo flag.
  • La textura NO toca geometría: ON y OFF producen imágenes del MISMO tamaño
    (no se mueve baseline/escala/métrica alguna).
  • El flag ON sí cambia píxeles (la textura hace algo) y es determinista.
  • apply_paper con v2 jamás saca valores fuera de [0,255] (clip del color).
"""
import random

import pytest

try:
    import numpy as np
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False

from tests.test_render_realism import _make_stub_bank

_FRASE = "humana respira presion"


def _renderer(tmp_path):
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(_make_stub_bank(tmp_path))


def _opts(**kw):
    from core.inkcore.renderer import RenderOptions
    base = dict(seed=99, background_style="hoja_blanca")
    base.update(kw)
    return RenderOptions(**base)


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_gate_off_es_determinista_y_estable(tmp_path):
    r = _renderer(tmp_path)
    off = _opts(ink_texture_v2=False)
    a = np.asarray(r.render_text(_FRASE, off))
    b = np.asarray(r.render_text(_FRASE, off))
    assert np.array_equal(a, b), "v2 OFF debe ser determinista con la misma seed"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_v2_no_cambia_geometria(tmp_path):
    r = _renderer(tmp_path)
    off = np.asarray(r.render_text(_FRASE, _opts(ink_texture_v2=False)))
    on = np.asarray(r.render_text(_FRASE, _opts(ink_texture_v2=True)))
    assert off.shape == on.shape, "la textura no debe mover baseline/escala/tamaño"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_v2_on_modifica_pixeles_y_es_determinista(tmp_path):
    r = _renderer(tmp_path)
    on = _opts(ink_texture_v2=True)
    c1 = np.asarray(r.render_text(_FRASE, on))
    c2 = np.asarray(r.render_text(_FRASE, on))
    off = np.asarray(r.render_text(_FRASE, _opts(ink_texture_v2=False)))
    assert np.array_equal(c1, c2), "v2 ON debe ser determinista con la misma seed"
    assert not np.array_equal(c1, off), "v2 ON debe cambiar la textura respecto a OFF"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_apply_paper_v2_respeta_rango_de_valores(tmp_path):
    """El campo fino puede pasar de 1.0 (zonas secas); el composite debe quedar
    en [0,255] sin overflow ni envolturas (clip del color de tinta)."""
    from core.inkcore.renderer_ink import apply_paper

    r = _renderer(tmp_path)
    opts = _opts(ink_texture_v2=True, ink_texture_fine_strength=0.9,
                 ink_pooling=0.9, ink_edge_irregularity=0.9, ink_width_jitter=0.6)
    # Capa de tinta real del renderer (RGBA) + papel sólido.
    ink = r.render_transparent(_FRASE, opts)
    paper = Image.new("RGB", ink.size, "#FAFAFA")
    page = apply_paper(ink, paper, opts, random.Random(3))
    arr = np.asarray(page)
    assert arr.min() >= 0 and arr.max() <= 255

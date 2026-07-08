"""Fase R12 — reconstrucción de borde del glifo. Contrato del patch:

  • GATE: edge_reconstruct=False → el paso no corre (rollback/A-B con un flag).
  • INVARIANCIA DE COLOCACIÓN (keystone): con el borde on vs off, CADA glifo
    conserva width y baseline_in idénticos → el layout coloca cada letra en la
    MISMA posición y escala. Es la prueba de que la textura NO toca
    proporciones/métricas (la deriva del golden de geometría es artefacto del
    detector de cajas sobre tinta sangrada, no un cambio de layout).
  • El helper preserva la TOPOLOGÍA: los huecos ('o','a','e'…) no se rellenan.
  • El borde on cambia píxeles y es determinista con la misma seed.
"""
import random
from pathlib import Path

import pytest

try:
    import numpy as np
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False

from tests.test_render_realism import _make_stub_bank

_CHARS = "abcdefghlmnopqrstuvwxyz"


def _renderer(tmp_path):
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(_make_stub_bank(tmp_path))


def _opts(**kw):
    from core.inkcore.renderer import RenderOptions
    # R14 (Track A): estos tests aíslan el paso de BORDE; el latente de mano
    # se apaga para conservar la realización calibrada en R12. (El conteo de
    # draws de apply_paper depende del bbox de tinta de la página; otra
    # realización puede cruzar un límite de celda entre on/off — dependencia
    # de datos anterior a R14.)
    kw.setdefault("hand_energy_sigma", 0.0)
    kw.setdefault("line_end_cramp", 0.0)
    # R17: la presión i.i.d. por glifo también mueve la oscuridad/bbox de la
    # página (misma dependencia de datos que hand_energy); se apaga aquí.
    kw.setdefault("glyph_pressure_jitter", 0.0)
    return RenderOptions(seed=7, background_style="hoja_blanca", **kw)


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_edge_no_cambia_colocacion(tmp_path):
    """KEYSTONE: width y baseline_in de cada glifo son idénticos con el borde
    on/off → la geometría del layout (avance x = width, posición y = baseline_in)
    queda intacta. Si esto pasa, la textura NO movió ninguna proporción."""
    r = _renderer(tmp_path)
    on = _opts(edge_reconstruct=True)
    off = _opts(edge_reconstruct=False)
    checked = 0
    for ch in _CHARS:
        e = r._select_entry(ch)
        if not e or not Path(e.image_path).exists():
            continue
        geo = r._geo(e)
        a = r._load_glyph(e.image_path, on, ch, geo=geo, rotation=0.0,
                          rng=random.Random(1))
        b = r._load_glyph(e.image_path, off, ch, geo=geo, rotation=0.0,
                          rng=random.Random(1))
        if not a or not b:
            continue
        (img_on, base_on), (img_off, base_off) = a, b
        assert img_on.size == img_off.size, f"{ch}: tamaño cambió {img_on.size} vs {img_off.size}"
        assert base_on == base_off, f"{ch}: baseline cambió {base_on} vs {base_off}"
        checked += 1
    assert checked >= 10, "no se evaluaron suficientes glifos"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_edge_no_consume_rng_del_layout(tmp_path):
    """A NIVEL DE PÁGINA: el paso de borde usa su PROPIO RNG y no toca el del
    layout. Tras renderizar la misma página con borde on vs off, el estado del
    RNG compartido debe ser IDÉNTICO → el kerning/jitter (la VARIACIÓN) se
    realiza igual con la misma seed. Si el borde tirara del rnd compartido, el
    stream divergiría y este test fallaría."""
    texto = "operacion respira presion mientras la tinta"
    r1 = _renderer(tmp_path)
    r1.render_text(texto, _opts(edge_reconstruct=True))
    state_on = r1._rng.getstate()
    r2 = _renderer(tmp_path)
    r2.render_text(texto, _opts(edge_reconstruct=False))
    state_off = r2._rng.getstate()
    assert state_on == state_off, "el borde alteró el stream del RNG del layout"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_gate_off_no_corre_el_paso(tmp_path):
    r = _renderer(tmp_path)
    off = _opts(edge_reconstruct=False)
    a = np.asarray(r.render_text("operacion", off))
    b = np.asarray(r.render_text("operacion", off))
    assert np.array_equal(a, b), "OFF debe ser determinista"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_edge_on_cambia_pixeles_y_es_determinista(tmp_path):
    r = _renderer(tmp_path)
    on = _opts(edge_reconstruct=True)
    c1 = np.asarray(r.render_text("operacion", on))
    c2 = np.asarray(r.render_text("operacion", on))
    off = np.asarray(r.render_text("operacion", _opts(edge_reconstruct=False)))
    assert np.array_equal(c1, c2), "ON debe ser determinista con la misma seed"
    assert not np.array_equal(c1, off), "ON debe cambiar la textura del borde"
    assert c1.shape == off.shape, "la página no debe cambiar de tamaño"


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_preserva_huecos_topologia(tmp_path):
    """Un anillo (como el contraforma de una 'o') NO debe rellenarse: el centro
    sigue transparente tras reconstruir el borde."""
    from core.inkcore.renderer_edge import reconstruct_glyph_edge

    size = 80
    a = np.zeros((size, size), np.uint8)
    cv2 = pytest.importorskip("cv2")
    cv2.circle(a, (40, 40), 30, 255, -1)   # disco
    cv2.circle(a, (40, 40), 14, 0, -1)     # hueco central
    rgba = np.dstack([np.full((size, size), 26, np.uint8),
                      np.full((size, size), 26, np.uint8),
                      np.full((size, size), 46, np.uint8), a])
    img = Image.fromarray(rgba)
    out = reconstruct_glyph_edge(img, random.Random(1), strength_px=2.0,
                                 cell_px=20.0, feather_px=1.5, feather_amount=0.5,
                                 outward_bias=0.3)
    oa = np.asarray(out.getchannel("A"))
    assert out.size == img.size, "no debe cambiar el tamaño del lienzo"
    assert oa[40, 40] < 40, "el hueco central se rellenó (topología rota)"
    assert oa[18, 40] > 200, "el anillo (radio ~22) perdió su cuerpo de tinta"

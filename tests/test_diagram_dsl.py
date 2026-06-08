"""Tests de DiagramRenderer (DSL de diagrama → dibujo a mano, Fase 6 en la UI)."""
import importlib.util

import numpy as np
import pytest

_PIL = importlib.util.find_spec("PIL") is not None


@pytest.fixture
def renderer():
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(GlyphBank())


def _ink(img):
    return int((np.asarray(img.convert("L")) < 150).sum())


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_render_devuelve_una_pagina_con_tinta(renderer):
    from core.inkcore.diagram_dsl import DiagramRenderer
    from core.inkcore.renderer import RenderOptions
    dsl = "box 50,50 300,150\narrow 300,100 500,100\ncircle 600,100 40"
    pages = DiagramRenderer(renderer).render(dsl, RenderOptions(font_size=30))
    assert len(pages) == 1
    assert _ink(pages[0]) > 0


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_lineas_invalidas_y_comentarios_no_rompen(renderer):
    from core.inkcore.diagram_dsl import DiagramRenderer
    from core.inkcore.renderer import RenderOptions
    dsl = "# comentario\nbox MALformado\nzzz 1 2 3\ncircle 200,200 50 ok"
    pages = DiagramRenderer(renderer).render(dsl, RenderOptions(font_size=30))
    assert len(pages) == 1  # no lanza, dibuja lo válido


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_etiqueta_usa_la_letra_del_banco(renderer, tmp_path):
    """La etiqueta de una caja se rinde con el motor del banco (no fuente del SO)."""
    import numpy as np
    from PIL import Image

    from core.inkcore.diagram_dsl import DiagramRenderer
    from core.inkcore.renderer import RenderOptions
    # Inyectar un glifo 'a' blanco (forma en alpha) en el banco aislado
    p = tmp_path / "a_000.png"
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[8:32, 8:32, 3] = 255
    Image.fromarray(arr).save(p)
    renderer.bank.add_glyph("a", str(p))
    pages = DiagramRenderer(renderer).render("box 100,100 400,260 aaa", RenderOptions(font_size=40))
    # debe haber tinta dentro de la caja (la etiqueta 'aaa' del banco)
    region = np.asarray(pages[0].convert("L"))[110:250, 110:390]
    assert int((region < 150).sum()) > 100

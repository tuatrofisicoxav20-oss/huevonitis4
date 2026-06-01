"""Tests del puente replicador↔editor (Fase 2) y la variación del renderer (Fase 3)."""
import importlib.util

import pytest

_PIL = importlib.util.find_spec("PIL") is not None


def _make_layout():
    from core.inkcore.replicator import Block, PageLayout
    return PageLayout(
        image_path="", page_width=400, page_height=300,
        blocks=[
            Block(type="text", x=20, y=30, w=200, h=24, text="hola mundo", enabled=True),
            Block(type="text", x=20, y=80, w=200, h=24, text="oculto", enabled=False),
            Block(type="rect", x=10, y=120, w=180, h=60, enabled=True),
        ],
    )


def test_layout_to_page_respeta_toggles_y_tipos():
    from core.inkcore.replicator_edit import layout_to_page
    from core.models import RectElement, TextElement
    page = layout_to_page(_make_layout())
    # El bloque desmarcado (enabled=False) no entra
    assert len(page.elements) == 2
    texts = [e for e in page.elements if isinstance(e, TextElement)]
    rects = [e for e in page.elements if isinstance(e, RectElement)]
    assert len(texts) == 1 and texts[0].text == "hola mundo"
    assert len(rects) == 1
    # Conserva la posición original (el acomodo)
    assert texts[0].x == 20 and texts[0].y == 30
    assert page.width == 400 and page.height == 300


@pytest.mark.skipif(not _PIL, reason="Pillow not installed")
def test_render_page_handwritten_produce_imagen_del_tamano_de_pagina(tmp_path):
    import numpy as np
    from PIL import Image

    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.replicator_edit import layout_to_page, render_page_handwritten

    # Banco con un glifo 'o' blanco (forma en alpha) para que haya tinta visible
    bank = GlyphBank()
    p = tmp_path / "o_000.png"
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[8:32, 8:32, 3] = 255
    Image.fromarray(arr).save(p)
    bank.add_glyph("o", str(p))

    page = layout_to_page(_make_layout())
    img = render_page_handwritten(page, bank)
    assert img is not None
    assert img.size == (400, 300)
    # Hay tinta visible (el recuadro y/o el texto)
    lum = np.asarray(img.convert("L"))
    assert int((lum < 150).sum()) > 50


@pytest.mark.skipif(not _PIL, reason="Pillow not installed")
def test_render_transparent_es_rgba_con_fondo_transparente(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions
    hr = HandwritingRenderer(GlyphBank())
    out = hr.render_transparent("abc", RenderOptions(font_size=30))
    assert out is not None and out.mode == "RGBA"
    # Esquina superior izquierda transparente (no hay tinta ahí)
    assert out.getpixel((0, 0))[3] == 0


@pytest.mark.skipif(not _PIL, reason="Pillow not installed")
def test_slant_y_drift_no_rompen_render(tmp_path):
    import numpy as np
    from PIL import Image

    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions
    bank = GlyphBank()
    p = tmp_path / "a_000.png"
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[8:32, 8:32, 3] = 255
    Image.fromarray(arr).save(p)
    bank.add_glyph("a", str(p))
    hr = HandwritingRenderer(bank)
    img = hr.render_text("aaaa", RenderOptions(slant_deg=12, baseline_drift=4, kerning_jitter=0.8))
    lum = np.asarray(img.convert("L"))
    assert int((lum < 150).sum()) > 100

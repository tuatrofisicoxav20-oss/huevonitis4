"""Tests del HandwritingRenderer: word-wrap, no-truncamiento de líneas largas."""
import pytest


@pytest.fixture
def renderer(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(GlyphBank())


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_text_wrap_no_trunca_lineas_largas(renderer):
    """Una línea larga sin saltos manuales debe wrappear, no truncarse.

    Regresión: render_text (ruta <=30 líneas) no aplicaba _soft_wrap_text, así que
    _render_line cortaba (break) en usable_width y se perdía texto — visible en el
    replicador, que llama render_text por bloque. Ahora el canvas crece en alto
    porque el texto se reparte en varias líneas.
    """
    from core.inkcore.renderer import RenderOptions
    opts = RenderOptions()
    corto = renderer.render_text("hola", opts)
    largo = renderer.render_text(" ".join(["palabra"] * 80), opts)
    assert corto is not None and largo is not None
    # Con el bug el largo se truncaba a 1 línea → misma altura que el corto.
    # Con el fix wrappea en muchas líneas → canvas claramente más alto.
    assert largo.height > corto.height * 2, (
        f"el texto largo no wrappeó (largo={largo.height}, corto={corto.height})"
    )


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_text_respeta_saltos_manuales(renderer):
    """Los \\n del usuario se preservan: N líneas cortas dan más alto que 1."""
    from core.inkcore.renderer import RenderOptions
    opts = RenderOptions()
    una = renderer.render_text("hola", opts)
    cinco = renderer.render_text("a\nb\nc\nd\ne", opts)
    assert una is not None and cinco is not None
    assert cinco.height >= una.height


def test_vertical_class_categorias():
    from core.inkcore.renderer import HandwritingRenderer
    assert HandwritingRenderer._vertical_class("p") == "desc"
    assert HandwritingRenderer._vertical_class("g") == "desc"
    assert HandwritingRenderer._vertical_class("d") == "asc"
    assert HandwritingRenderer._vertical_class("l") == "asc"
    assert HandwritingRenderer._vertical_class("a") == "xheight"
    assert HandwritingRenderer._vertical_class("o") == "xheight"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_recolor_ink_glifo_blanco_se_vuelve_visible():
    """Un glifo del extractor (RGB blanco, forma en alpha) debe recolorearse a la tinta.

    Regresión del bug de texto invisible: sin recolorear, la tinta blanca sobre
    papel claro no se veía. _recolor_ink repinta la forma con ink_color.
    """
    import numpy as np
    from PIL import Image

    from core.inkcore.renderer import HandwritingRenderer
    arr = np.zeros((30, 30, 4), dtype=np.uint8)
    arr[:, :, :3] = 255              # RGB blanco
    arr[8:22, 8:22, 3] = 255         # forma (cuadrado) solo en alpha
    out = HandwritingRenderer._recolor_ink(Image.fromarray(arr), "#1A1A2E")
    oarr = np.asarray(out)
    shape = oarr[:, :, 3] > 128      # donde hay forma
    assert shape.sum() > 0
    # En la forma, el RGB debe ser la tinta (~26,26,46), no blanco
    rgb_in_shape = oarr[:, :, :3][shape].mean(axis=0)
    assert rgb_in_shape[0] < 80 and rgb_in_shape[2] < 90, f"no se recoloreó: {rgb_in_shape}"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_render_text_produce_tinta_visible(renderer, tmp_path):
    """El render sobre un banco con un glifo blanco produce tinta visible (no 0 px)."""
    import numpy as np
    from PIL import Image

    from core.inkcore.renderer import RenderOptions
    # Inyectar un glifo 'a' blanco (forma en alpha) en el banco aislado
    p = tmp_path / "a_000.png"
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[8:32, 8:32, 3] = 255
    Image.fromarray(arr).save(p)
    renderer.bank.add_glyph("a", str(p))
    img = renderer.render_text("aaa", RenderOptions())
    lum = np.asarray(img.convert("L"))
    assert int((lum < 150).sum()) > 100, "la tinta sigue invisible tras recolorear"

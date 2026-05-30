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

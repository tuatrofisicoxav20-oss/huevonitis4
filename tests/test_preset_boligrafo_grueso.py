"""Preset 'Bolígrafo grueso': mismo bolígrafo, trazo más cargado de tinta.

El contrato importante no es "ink_boost más bajo" sino que la tinta extra venga
del ÁREA del trazo (ink_width_jitter dilata el alpha). El gamma satura: el núcleo
del trazo ya es opaco y sólo puede empujar los píxeles de borde del antialiasing.
"""
import numpy as np
import pytest

from tests.test_render_realism import _make_stub_bank


@pytest.fixture
def stub_renderer(tmp_path):
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(_make_stub_bank(tmp_path))


def _ink_mass(img) -> float:
    """Tinta depositada: sólo píxeles claramente más oscuros que el papel.

    Umbralizar es necesario: el grano del papel es una constante aditiva que
    sesgaría el ratio hacia 1 si se sumara toda la oscuridad de la página.
    """
    g = np.asarray(img.convert("L"), dtype=np.float64)
    dark = np.percentile(g, 99.0) - g
    return float(dark[dark > 40].sum())


def test_preset_existe_y_hereda_identidad_de_boligrafo():
    from core.inkcore.renderer import STYLE_PRESETS

    assert "Bolígrafo grueso" in STYLE_PRESETS
    base, grueso = STYLE_PRESETS["Bolígrafo"], STYLE_PRESETS["Bolígrafo grueso"]
    # Hereda la identidad de bolígrafo: misma tinta azul-negra y misma mano.
    assert grueso["ink_color"] == base["ink_color"]
    assert grueso["rotation_range"] == base["rotation_range"]
    assert grueso["background_style"] == base["background_style"]


def test_preset_carga_tinta_por_area_no_por_gamma():
    from core.inkcore.renderer import STYLE_PRESETS

    base, grueso = STYLE_PRESETS["Bolígrafo"], STYLE_PRESETS["Bolígrafo grueso"]
    # El área es el lever: la dilatación se enciende (el base la tiene apagada).
    assert base.get("ink_width_jitter", 0.0) == 0.0
    assert grueso["ink_width_jitter"] == pytest.approx(0.35)
    # Y el sangrado BAJA: sumar dilatación sobre bleed=1.8 emborrona el trazo.
    assert grueso["ink_bleed"] < base["ink_bleed"]


def test_apply_style_propaga_las_perillas_a_render_options():
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions

    opts = HandwritingRenderer.apply_style(
        HandwritingRenderer.__new__(HandwritingRenderer),
        RenderOptions(style="Bolígrafo grueso"),
    )
    assert opts.ink_width_jitter == pytest.approx(0.35)
    assert opts.ink_boost == pytest.approx(0.20)
    assert opts.ink_bleed == pytest.approx(0.8)
    assert opts.ink_color == "#0B1A52"


_TEXTO = "el veloz murcielago hindu comia feliz cardillo y kiwi"


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_deposita_mucha_mas_tinta_que_el_render_por_defecto(stub_renderer):
    """Comportamiento, no sólo configuración: la página sale mucho más entintada.

    El control es "Limpio" (el render por defecto), no "Bolígrafo": el base lleva
    ink_bleed=1.8 en px ABSOLUTOS, que a DPI bajo engorda tanto que compensa la
    dilatación y deja la diferencia dentro del ruido.
    """
    from core.inkcore.renderer import RenderOptions

    limpio = stub_renderer.render_pages(_TEXTO, RenderOptions(style="Limpio", seed=42))[0]
    grueso = stub_renderer.render_pages(_TEXTO, RenderOptions(style="Bolígrafo grueso", seed=42))[0]

    m_limpio, m_grueso = _ink_mass(limpio), _ink_mass(grueso)
    assert m_grueso > m_limpio * 1.25, (
        f"'Bolígrafo grueso' no carga tinta: {m_grueso:,.0f} vs {m_limpio:,.0f}"
    )


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("PIL"),
    reason="Pillow not installed",
)
def test_la_tinta_extra_viene_de_la_dilatacion(stub_renderer):
    """Apagar ink_width_jitter, con todo lo demás igual, quita tinta.

    Gotcha: `render_pages` vuelve a llamar `apply_style`, así que un preset SIEMPRE
    pisa lo que pase el caller. Para variar una perilla del preset hay que usar un
    `style` que no exista en STYLE_PRESETS y pasar las perillas a mano.
    """
    from core.inkcore.renderer import STYLE_PRESETS, RenderOptions

    perillas = dict(STYLE_PRESETS["Bolígrafo grueso"])
    con = stub_renderer.render_pages(
        _TEXTO, RenderOptions(style="__sin_preset__", seed=42, **perillas))[0]
    sin = stub_renderer.render_pages(
        _TEXTO, RenderOptions(style="__sin_preset__", seed=42,
                              **{**perillas, "ink_width_jitter": 0.0}))[0]

    m_con, m_sin = _ink_mass(con), _ink_mass(sin)
    assert m_con > m_sin * 1.05, (
        f"la dilatación no aporta tinta: con={m_con:,.0f} sin={m_sin:,.0f}"
    )

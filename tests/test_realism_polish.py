"""Tests Fase 6.5: inclinación por línea, márgenes irregulares, glifos faltantes."""
import importlib.util

import pytest

_PIL = importlib.util.find_spec("PIL") is not None


@pytest.fixture
def renderer():
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(GlyphBank())


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_inclinacion_base_distinta_por_linea(renderer):
    from core.inkcore.renderer import RenderOptions
    renderer.render_text("a\nb\nc\nd\ne", RenderOptions(font_size=40, line_slant_deg=1.5, seed=1))
    slants = renderer._last_line_slants
    assert len(slants) >= 5
    assert len(set(round(s, 3) for s in slants)) > 1  # no todas iguales


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_line_slant_cero_desactiva(renderer):
    from core.inkcore.renderer import RenderOptions
    renderer.render_text("a\nb\nc", RenderOptions(font_size=40, line_slant_deg=0.0))
    assert all(s == 0.0 for s in renderer._last_line_slants)


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_glifo_faltante_se_reporta_sin_romper(renderer):
    from core.inkcore.renderer import RenderOptions
    # El banco vacío del fixture: todo carácter es "faltante" → debe reportarlos,
    # no romper, y devolver una imagen.
    img = renderer.render_text("hola @#", RenderOptions(font_size=40))
    assert img is not None
    miss = renderer.last_missing_chars()
    assert "@" in miss and "#" in miss
    assert " " not in miss  # los espacios no cuentan como faltantes


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_seed_reproduce_slants(renderer):
    from core.inkcore.renderer import RenderOptions
    renderer.render_text("a\nb\nc\nd", RenderOptions(font_size=40, line_slant_deg=1.5, seed=9))
    s1 = list(renderer._last_line_slants)
    renderer.render_text("a\nb\nc\nd", RenderOptions(font_size=40, line_slant_deg=1.5, seed=9))
    s2 = list(renderer._last_line_slants)
    assert s1 == s2

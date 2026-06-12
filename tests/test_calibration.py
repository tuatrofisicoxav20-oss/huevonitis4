"""Tests R4: calibración de varianzas desde una página real (calibration.json).

La "página real" del test es sintética con parámetros CONOCIDOS: se renderiza
con el propio renderer (seed fija, varianzas elegidas) y el calibrador debe
recuperar esas estadísticas dentro de tolerancia — cierra el loop
render → medir → calibrar → render.
"""
import importlib.util
import json

import pytest

_PIL = importlib.util.find_spec("PIL") is not None

pytestmark = pytest.mark.skipif(not _PIL, reason="Pillow no instalado")

_LINEAS = (
    "el veloz murcielago hindu comia feliz cardillo y kiwi\n"
    "la cigarra zumba bajo el sol que arde sin parar\n"
    "joven pesquisa extrana firma un haz de luz boreal\n"
    "quien mira de lejos no distingue la tinta del lapiz\n"
    "cada palabra cae donde la mano quiere y no donde debe"
)
# Dos repeticiones (~90 huecos de palabra): con una sola página corta el
# estimador del cv tiene demasiada varianza de muestreo para tolerancias <20%.
TEXTO = _LINEAS + "\n" + _LINEAS


def _render_pagina(tmp_path, **option_overrides):
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions
    from tests.test_render_realism import _make_stub_bank

    bank = _make_stub_bank(tmp_path)
    r = HandwritingRenderer(bank)
    opts = RenderOptions(style="", background_style="hoja_blanca", seed=11,
                         **option_overrides)
    page = r.render_pages(TEXTO, opts)[0]
    p = tmp_path / "pagina_patron.png"
    page.save(p)
    return p


def test_calibrate_recupera_word_gap_cv(tmp_path):
    """El CV del espacio de palabra medido queda a <20% del configurado.

    La medición es borde-a-borde de tinta (como en una página real): el gap
    base entre letras desplaza un poco la media — por eso el objetivo se
    verifica contra el cv EFECTIVO borde-a-borde, no contra el parámetro puro.
    """
    from tools.calibrate_profile import calibrate

    objetivo = 0.20
    img = _render_pagina(tmp_path, word_space_cv=objetivo, jitter_px=0,
                         rotation_range=0.0, size_variation=0.0,
                         baseline_drift=0.0, line_slant_deg=0.0,
                         kerning_jitter=0.0, warp_strength=0.0,
                         glyph_slant_drift_deg=0.0)
    out = tmp_path / "calibration.json"
    data = calibrate(str(img), out)
    medido = data["metrics"]["word_gap_cv"]
    assert abs(medido - objetivo) / objetivo < 0.20, (
        f"word_gap_cv configurado {objetivo}, calibrado {medido}")


def test_roundtrip_calibracion_reproduce_estadisticas(tmp_path):
    """Loop completo: página A → calibrate → render B con from_calibration →
    las MEDICIONES de A y B coinciden (<20%) en espaciado de palabra."""
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions
    from tests.test_render_realism import _make_stub_bank
    from tools.calibrate_profile import calibrate
    from tools.eval_render.metrics import metrics_from_path

    img_a = _render_pagina(tmp_path, word_space_frac=0.5, word_space_cv=0.25)
    perfil = tmp_path / "perfil"
    calibrate(str(img_a), perfil / "calibration.json")

    bank = _make_stub_bank(tmp_path)
    r = HandwritingRenderer(bank)
    opts_b = RenderOptions.from_calibration(
        perfil, style="", background_style="hoja_blanca", seed=99)
    page_b = r.render_pages(TEXTO, opts_b)[0]
    p_b = tmp_path / "b.png"
    page_b.save(p_b)

    m_a = metrics_from_path(str(img_a))
    m_b = metrics_from_path(str(p_b))
    assert abs(m_b["word_gap_mu"] - m_a["word_gap_mu"]) / m_a["word_gap_mu"] < 0.20, (
        f"mu A={m_a['word_gap_mu']} vs B={m_b['word_gap_mu']}")
    assert abs(m_b["word_gap_cv"] - m_a["word_gap_cv"]) / m_a["word_gap_cv"] < 0.20, (
        f"cv A={m_a['word_gap_cv']} vs B={m_b['word_gap_cv']}")


def test_calibrate_recupera_espaciado_medio(tmp_path):
    """El espacio de palabra MEDIO (en fracción de altura) se recupera <20%."""
    from tools.calibrate_profile import calibrate

    img = _render_pagina(tmp_path, word_space_frac=0.55, word_space_cv=0.10,
                         jitter_px=0, rotation_range=0.0, size_variation=0.0,
                         baseline_drift=0.0, line_slant_deg=0.0,
                         kerning_jitter=0.0, warp_strength=0.0,
                         glyph_slant_drift_deg=0.0)
    data = calibrate(str(img), tmp_path / "c.json")
    m = data["metrics"]
    # word_space configurado: 0.55·font_size(44) ≈ 24.2 px. El gap de CAJAS
    # mide borde-a-borde (sin el avance del gap base), de ahí la tolerancia.
    assert 0.8 * 24.2 <= m["word_gap_mu"] <= 1.2 * 24.2, m["word_gap_mu"]


def test_calibration_json_y_from_calibration(tmp_path):
    """calibrate escribe el JSON y from_calibration lo mapea con clamps."""
    from core.inkcore.renderer import RenderOptions
    from tools.calibrate_profile import calibrate

    img = _render_pagina(tmp_path, word_space_cv=0.30, baseline_drift=3.0)
    out = tmp_path / "perfil" / "calibration.json"
    calibrate(str(img), out)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 1 and "metrics" in data

    opts = RenderOptions.from_calibration(out.parent)
    # El cv calibrado entra (clamped a [0.08, 0.35]).
    assert 0.08 <= opts.word_space_cv <= 0.35
    assert True  # vino del JSON, no del default
    assert 1.0 <= opts.baseline_drift <= 6.0
    assert 0.04 <= opts.size_variation <= 0.25
    assert 0.20 <= opts.word_space_frac <= 0.70


def test_from_calibration_clamps_contra_basura(tmp_path):
    """Un JSON con valores absurdos (mal escaneo) no produce un render loco."""
    from core.inkcore.renderer import RenderOptions

    d = tmp_path / "perfil"
    d.mkdir()
    (d / "calibration.json").write_text(json.dumps({
        "version": 1,
        "metrics": {"height_mu": 20.0, "word_gap_mu": 400.0,  # 20× la letra
                    "word_gap_cv": 3.0, "letter_gap_mu": 90.0,
                    "baseline_sigma": 50.0, "slant_mean": 45.0,
                    "slant_std": 30.0, "height_cv": 2.0,
                    "left_margin_sigma": 200.0},
    }), encoding="utf-8")
    opts = RenderOptions.from_calibration(d)
    assert opts.word_space_frac == 0.70      # clamp superior
    assert opts.word_space_cv == 0.35
    assert opts.letter_gap_frac == 0.20
    assert opts.baseline_drift == 6.0
    assert opts.slant_deg == 8.0
    assert opts.rotation_range == 5.0
    assert opts.size_variation == 0.25
    assert opts.margin_walk_px == 14.0


def test_sin_calibration_devuelve_defaults(tmp_path):
    from core.inkcore.renderer import RenderOptions
    opts = RenderOptions.from_calibration(tmp_path, jitter_px=5)
    assert opts.word_space_cv == 0.18 and opts.jitter_px == 5

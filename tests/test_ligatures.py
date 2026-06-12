"""Tests R10 (G3): ligaduras de pares frecuentes (semi-cursiva básica).

Los pares del español ("qu", "ll", "de"…) se capturan ESCRITOS JUNTOS en una
casilla del template y el banco/renderer los tratan como un carácter de dos
letras: lookup de par antes que de char suelto, con probabilidad p.
"""
import importlib.util

import pytest

_DEPS = all(importlib.util.find_spec(m) for m in ("PIL", "cv2", "numpy"))

pytestmark = pytest.mark.skipif(not _DEPS, reason="faltan PIL/cv2/numpy")


def test_layout_acepta_charset_con_pares():
    from core.inkcore.template_sheet import (
        MINUSCULAS,
        PARES_FRECUENTES,
        TemplateLayout,
        build_template_sheet,
    )

    charset = list(MINUSCULAS) + list(PARES_FRECUENTES)
    lay = TemplateLayout(charset=charset)
    assert lay.cell_letter(len(MINUSCULAS)) == "qu"
    assert lay.cell_letter(len(charset) - 1) == "es"
    assert lay.n_cells >= len(charset)
    img = build_template_sheet(lay)
    assert img is not None and img.width == lay.width


def test_roundtrip_extrae_pares(tmp_path):
    """Una casilla rotulada 'qu' escrita junta se extrae etiquetada 'qu'.

    El charset es el REALISTA (minúsculas + pares): un charset de 3 tokens
    degenera la grilla en una sola fila gigante y el umbral de casilla vacía
    (proporcional al área) se traga los trazos finos — eso es geometría de
    grilla preexistente, no de ligaduras.
    """
    from core.inkcore.template_extract import extract_from_template
    from core.inkcore.template_sheet import MINUSCULAS, TemplateLayout
    from tests.test_template import _fill_sheet

    charset = [*list(MINUSCULAS), "qu", "ll", "de"]
    lay = TemplateLayout(charset=charset)
    idx = {tok: i for i, tok in enumerate(charset)}
    img = _fill_sheet(lay, [idx["qu"], idx["ll"], idx["de"]])
    p = tmp_path / "pares.png"
    img.save(p)
    out = extract_from_template(str(p), lay)
    chars = [c for c, _g, _q in out]
    assert set(chars) == {"qu", "ll", "de"}, chars
    # Geometría del par: 'qu' tiene descendente (la q) → su baseline queda
    # ARRIBA del fondo del crop; 'll' asienta (baseline al fondo de tinta).
    geos = {c: g.info["geometry"] for c, g, _q in out}
    assert geos["qu"]["baseline_off"] < geos["qu"]["nat_h_px"] - 4
    assert geos["ll"]["nat_h_px"] - geos["ll"]["baseline_off"] <= 12


def _bank_con_pares(tmp_path):
    """Banco stub: minúsculas sueltas + las ligaduras 'de' y 'en'."""
    from tests.test_render_realism import _make_stub_bank, _stub_glyph

    bank = _make_stub_bank(tmp_path)
    gd = tmp_path / "pares"
    gd.mkdir()
    for par in ("de", "en"):
        # Ligadura stub: los dos glifos pegados lado a lado en un PNG.
        from PIL import Image
        a, _geo_a = _stub_glyph(par[0])
        b, _geo_b = _stub_glyph(par[1])
        h = max(a.height, b.height)
        img = Image.new("RGBA", (a.width + b.width - 4, h), (255, 255, 255, 0))
        img.paste(a, (0, h - a.height), a)
        img.paste(b, (a.width - 4, h - b.height), b)
        p = gd / f"{par}.png"
        img.save(p)
        bank.add_glyph(par, str(p), geometry={
            "nat_h_px": img.height, "nat_w_px": img.width,
            "baseline_off": img.height - 2, "em_px": 100,
            "lsb": 0, "rsb": 0, "metrics_source": "template",
        })
    return bank


def test_render_usa_ligadura_con_probabilidad(tmp_path):
    """Con ligature_prob=1 el par del banco se usa; con 0, nunca."""
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions

    bank = _bank_con_pares(tmp_path)
    r = HandwritingRenderer(bank)

    siempre = RenderOptions(style="", background_style="hoja_blanca", seed=3,
                            ligature_prob=1.0)
    r.render_pages("de en de en", siempre)
    usados = set(r._sel_history.keys())
    assert {"de", "en"} <= usados, f"no usó las ligaduras: {usados}"
    assert "d" not in usados and "n" not in usados
    # La cobertura cuenta CARACTERES: 8 letras pedidas, 8 cubiertas.
    assert r._glyphs_placed == 8

    nunca = RenderOptions(style="", background_style="hoja_blanca", seed=3,
                          ligature_prob=0.0)
    r.render_pages("de en", nunca)
    usados = set(r._sel_history.keys())
    assert "de" not in usados and "en" not in usados
    assert {"d", "e", "n"} <= usados


def test_par_inexistente_no_afecta(tmp_path):
    """Texto con pares que NO están en el banco renderiza char a char."""
    from core.inkcore.renderer import HandwritingRenderer, RenderOptions
    from tests.test_render_realism import _make_stub_bank

    r = HandwritingRenderer(_make_stub_bank(tmp_path))
    opts = RenderOptions(style="", background_style="hoja_blanca", seed=5,
                         ligature_prob=1.0)
    pages = r.render_pages("denude", opts)
    assert pages and not r.last_missing_chars()
    assert r._glyphs_placed == 6

"""Tests del modo MAPA CONCEPTUAL (Ticket 3, fases A–C).

Cubren: parsing de texto indentado → árbol, layout sin solapes de cajas, y
render que produce una página RGB con tinta visible y exportable.
"""
import importlib.util

import pytest

_PIL = importlib.util.find_spec("PIL") is not None


@pytest.fixture
def renderer(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(GlyphBank())


def _bank_con_a(renderer, tmp_path):
    """Inyecta un glifo 'a' blanco (forma en alpha) en el banco aislado."""
    import numpy as np
    from PIL import Image
    p = tmp_path / "a_000.png"
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :, :3] = 255
    arr[8:32, 8:32, 3] = 255
    Image.fromarray(arr).save(p)
    renderer.bank.add_glyph("a", str(p))


# ── Fase A: parsing ─────────────────────────────────────────────────────────

def test_parse_jerarquia_basica():
    from core.inkcore.concept_map import parse_indented_tree
    root = parse_indented_tree(
        "Raiz\n"
        "  Hijo A\n"
        "  Hijo B\n"
        "    Nieto\n"
    )
    assert root is not None
    assert root.text == "Raiz"
    assert [c.text for c in root.children] == ["Hijo A", "Hijo B"]
    assert [c.text for c in root.children[1].children] == ["Nieto"]
    assert root.children[1].children[0].depth == 2


def test_parse_descarta_vinetas_y_blancos():
    from core.inkcore.concept_map import parse_indented_tree
    root = parse_indented_tree(
        "- Raiz\n"
        "\n"
        "  * Hijo A\n"
        "  + Hijo B\n"
    )
    assert root.text == "Raiz"
    assert [c.text for c in root.children] == ["Hijo A", "Hijo B"]


def test_parse_multiples_raices_usa_raiz_virtual():
    from core.inkcore.concept_map import parse_indented_tree
    root = parse_indented_tree("Uno\nDos\n")
    assert root.virtual is True
    assert [c.text for c in root.children] == ["Uno", "Dos"]


def test_parse_texto_vacio_devuelve_none():
    from core.inkcore.concept_map import parse_indented_tree
    assert parse_indented_tree("   \n\n") is None


# ── Fase B: layout ──────────────────────────────────────────────────────────

def _rects_solapan(a, b) -> bool:
    """True si dos cajas (x, y, w, h) ya posicionadas se enciman."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


@pytest.mark.skipif(not _PIL, reason="Pillow not installed")
def test_layout_sin_cajas_encimadas(renderer, tmp_path):
    """El árbol de validación (1 raíz + 4 hijos + 1 nieto) no encima cajas."""
    from core.inkcore.concept_map import ConceptMapRenderer, iter_nodes, parse_indented_tree
    from core.inkcore.renderer import RenderOptions
    _bank_con_a(renderer, tmp_path)
    cmr = ConceptMapRenderer(renderer)
    opts = renderer.apply_style(RenderOptions())
    root = parse_indented_tree(
        "Raiz\n"
        "  aaa\n"
        "  aaa aaa\n"
        "    aaa\n"
        "  aaa\n"
        "  aaa aaa aaa\n"
    )
    cmr._measure(root, opts)
    cmr._layout(root)
    cmr._normalize_positions(root)
    nodes = [n for n in iter_nodes(root) if not n.virtual]
    rects = [(n.x + n.jx, n.y + n.jy, n.w, n.h) for n in nodes]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not _rects_solapan(rects[i], rects[j]), (
                f"cajas encimadas: nodo {i} y {j} ({rects[i]} vs {rects[j]})"
            )


@pytest.mark.skipif(not _PIL, reason="Pillow not installed")
def test_layout_hijos_debajo_de_la_raiz(renderer, tmp_path):
    from core.inkcore.concept_map import ConceptMapRenderer, parse_indented_tree
    from core.inkcore.renderer import RenderOptions
    _bank_con_a(renderer, tmp_path)
    cmr = ConceptMapRenderer(renderer)
    opts = renderer.apply_style(RenderOptions())
    root = parse_indented_tree("Raiz\n  aaa\n  aaa\n")
    cmr._measure(root, opts)
    cmr._layout(root)
    cmr._normalize_positions(root)
    for child in root.children:
        assert child.y > root.y, "los hijos deben quedar debajo de la raíz"


# ── Fase C: render ──────────────────────────────────────────────────────────

@pytest.mark.skipif(not _PIL, reason="Pillow not installed")
def test_render_concept_map_produce_pagina_con_tinta(renderer, tmp_path):
    import numpy as np

    from core.inkcore.concept_map import ConceptMapRenderer
    from core.inkcore.renderer import RenderOptions
    _bank_con_a(renderer, tmp_path)
    pages = ConceptMapRenderer(renderer).render(
        "Raiz\n  aaa\n  aaa aaa\n    aaa\n  aaa\n  aaa\n",
        RenderOptions(),
    )
    assert isinstance(pages, list) and len(pages) == 1
    page = pages[0]
    assert page.mode == "RGB"
    lum = np.asarray(page.convert("L"))
    # Cajas + conectores + texto: bastante tinta oscura sobre fondo claro.
    assert int((lum < 150).sum()) > 1000, "el mapa no tiene tinta visible"


@pytest.mark.skipif(not _PIL, reason="Pillow not installed")
def test_render_concept_map_vacio_no_crashea(renderer):
    from core.inkcore.concept_map import ConceptMapRenderer
    from core.inkcore.renderer import RenderOptions
    assert ConceptMapRenderer(renderer).render("   \n", RenderOptions()) == []


@pytest.mark.skipif(not _PIL, reason="Pillow not installed")
def test_render_concept_map_exportable_a_pdf(renderer, tmp_path):
    from core.inkcore.concept_map import ConceptMapRenderer
    from core.inkcore.renderer import RenderOptions
    _bank_con_a(renderer, tmp_path)
    pages = ConceptMapRenderer(renderer).render("Raiz\n  aaa\n  aaa\n", RenderOptions())
    assert pages
    out = tmp_path / "mapa.pdf"
    pages[0].save(str(out), "PDF", resolution=150)
    assert out.exists() and out.stat().st_size > 0

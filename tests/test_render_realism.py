"""Golden R0: línea base de métricas de realismo del renderer ACTUAL.

Renderiza una frase fija con seed fija sobre un banco STUB de glifos
sintéticos cuyas proporciones naturales son conocidas (x-height 40 px,
ascendentes 60, descendentes 62 con cola) y registra las métricas de
tools/eval_render/metrics.py como snapshot.

Estos números documentan los defectos del renderer de HOY (R-BUG-01/02/05…):
height_cv plano, word_gap_cv ≈ 0, dup_rate alto. Las fases R2-R9 los mueven y
ACTUALIZAN este golden con asserts direccionales (height_cv > 0.30, etc.).
"""
import importlib.util

import pytest

_PIL = importlib.util.find_spec("PIL") is not None

# Sólo a-z y espacios/saltos: el banco stub cubre las 26 minúsculas. Líneas
# < 45 chars para que el wrap actual (estimación 0.55·fs) no las parta y el
# snapshot no dependa de ese detalle.
FRASE_PATRON = (
    "el veloz murcielago hindu comia feliz\n"
    "la cigarra zumba bajo el sol que arde\n"
    "joven pesquisa extrana firma de luz"
)

_ASCENDERS = frozenset("bdfhklt")
_DESCENDERS = frozenset("gjpqy")


def _stub_glyph(char: str):
    """Glifo sintético estilo banco real: RGB blanco + forma en el alpha.

    Proporciones naturales conocidas: cuerpo (x-height) de 40 px; las
    ascendentes suman asta hacia arriba (alto 60) y las descendentes cola
    hacia abajo (alto 62). La silueta varía de forma determinista por char
    para que el dHash distinga letras distintas, como en una letra real.
    """
    from PIL import Image, ImageDraw

    k = ord(char)
    w = 26 + (k * 7) % 22          # 26..47 px, determinista por char
    if char in _DESCENDERS:
        h, body_y0, body_y1 = 62, 0, 40
    elif char in _ASCENDERS:
        h, body_y0, body_y1 = 60, 20, 60
    else:
        h, body_y0, body_y1 = 40, 0, 40

    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    ink = (255, 255, 255, 255)
    t = 4  # grosor de trazo

    # Cuerpo: elipse / arco / zigzag según el char (siluetas distintas).
    shape = k % 3
    if shape == 0:
        draw.ellipse((2, body_y0 + 2, w - 3, body_y1 - 3), outline=ink, width=t)
    elif shape == 1:
        draw.arc((2, body_y0 + 2, w - 3, body_y1 - 3), 90, 360, fill=ink, width=t)
        draw.line((w - 5, body_y0 + 6, w - 5, body_y1 - 3), fill=ink, width=t)
    else:
        mid = (body_y0 + body_y1) // 2
        draw.line((2, body_y1 - 3, w // 2, body_y0 + 3), fill=ink, width=t)
        draw.line((w // 2, body_y0 + 3, w - 3, body_y1 - 3), fill=ink, width=t)
        draw.line((4, mid, w - 5, mid), fill=ink, width=t)

    # Asta (ascendentes) o cola (descendentes) en una x determinista.
    stem_x = 4 + (k * 5) % max(1, w - 10)
    if char in _ASCENDERS:
        draw.line((stem_x, 0, stem_x, body_y1 - 4), fill=ink, width=t)
    elif char in _DESCENDERS:
        draw.line((stem_x, body_y1 - 6, stem_x, h - 2), fill=ink, width=t)
        draw.line((stem_x, h - 4, max(2, stem_x - 8), h - 2), fill=ink, width=t)
    return img


@pytest.fixture
def stub_renderer(tmp_path):
    """HandwritingRenderer sobre un banco aislado con las 26 minúsculas stub."""
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer

    bank = GlyphBank()
    glyph_dir = tmp_path / "stub_glyphs"
    glyph_dir.mkdir()
    bank.begin_batch()
    for ch in "abcdefghijklmnopqrstuvwxyz":
        p = glyph_dir / f"{ch}.png"
        _stub_glyph(ch).save(p)
        bank.add_glyph(ch, str(p))
    bank.end_batch()
    return HandwritingRenderer(bank)


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_golden_metricas_linea_base(stub_renderer):
    """Snapshot R0 de las métricas del renderer actual (seed fija)."""
    from core.inkcore.renderer import RenderOptions
    from tools.eval_render.metrics import compute_metrics

    opts = RenderOptions(style="", background_style="hoja_blanca", seed=42)
    pages = stub_renderer.render_pages(FRASE_PATRON, opts)
    assert pages, "render_pages no devolvió páginas"
    m = compute_metrics(pages[0])
    print("\nGOLDEN R0:", m)

    # Sanidad estructural: 3 líneas de texto con decenas de letras.
    assert m["n_lines"] == 3
    assert m["n_boxes"] > 60

    # ── Snapshot de LÍNEA BASE (renderer actual, valores defectuosos a mover) ──
    # height_cv ~0.20: la escala por clase da DOS alturas posibles, no el
    # continuo natural (0.35-0.60 humano). R2 debe subirlo a > 0.30.
    assert m["height_cv"] == pytest.approx(0.20, rel=0.5)
    # word_gap_cv ~0.04: espacio de palabra CONSTANTE (R-BUG-05). R3 → > 0.10.
    assert m["word_gap_cv"] < 0.08
    # baseline_autocorr ~-0.10: jitter BLANCO por letra encima del drift
    # (ruido, no paseo humano). R3 (deriva correlacionada) → > 0.4.
    assert m["baseline_autocorr"] == pytest.approx(-0.10, abs=0.30)
    # dup_rate ~0.77 con 1 variante por char (efecto sello). R5 → < 0.05.
    assert m["phash_dup_rate"] > 0.30


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_compare_cli_corre_sobre_dos_pngs(stub_renderer, tmp_path):
    """compare.py funciona end-to-end sobre dos PNGs cualesquiera."""
    from core.inkcore.renderer import RenderOptions
    from tools.eval_render.compare import main

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    stub_renderer.render_pages(
        FRASE_PATRON, RenderOptions(style="", background_style="hoja_blanca", seed=1)
    )[0].save(a)
    stub_renderer.render_pages(
        FRASE_PATRON, RenderOptions(style="", background_style="hoja_blanca", seed=2)
    )[0].save(b)
    out_json = tmp_path / "cmp.json"
    rc = main([str(a), str(b), "--json", str(out_json)])
    assert rc == 0
    assert out_json.exists()


@pytest.mark.skipif(not _PIL, reason="Pillow no instalado")
def test_coverage_report_lista_faltantes(stub_renderer):
    """coverage_report avisa qué chars no tiene el banco SIN renderizar (R0)."""
    rep = stub_renderer.coverage_report("hola 123 ñu")
    assert set("123ñ") <= set(rep["missing"])
    assert set("hola") <= set(rep["covered"])
    assert "u" in rep["covered"]
    assert " " not in rep["missing"] and " " not in rep["covered"]
    assert 0.0 < rep["coverage"] < 1.0

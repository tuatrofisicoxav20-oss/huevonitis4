"""Tests del export PDF streaming + iter_pages (Fase 5).

Verifica que iter_pages es un generador perezoso y que export_pages_streaming
produce un PDF carta multipágina sin acumular en RAM (consume el iterador).
"""
import importlib.util
import re

import pytest

_HAS_RL = importlib.util.find_spec("reportlab") is not None
_HAS_PIL = importlib.util.find_spec("PIL") is not None


@pytest.fixture
def renderer():
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.bank import GlyphBank
    from core.inkcore.renderer import HandwritingRenderer
    return HandwritingRenderer(GlyphBank())


@pytest.mark.skipif(not _HAS_PIL, reason="Pillow no instalado")
def test_iter_pages_es_generador_perezoso(renderer):
    import types

    from core.inkcore.renderer import RenderOptions
    texto = "\n\n".join(["palabra " * 40] * 20)
    gen = renderer.iter_pages(texto, RenderOptions(font_size=40))
    assert isinstance(gen, types.GeneratorType)  # no materializa nada todavía
    first = next(gen)
    assert first is not None
    rest = list(gen)
    assert len(rest) >= 1  # produjo varias páginas


@pytest.mark.skipif(not (_HAS_RL and _HAS_PIL), reason="reportlab/Pillow no instalados")
def test_export_streaming_pdf_carta_multipagina(renderer, tmp_path):
    from core.export.pdf_exporter import export_pages_streaming
    from core.inkcore.renderer import RenderOptions

    texto = "\n\n".join(["palabra " * 40] * 30)
    out = tmp_path / "demo.pdf"
    seen = []
    ok = export_pages_streaming(
        renderer.iter_pages(texto, RenderOptions(font_size=40)),
        str(out),
        page_size="letter",
        progress_cb=lambda i, t: seen.append(i),
    )
    assert ok is True
    assert out.exists() and out.stat().st_size > 0
    data = out.read_bytes()
    n_pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    assert n_pages >= 2
    assert seen and seen[-1] == n_pages  # el progreso llegó hasta la última
    # tamaño carta: 612x792 pts
    assert re.search(rb"/MediaBox\s*\[\s*0\s+0\s+612\s+792", data)


@pytest.mark.skipif(not (_HAS_RL and _HAS_PIL), reason="reportlab/Pillow no instalados")
def test_export_streaming_acepta_lista(renderer, tmp_path):
    """El exportador también consume una lista (mapa/documento), no sólo generadores."""
    from PIL import Image

    from core.export.pdf_exporter import export_pages_streaming
    pages = [Image.new("RGB", (620, 877), "white") for _ in range(3)]
    out = tmp_path / "lista.pdf"
    assert export_pages_streaming(pages, str(out)) is True
    assert len(re.findall(rb"/Type\s*/Page[^s]", out.read_bytes())) == 3


@pytest.mark.skipif(not (_HAS_RL and _HAS_PIL), reason="reportlab/Pillow no instalados")
def test_export_streaming_vacio_devuelve_false(tmp_path):
    from core.export.pdf_exporter import export_pages_streaming
    assert export_pages_streaming(iter([]), str(tmp_path / "x.pdf")) is False

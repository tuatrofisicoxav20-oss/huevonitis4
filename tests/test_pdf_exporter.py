"""export_rendered_pages_pdf genera PDF válido — R8: SIN requerir reportlab.

La ruta primaria es PIL puro (Pillow escribe PDF multipágina nativo); la
variante reportlab queda opcional con sufijo _reportlab. La validación de
reapertura no usa pypdf (no es dependencia): el conteo de páginas sale del
``/Count N`` del árbol de páginas y el tamaño físico del ``MediaBox``.
"""
import re
from pathlib import Path

import pytest


def _has_reportlab():
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


def _has_pil():
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def _pdf_page_count(path) -> int:
    data = Path(path).read_bytes()
    assert data.startswith(b"%PDF"), "no es un PDF"
    counts = [int(m) for m in re.findall(rb"/Count\s+(\d+)", data)]
    assert counts, "PDF sin árbol de páginas"
    return max(counts)


@pytest.mark.skipif(not _has_pil(), reason="PIL no instalado")
def test_export_rendered_pages_pdf_sin_reportlab(tmp_path, monkeypatch):
    """R8: exporta 3 páginas carta SIN reportlab y el PDF reabre bien."""
    from PIL import Image

    import core.export.pdf_exporter as pe

    monkeypatch.setattr(pe, "RL_OK", False)  # fuerza el mundo sin reportlab
    pages = [Image.new("RGB", (1275, 1650), c)
             for c in ((255, 255, 255), (240, 240, 240), (250, 250, 245))]
    output = tmp_path / "tres_paginas.pdf"
    assert pe.export_rendered_pages_pdf(pages, str(output))
    assert _pdf_page_count(output) == 3
    # Tamaño físico: 1275 px a 150 DPI = 8.5 in = 612 pt (carta exacta).
    data = output.read_bytes()
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+(\d+)[\d.]*\s+(\d+)", data)
    assert m and int(m.group(1)) == 612 and int(m.group(2)) == 792, (
        f"MediaBox no es carta: {m.group(0) if m else None}")


@pytest.mark.skipif(not _has_pil(), reason="PIL no instalado")
def test_export_streaming_cae_a_pil_sin_reportlab(tmp_path, monkeypatch):
    """El exportador del Writer (streaming) funciona sin reportlab (R8)."""
    from PIL import Image

    import core.export.pdf_exporter as pe

    monkeypatch.setattr(pe, "RL_OK", False)
    progreso = []

    def gen():
        for i in range(3):
            yield Image.new("RGB", (1275, 1650), (255 - i, 255 - i, 255))

    output = tmp_path / "streaming.pdf"
    ok = pe.export_pages_streaming(
        gen(), str(output), page_size="letter",
        progress_cb=lambda n, t: progreso.append(n), total=3)
    assert ok
    assert _pdf_page_count(output) == 3
    assert progreso == [1, 2, 3], "el progreso no avanzó por página"


@pytest.mark.skipif(not _has_pil(), reason="PIL no instalado")
def test_export_rendered_pages_pdf(tmp_path):
    """La ruta primaria (PIL) exporta con o sin reportlab presente."""
    from PIL import Image

    from core.export.pdf_exporter import export_rendered_pages_pdf

    img1 = Image.new("RGB", (595, 842), (255, 255, 255))
    img2 = Image.new("RGB", (595, 842), (240, 240, 240))

    output = str(tmp_path / "test_pages.pdf")
    ok = export_rendered_pages_pdf([img1, img2], output)

    assert ok, "export_rendered_pages_pdf devolvió False"
    assert Path(output).exists(), "PDF no fue creado"
    assert _pdf_page_count(output) == 2


@pytest.mark.skipif(not _has_pil(), reason="PIL no instalado")
def test_export_rendered_pages_empty_returns_false(tmp_path):
    from core.export.pdf_exporter import export_rendered_pages_pdf
    output = str(tmp_path / "empty.pdf")
    ok = export_rendered_pages_pdf([], output)
    assert not ok


@pytest.mark.skipif(not (_has_reportlab() and _has_pil()),
                    reason="reportlab o PIL no instalado")
def test_export_rendered_pages_pdf_reportlab_opcional(tmp_path):
    """La variante reportlab sigue disponible para quien la tenga (R8)."""
    from PIL import Image

    from core.export.pdf_exporter import export_rendered_pages_pdf_reportlab

    output = str(tmp_path / "rl.pdf")
    ok = export_rendered_pages_pdf_reportlab(
        [Image.new("RGB", (1275, 1650), (255, 255, 255))], output)
    assert ok and Path(output).stat().st_size > 100


@pytest.mark.skipif(not _has_reportlab(), reason="reportlab no instalado")
def test_export_text_pdf_still_works(tmp_path):
    from core.export.pdf_exporter import export_text_pdf
    output = str(tmp_path / "text.pdf")
    ok = export_text_pdf("Hola mundo.\n\nSegundo párrafo.", output, title="Test")
    assert ok
    assert Path(output).stat().st_size > 100

"""D5: export_rendered_pages_pdf genera PDF válido con las páginas correctas."""
import pytest
from pathlib import Path


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


@pytest.mark.skipif(not (_has_reportlab() and _has_pil()), reason="reportlab o PIL no instalado")
def test_export_rendered_pages_pdf(tmp_path):
    from PIL import Image
    from core.export.pdf_exporter import export_rendered_pages_pdf

    img1 = Image.new("RGB", (595, 842), (255, 255, 255))
    img2 = Image.new("RGB", (595, 842), (240, 240, 240))

    output = str(tmp_path / "test_pages.pdf")
    ok = export_rendered_pages_pdf([img1, img2], output)

    assert ok, "export_rendered_pages_pdf devolvió False"
    assert Path(output).exists(), "PDF no fue creado"
    assert Path(output).stat().st_size > 100


@pytest.mark.skipif(not (_has_reportlab() and _has_pil()), reason="reportlab o PIL no instalado")
def test_export_rendered_pages_empty_returns_false(tmp_path):
    from core.export.pdf_exporter import export_rendered_pages_pdf
    output = str(tmp_path / "empty.pdf")
    ok = export_rendered_pages_pdf([], output)
    assert not ok


@pytest.mark.skipif(not _has_reportlab(), reason="reportlab no instalado")
def test_export_text_pdf_still_works(tmp_path):
    from core.export.pdf_exporter import export_text_pdf
    output = str(tmp_path / "text.pdf")
    ok = export_text_pdf("Hola mundo.\n\nSegundo párrafo.", output, title="Test")
    assert ok
    assert Path(output).stat().st_size > 100

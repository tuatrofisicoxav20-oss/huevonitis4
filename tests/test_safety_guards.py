"""Tests para garantías de seguridad: borrado restringido y carga de settings."""
import json

import pytest
from PIL import Image


def _make_image(path):
    Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(str(path))
    return str(path)


# ── ProjectManager: no borra imágenes externas ────────────────────────────────


def test_project_delete_keeps_external_images(tmp_path, monkeypatch):
    """delete() debe NO borrar imágenes cuya ruta cae fuera de DATA_DIR."""
    from core.models import ImageElement, Page, Project
    from core.project_manager import ProjectManager

    # Imagen "externa" en una carpeta del usuario, fuera de DATA_DIR
    external_dir = tmp_path.parent / "external_user_files"
    external_dir.mkdir(exist_ok=True)
    external_img = _make_image(external_dir / "user_photo.png")

    pm = ProjectManager()
    proj = Project(name="Con foto externa")
    page = Page(name="Página 1")
    page.elements.append(ImageElement(image_path=external_img, x=0, y=0, width=100, height=100))
    proj.pages.append(page)
    pm.save(proj)

    pm.delete(proj.id)

    # La imagen externa debe seguir existiendo
    from pathlib import Path
    assert Path(external_img).exists(), (
        "Huevonitis NUNCA debe borrar archivos externos a DATA_DIR"
    )


def test_project_delete_removes_internal_images(tmp_path, monkeypatch):
    """delete() SÍ borra imágenes dentro de DATA_DIR."""
    import config
    from core.models import ImageElement, Page, Project
    from core.project_manager import ProjectManager

    # Imagen dentro de DATA_DIR (proyecto)
    internal_img_dir = config.PROJECTS_DIR / "img_assets"
    internal_img_dir.mkdir(parents=True, exist_ok=True)
    internal_img = _make_image(internal_img_dir / "asset.png")

    pm = ProjectManager()
    proj = Project(name="Con asset interno")
    page = Page(name="Página 1")
    page.elements.append(ImageElement(image_path=internal_img, x=0, y=0, width=100, height=100))
    proj.pages.append(page)
    pm.save(proj)

    pm.delete(proj.id)

    from pathlib import Path
    assert not Path(internal_img).exists(), (
        "Imágenes dentro de DATA_DIR deben borrarse al eliminar el proyecto"
    )


# ── GlyphBank: no borra fuera de bank_dir ──────────────────────────────────────


def test_bank_remove_skips_external_path(tmp_path):
    """remove_glyph debe NO tocar archivos fuera de bank_dir aunque el manifest los referencie."""
    import config
    from core.inkcore.bank import GlyphBank
    from core.models import GlyphEntry

    config.ensure_dirs()
    external = tmp_path.parent / "outside_glifo.png"
    Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(str(external))

    bank = GlyphBank()
    fake_entry = GlyphEntry(
        char="x", image_path=str(external), quality_score=0.5,
        tier="Silver", ink_coverage=0.3, index=0,
    )
    bank._entries.append(fake_entry)
    bank.remove_glyph(fake_entry)

    assert external.exists(), "Bank no debe borrar archivos fuera de bank_dir"
    assert fake_entry not in bank._entries, "Pero sí debe quitarlo del manifest"


# ── Settings: min_glyph_quality se carga y aplica al config ───────────────────


def test_settings_min_glyph_quality_loaded(tmp_path, monkeypatch):
    """config.load_settings() debe leer min_glyph_quality de settings.json."""
    import config

    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SETTINGS_FILE.write_text(json.dumps({"min_glyph_quality": 0.42}))

    monkeypatch.setattr(config, "MIN_GLYPH_QUALITY", 0.18)
    config.load_settings()
    assert pytest.approx(0.42) == config.MIN_GLYPH_QUALITY


def test_settings_min_glyph_quality_out_of_range_ignored(tmp_path, monkeypatch):
    """Valores fuera de [0,1] no deben sobrescribir el default."""
    import config

    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SETTINGS_FILE.write_text(json.dumps({"min_glyph_quality": 5.0}))

    monkeypatch.setattr(config, "MIN_GLYPH_QUALITY", 0.18)
    config.load_settings()
    assert pytest.approx(0.18) == config.MIN_GLYPH_QUALITY, (
        "Valores fuera de rango deben ignorarse, no aplicarse"
    )


# ── Ingestion: .doc devuelve mensaje claro, no excepción ─────────────────────


def test_ingestion_old_doc_returns_friendly_message(tmp_path):
    """Cargar un .doc viejo debe devolver Document con mensaje explicativo."""
    from core.ocr.ingestion import DocumentIngestion

    fake_doc = tmp_path / "old_format.doc"
    fake_doc.write_bytes(b"\xd0\xcf\x11\xe0FAKE_OLE")  # firma de OLE/DOC

    ingestion = DocumentIngestion(ocr_backend=None)
    doc = ingestion.ingest(str(fake_doc))

    assert doc.source_type == "unsupported"
    assert len(doc.pages) == 1
    text = " ".join(b.text for b in doc.pages[0].blocks)
    assert ".doc" in text.lower() or "no es compatible" in text.lower()

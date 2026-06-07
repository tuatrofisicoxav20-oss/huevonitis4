"""Tests de captura masiva de glifos (Fase 2)."""
import pytest
from PIL import Image


def _make_png(path, text_char="a"):
    img = Image.new("RGBA", (32, 32), (255, 255, 255, 255))
    img.save(str(path))
    return str(path)


def _make_bank(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()
    from core.inkcore.bank import GlyphBank
    bank = GlyphBank()
    bank.bank_dir = tmp_path / "bank"
    bank.bank_dir.mkdir(exist_ok=True)
    bank.manifest_file = bank.bank_dir / "manifest.json"
    bank._entries = []
    return bank


def test_bulk_session_stats_counting():
    from core.inkcore.bulk_capture import BulkCaptureSession, BulkGlyphCandidate
    from core.models import GlyphEntry

    def _g(char):
        return GlyphEntry(char=char, image_path="", quality_score=0.9,
                          tier="Gold", ink_coverage=0.5, index=0)

    session = BulkCaptureSession(sources=[])
    session.candidates = [
        BulkGlyphCandidate(glyph=_g("a"), source_image="x", source_page_num=1,
                           decision="approved"),
        BulkGlyphCandidate(glyph=_g("b"), source_image="x", source_page_num=1,
                           decision="rejected"),
        BulkGlyphCandidate(glyph=_g("c"), source_image="x", source_page_num=1,
                           decision="pending"),
        BulkGlyphCandidate(glyph=_g("d"), source_image="x", source_page_num=1,
                           decision="pending"),
    ]
    s = session.stats()
    assert s["total"] == 4
    assert s["approved"] == 1
    assert s["rejected"] == 1
    assert s["pending"] == 2


def test_bulk_candidate_display_char_priority():
    from core.inkcore.bulk_capture import BulkGlyphCandidate
    from core.models import GlyphEntry

    g = GlyphEntry(char="x", image_path="", quality_score=0.8, tier="Gold",
                   ink_coverage=0.4, index=0,
                   predicted_char="a", label_confidence=0.9)

    cand = BulkGlyphCandidate(glyph=g, source_image="", source_page_num=1)
    assert cand.display_char == "a"  # predicted_char > char

    cand.user_label = "z"
    assert cand.display_char == "z"  # user_label > predicted_char


def test_bulk_candidate_needs_review():
    from core.inkcore.bulk_capture import BulkGlyphCandidate
    from core.models import GlyphEntry

    def _g(tier, conf):
        return GlyphEntry(char="a", image_path="", quality_score=0.8,
                          tier=tier, ink_coverage=0.4, index=0,
                          label_confidence=conf)

    high = BulkGlyphCandidate(glyph=_g("Gold", 0.9), source_image="", source_page_num=1)
    low = BulkGlyphCandidate(glyph=_g("Bronze", 0.5), source_image="", source_page_num=1)
    no_conf = BulkGlyphCandidate(glyph=_g("Silver", None), source_image="", source_page_num=1)

    assert not high.needs_review
    assert low.needs_review
    assert no_conf.needs_review


def test_bulk_runner_processes_multiple_images(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    img1 = _make_png(tmp_path / "img1.png")
    img2 = _make_png(tmp_path / "img2.png")

    from core.inkcore.bulk_capture import BulkCaptureRunner
    from core.inkcore.extraction_pipeline import PipelineConfig

    cfg = PipelineConfig(detectors=["classic_cv"], labelers=[])
    runner = BulkCaptureRunner(cfg)
    session = runner.run([img1, img2])

    assert session.sources == [img1, img2]
    assert isinstance(session.candidates, list)
    # Imágenes sintéticas blancas pueden producir 0 glifos (no hay tinta),
    # pero la sesión debe completar sin error
    s = session.stats()
    assert s["total"] == len(session.candidates)
    assert s["total"] >= 0


def test_bulk_runner_handles_nonexistent_files(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    from core.inkcore.bulk_capture import BulkCaptureRunner
    from core.inkcore.extraction_pipeline import PipelineConfig

    cfg = PipelineConfig(detectors=["classic_cv"], labelers=[])
    runner = BulkCaptureRunner(cfg)
    session = runner.run(["/nonexistent/path.png"])
    assert isinstance(session.candidates, list)


def test_bulk_candidate_source_label():
    """source_label es legible y distinto de source_image (path)."""
    from core.inkcore.bulk_capture import BulkGlyphCandidate
    from core.models import GlyphEntry

    g = GlyphEntry(char="a", image_path="/tmp/a.png", quality_score=0.8,
                   tier="Gold", ink_coverage=0.4, index=0)
    cand = BulkGlyphCandidate(
        glyph=g, source_image="/tmp/page_1_abc.png",
        source_page_num=3, source_label="Página 3",
    )
    assert cand.source_label == "Página 3"
    assert cand.source_page_num == 3


def test_bulk_session_new_fields():
    """BulkCaptureSession lleva is_pdf, total_pages, elapsed_s."""
    from core.inkcore.bulk_capture import BulkCaptureSession
    s = BulkCaptureSession(sources=["test.pdf"], is_pdf=True, total_pages=6, elapsed_s=12.3)
    assert s.is_pdf
    assert s.total_pages == 6
    assert s.elapsed_s == pytest.approx(12.3)


def test_bulk_runner_run_pdf_cancellation(tmp_path, monkeypatch):
    """run_pdf con cancel activo aborta limpiamente sin candidatos."""
    import sys
    import threading
    from unittest.mock import MagicMock

    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    config.ensure_dirs()

    # Inyectar pdf2image falso en sys.modules (puede no estar instalado)
    mock_pdf2image = MagicMock()
    mock_pdf2image.pdfinfo_from_path.return_value = {"Pages": 10}
    mock_pdf2image.convert_from_path.return_value = []
    monkeypatch.setitem(sys.modules, "pdf2image", mock_pdf2image)

    cancel = threading.Event()
    cancel.set()  # cancelar de inmediato

    from core.inkcore.bulk_capture import BulkCaptureRunner
    from core.inkcore.extraction_pipeline import PipelineConfig

    cfg = PipelineConfig(detectors=["classic_cv"], labelers=[])
    runner = BulkCaptureRunner(cfg, cancel_event=cancel)
    session = runner.run_pdf("fake.pdf")

    assert session.is_pdf
    assert len(session.candidates) == 0


def test_bulk_commit_preserves_metadata(tmp_path, monkeypatch):
    """Aprobados al banco guardan predicted_char y demás metadatos."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    bank = _make_bank(tmp_path, monkeypatch)

    src = tmp_path / "tipo" / "glifo.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(str(src))

    from core.inkcore.bulk_capture import BulkCaptureSession, BulkGlyphCandidate
    from core.models import GlyphEntry

    g = GlyphEntry(
        char="a", image_path=str(src), quality_score=0.85,
        tier="Gold", ink_coverage=0.4, index=0,
        predicted_char="a", label_confidence=0.93,
        detector_sources=["classic_cv"],
    )
    cand = BulkGlyphCandidate(glyph=g, source_image=str(src), source_page_num=1,
                               decision="approved")
    session = BulkCaptureSession(sources=[str(src)], candidates=[cand])

    for c in session.candidates:
        entry = bank.add_glyph(
            c.display_char, c.glyph.image_path,
            predicted_char=c.glyph.predicted_char,
            label_confidence=c.glyph.label_confidence,
            detector_sources=c.glyph.detector_sources,
            quality_override={
                "score": c.glyph.quality_score,
                "tier": c.glyph.tier,
                "ink_coverage": c.glyph.ink_coverage,
            },
        )
    assert entry is not None
    assert entry.predicted_char == "a"
    assert entry.label_confidence == pytest.approx(0.93)
    assert "classic_cv" in entry.detector_sources

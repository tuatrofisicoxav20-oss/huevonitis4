"""D3: verifica que ExtractionOptions puede llevar pipeline_config."""
from core.inkcore.extractor import ExtractionOptions
from core.inkcore.extraction_pipeline import PipelineConfig


def test_extraction_options_includes_pipeline_config():
    cfg = PipelineConfig(detectors=["classic_cv"], labelers=["tesseract_labeler"])
    opts = ExtractionOptions(use_pipeline=True, pipeline_config=cfg)
    assert opts.use_pipeline is True
    assert opts.pipeline_config is not None
    assert "tesseract_labeler" in opts.pipeline_config.labelers


def test_default_pipeline_config_follows_config_detector(monkeypatch):
    """Paso 3 — config.GLYPH_DETECTOR es la fuente única de verdad del detector."""
    import config
    from core.inkcore.extractor import _build_default_pipeline_config

    monkeypatch.setattr(config, "GLYPH_DETECTOR", "classic_cv")
    assert _build_default_pipeline_config().detectors == ["classic_cv"]

    # Otro detector → se fusiona con classic_cv (classic_cv siempre como base).
    monkeypatch.setattr(config, "GLYPH_DETECTOR", "easyocr")
    dets = _build_default_pipeline_config().detectors
    assert "easyocr" in dets and "classic_cv" in dets


def test_extraction_options_default_pipeline_on():
    # F6 — actualizado: el default de use_pipeline cambió de False a True
    # (ensemble por defecto, con fallback automático a legacy). pipeline_config
    # sigue siendo None por defecto: se construye un PipelineConfig() al vuelo.
    opts = ExtractionOptions()
    assert opts.use_pipeline is True
    assert opts.pipeline_config is None

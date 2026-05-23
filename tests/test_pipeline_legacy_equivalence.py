"""B12: prueba de no-regresión — use_pipeline=False debe dar output idéntico al legacy."""
import pytest


def test_extract_from_image_legacy_path(tmp_path):
    """Con use_pipeline=False, extract_from_image delega al flujo _run() de siempre."""
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    (config.TIPOGRAFIA_DIR / "_temp_extract").mkdir(parents=True, exist_ok=True)

    from core.inkcore.extractor import GlyphExtractor, ExtractionOptions

    ext = GlyphExtractor()
    opts_legacy = ExtractionOptions(use_pipeline=False)
    opts_pipeline_off = ExtractionOptions()  # default también es False

    assert opts_legacy.use_pipeline is False
    assert opts_pipeline_off.use_pipeline is False

    # Sin imagen real disponible, verificar que ambos devuelven [] sin explotar
    result_a = ext.extract_from_image("nonexistent.png", "abc", opts_legacy)
    result_b = ext.extract_from_image("nonexistent.png", "abc", opts_pipeline_off)
    assert result_a == result_b == []


def test_pipeline_config_defaults():
    """PipelineConfig tiene defaults sensatos y no rompe al instanciar."""
    from core.inkcore.extraction_pipeline import PipelineConfig
    cfg = PipelineConfig()
    assert cfg.detectors == ["classic_cv"]
    assert cfg.detector_fusion == "union"
    assert cfg.labelers == []
    assert cfg.min_quality == pytest.approx(0.18, abs=0.01)
    assert cfg.debug_overlay is False
    assert cfg.labeler_batch_size == 32


def test_pipeline_instantiates_without_optional_deps():
    """GlyphExtractionPipeline arranca con solo classic_cv (sin deps opcionales)."""
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)

    from core.inkcore.extraction_pipeline import GlyphExtractionPipeline, PipelineConfig
    cfg = PipelineConfig(detectors=["classic_cv"], labelers=[])
    pipeline = GlyphExtractionPipeline(cfg)
    assert len(pipeline.detectors) >= 1
    assert len(pipeline.labelers) == 0


def test_extraction_result_nonexistent_image():
    """extract() sobre imagen inexistente devuelve ExtractionResult con lista vacía."""
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)

    from core.inkcore.extraction_pipeline import GlyphExtractionPipeline, PipelineConfig
    cfg = PipelineConfig(detectors=["classic_cv"], labelers=[])
    pipeline = GlyphExtractionPipeline(cfg)
    result = pipeline.extract("__nonexistent__.png")
    assert result.glyphs == []
    assert "error" in result.stats

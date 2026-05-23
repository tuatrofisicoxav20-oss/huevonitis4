"""D3: verifica que ExtractionOptions puede llevar pipeline_config."""
from core.inkcore.extractor import ExtractionOptions
from core.inkcore.extraction_pipeline import PipelineConfig


def test_extraction_options_includes_pipeline_config():
    cfg = PipelineConfig(detectors=["classic_cv"], labelers=["tesseract_labeler"])
    opts = ExtractionOptions(use_pipeline=True, pipeline_config=cfg)
    assert opts.use_pipeline is True
    assert opts.pipeline_config is not None
    assert "tesseract_labeler" in opts.pipeline_config.labelers


def test_extraction_options_default_no_pipeline():
    opts = ExtractionOptions()
    assert opts.use_pipeline is False
    assert opts.pipeline_config is None

"""Smoke test for InkCorePipeline instantiation."""
import pytest


def test_pipeline_instantiates(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.pipeline import InkCorePipeline
    pipeline = InkCorePipeline()
    assert pipeline is not None


def test_pipeline_has_bank(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.pipeline import InkCorePipeline
    pipeline = InkCorePipeline()
    assert pipeline.bank is not None


def test_pipeline_coverage(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.pipeline import InkCorePipeline
    pipeline = InkCorePipeline()
    cov = pipeline.bank.coverage()
    assert "total_glyphs" in cov
    assert isinstance(cov["total_glyphs"], int)


def test_pipeline_reload_bank(tmp_path):
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    from core.inkcore.pipeline import InkCorePipeline
    pipeline = InkCorePipeline()
    pipeline.reload_bank()
    assert pipeline.bank is not None

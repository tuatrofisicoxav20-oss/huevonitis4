"""Tests end-to-end con fotos reales de letra manuscrita.

Marcados @slow — no corren en `pytest tests/` por defecto.
Correr con:
    pytest tests/test_e2e_extraction.py -m slow -v

Si no hay fixtures en tests/fixtures/handwriting/, se saltean limpiamente.
"""
import json
import time
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "handwriting"
EXPECTATIONS_FILE = FIXTURES_DIR / "expectations.json"


def _load_expectations() -> dict:
    """BUG-03: NO llamar pytest.skip aquí — rompe la colección de TODO el módulo
    cuando se invoca desde _list_fixtures() en parse-time."""
    if not EXPECTATIONS_FILE.exists():
        return {}
    try:
        with open(EXPECTATIONS_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("fixtures", {})


def _list_fixtures():
    exp = _load_expectations()
    if not exp:
        return []
    params = []
    for name in exp:
        path = FIXTURES_DIR / name
        if path.exists():
            params.append(pytest.param(name, id=name))
    return params


_FIXTURES = _list_fixtures()


@pytest.mark.slow
@pytest.mark.skipif(not _FIXTURES, reason="Sin fixtures en tests/fixtures/handwriting/")
@pytest.mark.parametrize("fixture_name", _FIXTURES or [pytest.param("dummy", id="skipped")])
def test_legacy_extraction_meets_minimum(fixture_name, tmp_path, monkeypatch):
    """El extractor legacy extrae al menos N glifos del fixture."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    exp = _load_expectations()[fixture_name]

    from core.inkcore.extractor import ExtractionOptions
    from core.inkcore.pipeline import InkCorePipeline

    pipeline = InkCorePipeline()
    t0 = time.perf_counter()
    glyphs = pipeline.extract(
        str(FIXTURES_DIR / fixture_name), "",
        ExtractionOptions(use_pipeline=False),
    )
    elapsed = time.perf_counter() - t0

    assert len(glyphs) >= exp["expected_min_glyphs_legacy"], (
        f"Legacy: {len(glyphs)} glifos, esperado >= {exp['expected_min_glyphs_legacy']}"
    )
    assert elapsed <= exp["expected_max_seconds_legacy"], (
        f"Legacy tardó {elapsed:.1f}s, límite {exp['expected_max_seconds_legacy']}s"
    )


@pytest.mark.slow
@pytest.mark.parametrize("fixture_name", _list_fixtures())
def test_ensemble_extraction_meets_minimum(fixture_name, tmp_path, monkeypatch):
    """El pipeline ensemble extrae al menos N glifos."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    exp = _load_expectations()[fixture_name]

    from core.inkcore import glyph_detectors
    from core.inkcore.extraction_pipeline import PipelineConfig
    from core.inkcore.extractor import ExtractionOptions
    from core.inkcore.pipeline import InkCorePipeline

    available = glyph_detectors.get_available()
    dets = ["classic_cv"]
    if available.get("craft"):
        dets.append("craft")

    cfg = PipelineConfig(detectors=dets, labelers=[], detector_fusion="union")
    pipeline = InkCorePipeline()

    t0 = time.perf_counter()
    glyphs = pipeline.extract(
        str(FIXTURES_DIR / fixture_name), "",
        ExtractionOptions(use_pipeline=True, pipeline_config=cfg),
    )
    elapsed = time.perf_counter() - t0

    assert len(glyphs) >= exp["expected_min_glyphs_ensemble"], (
        f"Ensemble: {len(glyphs)} glifos, esperado >= {exp['expected_min_glyphs_ensemble']}"
    )
    assert elapsed <= exp["expected_max_seconds_ensemble"], (
        f"Ensemble tardó {elapsed:.1f}s, límite {exp['expected_max_seconds_ensemble']}s"
    )


@pytest.mark.slow
@pytest.mark.parametrize("fixture_name", _list_fixtures())
def test_quality_distribution(fixture_name, tmp_path, monkeypatch):
    """Al menos X% de glifos deben ser Gold."""
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()

    exp = _load_expectations()[fixture_name]

    from core.inkcore.extractor import ExtractionOptions
    from core.inkcore.pipeline import InkCorePipeline

    pipeline = InkCorePipeline()
    glyphs = pipeline.extract(
        str(FIXTURES_DIR / fixture_name), "",
        ExtractionOptions(use_pipeline=False),
    )
    if not glyphs:
        pytest.fail("Cero glifos extraídos del fixture")

    gold = sum(1 for g in glyphs if g.tier == "Gold")
    ratio = gold / len(glyphs)
    assert ratio >= exp["expected_min_gold_ratio"], (
        f"Gold ratio {ratio:.2f}, esperado >= {exp['expected_min_gold_ratio']}"
    )

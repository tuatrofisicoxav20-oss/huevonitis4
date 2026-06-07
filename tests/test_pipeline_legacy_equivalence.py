"""B12: prueba de no-regresión — use_pipeline=False debe dar output idéntico al legacy."""
import pytest


def test_extract_from_image_legacy_path(tmp_path):
    """Con use_pipeline=False, extract_from_image delega al flujo _run() de siempre."""
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    (config.TIPOGRAFIA_DIR / "_temp_extract").mkdir(parents=True, exist_ok=True)

    from core.inkcore.extractor import ExtractionOptions, GlyphExtractor

    ext = GlyphExtractor()
    opts_legacy = ExtractionOptions(use_pipeline=False)
    opts_default = ExtractionOptions()  # F6: el default AHORA es use_pipeline=True

    assert opts_legacy.use_pipeline is False
    # F6 — actualizado: el default cambió a True (ensemble por defecto). El path
    # legacy se obtiene explícitamente con use_pipeline=False.
    assert opts_default.use_pipeline is True

    # Sin imagen real disponible, ambos caminos devuelven [] sin explotar: el
    # legacy porque el archivo no existe; el ensemble porque cae a legacy (0
    # glifos / error de lectura) y este también devuelve [].
    result_a = ext.extract_from_image("nonexistent.png", "abc", opts_legacy)
    result_b = ext.extract_from_image("nonexistent.png", "abc", opts_default)
    assert result_a == result_b == []


def test_pipeline_zero_glyphs_falls_back_to_legacy(tmp_path, monkeypatch):
    """F6 — si el ensemble devuelve 0 glifos, extract_from_image cae a legacy."""
    import config
    config.TIPOGRAFIA_DIR.mkdir(parents=True, exist_ok=True)
    (config.TIPOGRAFIA_DIR / "_temp_extract").mkdir(parents=True, exist_ok=True)

    from core.inkcore import extraction_pipeline as ep
    from core.inkcore.extractor import ExtractionOptions, GlyphExtractor
    from core.models import GlyphEntry

    # Pipeline falso que SIEMPRE devuelve 0 glifos.
    class _EmptyPipeline:
        def __init__(self, cfg):
            pass

        def extract(self, image_path, reference_text=""):
            return ep.ExtractionResult(glyphs=[], stats={})

    monkeypatch.setattr(ep, "GlyphExtractionPipeline", _EmptyPipeline)

    ext = GlyphExtractor()
    sentinel = [GlyphEntry(char="z", image_path="x.png", quality_score=0.9,
                           tier="Gold", ink_coverage=0.5, index=0)]
    # Espiar el path legacy: si se invoca, devuelve el sentinel.
    monkeypatch.setattr(ext, "_run", lambda *a, **k: sentinel)
    # El fallback exige que la imagen exista para llegar a _run.
    img = tmp_path / "real.png"
    from PIL import Image
    Image.new("RGB", (10, 10), (255, 255, 255)).save(str(img))

    result = ext.extract_from_image(str(img), "abc",
                                    ExtractionOptions(use_pipeline=True))
    assert result is sentinel, "el fallback por 0 glifos no invocó el legacy"


def test_pipeline_config_defaults():
    """PipelineConfig tiene defaults sensatos y no rompe al instanciar.

    F6 — actualizado: los defaults del ensemble cambiaron. labelers ahora trae
    ambos labelers y el voting es por consenso (verificación cruzada). Esto
    refleja el ensemble activado por defecto, no el placeholder vacío anterior.
    """
    from core.inkcore.extraction_pipeline import PipelineConfig
    cfg = PipelineConfig()
    assert cfg.detectors == ["classic_cv"]
    assert cfg.detector_fusion == "union"
    assert cfg.labelers == ["tesseract_labeler", "trocr_labeler"]
    assert cfg.labeler_voting == "consensus"
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

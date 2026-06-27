"""Smoke test for InkCorePipeline instantiation."""


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


def test_prune_stale_extract_dirs_preserva_recientes_borra_viejos(tmp_path):
    """La higiene de huérfanos NO debe tocar subdirs recientes (hilos/páginas en
    curso); sólo poda los viejos (extracciones abandonadas de sesiones previas).

    Regresión del bug de captura masiva: antes se compartía _temp_extract y se
    purgaban TODOS los PNG al inicio de cada extract(), destruyendo los crops de
    páginas/hilos concurrentes. Ahora cada extract() usa su subdir único y sólo
    se podan los viejos por antigüedad.
    """
    import os
    import time

    from core.inkcore.extraction_pipeline import _prune_stale_extract_dirs
    base = tmp_path / "_temp_extract"
    base.mkdir()
    reciente = base / "ex_reciente"
    reciente.mkdir()
    (reciente / "a_0001.png").write_bytes(b"x")
    viejo = base / "ex_viejo"
    viejo.mkdir()
    (viejo / "a_0001.png").write_bytes(b"x")
    past = time.time() - 7200          # 2 h atrás
    os.utime(viejo, (past, past))
    removed = _prune_stale_extract_dirs(base, ttl_s=3600)
    assert removed == 1
    assert reciente.exists(), "un subdir reciente (hilo concurrente) NO debe podarse"
    assert not viejo.exists(), "un subdir viejo (huérfano) debe podarse"

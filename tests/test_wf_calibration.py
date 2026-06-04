"""Salto 4 — calibración de wf a la letra del usuario."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_tipo(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "TIPOGRAFIA_DIR", tmp_path / "tipo")
    config.ensure_dirs()
    from core.inkcore import wf_calibration
    wf_calibration.invalidate()
    yield
    wf_calibration.invalidate()


def test_learned_wf_overrides_table_after_enough_samples():
    from core.inkcore import wf_calibration
    from core.inkcore.extractor_align_basic import wf

    # La tabla fija da 0.40 para 'i'. Simulamos 5 muestras consistentes de 0.90
    # (una 'i' anormalmente ancha para este usuario).
    for _ in range(5):
        wf_calibration.record("i", 0.90)
    wf_calibration.flush()
    wf_calibration.invalidate()  # forzar recarga desde disco

    # wf debe devolver el valor APRENDIDO (mediana ≈ 0.90), no el de tabla 0.40.
    assert wf("i") == pytest.approx(0.90, abs=1e-3)
    # Un char sin muestras cae a la tabla fija.
    assert wf("z") == pytest.approx(0.72, abs=1e-3)


def test_below_min_samples_falls_back_to_table():
    from core.inkcore import wf_calibration
    from core.inkcore.extractor_align_basic import wf

    # Solo 2 muestras (< MIN_SAMPLES=3) → no se confía, cae a tabla.
    wf_calibration.record("i", 0.90)
    wf_calibration.record("i", 0.92)
    wf_calibration.flush()
    wf_calibration.invalidate()
    assert wf("i") == pytest.approx(0.40, abs=1e-3)  # tabla, no aprendido


def test_median_resists_outlier():
    from core.inkcore import wf_calibration

    # 4 muestras ~0.80 + 1 outlier 2.0 → mediana ≈ 0.80, no la arrastra el outlier.
    for w in (0.78, 0.80, 0.81, 0.79, 2.0):
        wf_calibration.record("a", w)
    wf_calibration.flush()
    wf_calibration.invalidate()
    learned = wf_calibration.learned_wf("a")
    assert 0.75 <= learned <= 0.85


def test_out_of_range_samples_rejected():
    from core.inkcore import wf_calibration
    # Muestras absurdas (ruido de segmentación) no se registran.
    wf_calibration.record("a", 0.0)
    wf_calibration.record("a", 50.0)
    assert wf_calibration.learned_wf("a", min_samples=1) is None


def test_persistence_round_trip():
    from core.inkcore import wf_calibration
    for _ in range(3):
        wf_calibration.record("m", 1.45)
    wf_calibration.flush()
    wf_calibration.invalidate()
    # Tras recargar desde disco, las muestras siguen ahí.
    assert wf_calibration.learned_wf("m") == pytest.approx(1.45, abs=1e-3)
    assert wf_calibration.stats().get("m") == 3

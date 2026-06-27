"""Tests for businesscore estimator."""
import pytest

from core.businesscore.estimator import calculate_price, get_price_breakdown
from core.models import ClientJob


def test_price_normal_apunte(monkeypatch):
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job = ClientJob(pages=1, urgency="Normal", job_type="Apunte")
    price = calculate_price(job)
    assert price > 0
    assert price == round(50.0 * 1 * 1.0 * 1.0 * (1.0 + 1 * 0.015), 2)


def test_price_urgente_tarea(monkeypatch):
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job = ClientJob(pages=5, urgency="Urgente", job_type="Tarea")
    price = calculate_price(job)
    assert price > calculate_price(ClientJob(pages=5, urgency="Normal", job_type="Tarea"))


def test_price_ultra_urgente(monkeypatch):
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job_normal = ClientJob(pages=3, urgency="Normal", job_type="Apunte")
    job_ultra = ClientJob(pages=3, urgency="Ultra-urgente", job_type="Apunte")
    assert calculate_price(job_ultra) > calculate_price(job_normal)


def test_price_guard_pages_zero(monkeypatch):
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job = ClientJob(pages=0, urgency="Normal", job_type="Apunte")
    price = calculate_price(job)
    assert price > 0  # pages clamped to 1


def test_price_guard_pages_negative(monkeypatch):
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job = ClientJob(pages=-5, urgency="Normal", job_type="Apunte")
    price = calculate_price(job)
    assert price > 0  # pages clamped to 1


def test_breakdown_keys(monkeypatch):
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job = ClientJob(pages=3, urgency="Urgente", job_type="Guía")
    bd = get_price_breakdown(job)
    assert "base" in bd
    assert "total" in bd
    assert "urgency_multiplier" in bd
    assert bd["urgency_multiplier"] == 1.5
    assert bd["type_multiplier"] == 1.3


@pytest.mark.parametrize("urgency,expected_mult", [
    ("Normal", 1.0),
    ("Urgente", 1.5),
    ("Ultra-urgente", 2.2),
])
def test_all_urgencies(monkeypatch, urgency, expected_mult):
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job = ClientJob(pages=2, urgency=urgency, job_type="Apunte")
    bd = get_price_breakdown(job)
    assert bd["urgency_multiplier"] == expected_mult


@pytest.mark.parametrize("job_type", ["Apunte", "Tarea", "Guía", "Resumen", "Otro"])
def test_all_job_types(monkeypatch, job_type):
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job = ClientJob(pages=1, urgency="Normal", job_type=job_type)
    assert calculate_price(job) > 0


@pytest.mark.parametrize("bad", ["", None, "tres", "  ", "abc"])
def test_price_pages_no_numerico_no_truena(monkeypatch, bad):
    """pages vacío/None/no numérico desde el formulario → 1 página, sin crash.

    Antes int(job.pages) lanzaba ValueError/TypeError y tumbaba la cotización.
    """
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    job = ClientJob(pages=bad, urgency="Normal", job_type="Apunte")
    price = calculate_price(job)
    assert price == calculate_price(ClientJob(pages=1, urgency="Normal", job_type="Apunte"))
    # y el desglose tampoco truena (mismo total que 1 página)
    assert get_price_breakdown(job)["total"] == \
        get_price_breakdown(ClientJob(pages=1, urgency="Normal", job_type="Apunte"))["total"]


def test_price_pages_float_string(monkeypatch):
    """'3.0' o '3 ' se normalizan a 3 páginas."""
    import config
    monkeypatch.setattr(config, "BASE_PRICE_PER_PAGE_MXN", 50.0)
    assert calculate_price(ClientJob(pages="3.0", urgency="Normal", job_type="Apunte")) == \
        calculate_price(ClientJob(pages=3, urgency="Normal", job_type="Apunte"))

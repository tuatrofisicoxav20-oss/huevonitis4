"""Tests for BusinessLedger: CRUD, monthly_income, _parse_payment_date."""
import pytest

from core.models import ClientJob, Payment


@pytest.fixture
def ledger():
    from core.businesscore.ledger import BusinessLedger
    return BusinessLedger()


def test_add_and_get_job(ledger):
    job = ClientJob(client_name="Ana", pages=3)
    ledger.add_job(job)
    jobs = ledger.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].client_name == "Ana"


def test_update_job(ledger):
    job = ClientJob(client_name="Pedro", pages=2)
    ledger.add_job(job)
    job.client_name = "Pedro Modificado"
    ledger.update_job(job)
    jobs = ledger.get_jobs()
    assert jobs[0].client_name == "Pedro Modificado"


def test_delete_job(ledger):
    job = ClientJob(client_name="Temp")
    ledger.add_job(job)
    ledger.delete_job(job.id)
    assert len(ledger.get_jobs()) == 0


def test_add_payment(ledger):
    pay = Payment(client_name="Luis", amount=150.0)
    ledger.add_payment(pay)
    payments = ledger.get_payments()
    assert len(payments) == 1
    assert payments[0].amount == 150.0


def test_total_income(ledger):
    ledger.add_payment(Payment(amount=100.0))
    ledger.add_payment(Payment(amount=200.0))
    assert ledger.total_income() == 300.0


def test_monthly_income(ledger):
    p1 = Payment(amount=100.0, date="15/01/2026")
    p2 = Payment(amount=50.0, date="20/01/2026")
    p3 = Payment(amount=200.0, date="05/02/2026")
    for p in [p1, p2, p3]:
        ledger.add_payment(p)
    assert ledger.monthly_income(2026, 1) == 150.0
    assert ledger.monthly_income(2026, 2) == 200.0
    assert ledger.monthly_income(2026, 3) == 0.0


def test_parse_payment_date_formats(ledger):
    valid_dates = ["15/01/2026", "2026-01-15", "2026-01-15T10:30:00"]
    for d in valid_dates:
        result = ledger._parse_payment_date(d)
        assert result is not None, f"Failed to parse: {d}"


def test_parse_payment_date_invalid(ledger):
    result = ledger._parse_payment_date("not-a-date")
    assert result is None


def test_data_persists_on_reload(ledger, tmp_path):
    job = ClientJob(client_name="Persistido")
    ledger.add_job(job)
    from core.businesscore.ledger import BusinessLedger
    ledger2 = BusinessLedger()
    jobs = ledger2.get_jobs()
    assert any(j.client_name == "Persistido" for j in jobs)


def test_active_jobs_count(ledger):
    ledger.add_job(ClientJob(status="En Progreso"))
    ledger.add_job(ClientJob(status="Aceptado"))
    ledger.add_job(ClientJob(status="Pagado"))
    assert ledger.active_jobs_count() == 2

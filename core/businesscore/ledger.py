import json
import logging
import os
import tempfile
from datetime import datetime

import config
from core.businesscore.models import ClientJob, Payment

logger = logging.getLogger(__name__)


class BusinessLedger:
    def __init__(self):
        config.BUSINESS_DIR.mkdir(parents=True, exist_ok=True)
        self.jobs_file = config.BUSINESS_DIR / "jobs.json"
        self.payments_file = config.BUSINESS_DIR / "payments.json"
        self._jobs: list[ClientJob] = []
        self._payments: list[Payment] = []
        self.load()

    def load(self):
        if self.jobs_file.exists():
            try:
                with open(self.jobs_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._jobs = [self._job_from_dict(d) for d in data]
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.error(f"Error loading jobs: {e}", exc_info=True)
                self._jobs = []
        if self.payments_file.exists():
            try:
                with open(self.payments_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._payments = [self._payment_from_dict(d) for d in data]
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.error(f"Error loading payments: {e}", exc_info=True)
                self._payments = []

    def _atomic_write(self, target_path, data):
        """Write JSON atomically: write to tmp then rename to avoid partial-write corruption."""
        dir_ = target_path.parent
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, target_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def save(self):
        self._atomic_write(self.jobs_file, [j.__dict__ for j in self._jobs])
        self._atomic_write(self.payments_file, [p.__dict__ for p in self._payments])

    def add_job(self, job: ClientJob):
        self._jobs.append(job)
        self.save()

    def update_job(self, job: ClientJob):
        job.touch()
        for i, j in enumerate(self._jobs):
            if j.id == job.id:
                self._jobs[i] = job
                break
        self.save()

    def delete_job(self, job_id: str):
        self._jobs = [j for j in self._jobs if j.id != job_id]
        self.save()

    def get_jobs(self) -> list[ClientJob]:
        """Return jobs sorted by creation date (oldest first); UI uses reversed() for newest-first."""
        def _sort_key(j):
            try:
                return datetime.fromisoformat(j.created_at)
            except (ValueError, TypeError):
                return datetime.min
        return sorted(self._jobs, key=_sort_key)

    def get_job(self, job_id: str) -> ClientJob | None:
        for j in self._jobs:
            if j.id == job_id:
                return j
        return None

    def add_payment(self, payment: Payment):
        self._payments.append(payment)
        self.save()

    def get_payments(self) -> list[Payment]:
        """Return payments sorted by date (oldest first); UI uses reversed() for newest-first."""
        def _sort_key(p):
            dt = self._parse_payment_date(p.date)
            return dt if dt is not None else datetime.min
        return sorted(self._payments, key=_sort_key)

    def get_payments_for_job(self, job_id: str) -> list[Payment]:
        return [p for p in self._payments if p.job_id == job_id]

    def total_income(self) -> float:
        return round(sum(p.amount for p in self._payments), 2)

    def _parse_payment_date(self, date_str: str) -> datetime | None:
        """Parse a payment date in dd/mm/YYYY or ISO 8601 format. Returns None on failure."""
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    def monthly_income(self, year: int, month: int) -> float:
        """Sum payments whose date matches the given year AND month exactly."""
        total = 0.0
        for p in self._payments:
            dt = self._parse_payment_date(p.date)
            if dt is not None and dt.year == year and dt.month == month:
                total += p.amount
        return round(total, 2)

    def active_jobs_count(self) -> int:
        active = {"Aceptado", "En Progreso", "Revisión"}
        return sum(1 for j in self._jobs if j.status in active)

    def _job_from_dict(self, d: dict) -> ClientJob:
        job = ClientJob()
        for k, v in d.items():
            if hasattr(job, k):
                setattr(job, k, v)
        return job

    def _payment_from_dict(self, d: dict) -> Payment:
        pay = Payment()
        for k, v in d.items():
            if hasattr(pay, k):
                setattr(pay, k, v)
        return pay

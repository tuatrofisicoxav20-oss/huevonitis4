from core.models import ClientJob, JobStatus, JobType, Payment, Urgency

__all__ = ["ClientJob", "Payment", "JOB_STATUSES", "JOB_TYPES", "URGENCIES"]

JOB_STATUSES = [s.value for s in JobStatus]
JOB_TYPES = [t.value for t in JobType]
URGENCIES = [u.value for u in Urgency]

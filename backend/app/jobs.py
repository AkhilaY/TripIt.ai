import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import Job, JobStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobStore:
    """In-memory job store. Fine for a single personal server; jobs are lost on restart,
    which is OK because the app keeps the reel URL and can resubmit it."""

    def __init__(self, ttl_hours: int = 24):
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._ttl = timedelta(hours=ttl_hours)

    async def create(self, url: str) -> tuple[Job, bool]:
        """Returns (job, created). Reuses a recent non-failed job for the same URL."""
        async with self._lock:
            self._evict_expired()
            for job in self._jobs.values():
                if job.url == url and job.status != JobStatus.failed:
                    return job, False
            now = _now()
            job = Job(id=uuid.uuid4().hex, url=url, status=JobStatus.queued, created_at=now, updated_at=now)
            self._jobs[job.id] = job
            return job, True

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def update(self, job_id: str, **changes) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = _now()

    def _evict_expired(self) -> None:
        cutoff = _now() - self._ttl
        for job_id in [j.id for j in self._jobs.values() if j.updated_at < cutoff]:
            del self._jobs[job_id]

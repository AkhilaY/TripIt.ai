import asyncio
from typing import Optional

from .db import Database
from .models import Job


class JobStore:
    """Import jobs, persisted in SQLite so they survive restarts."""

    def __init__(self, db: Database):
        self.db = db
        self._lock = asyncio.Lock()

    async def create(self, url: str, shared_text: Optional[str] = None) -> tuple[Job, bool]:
        """Returns (job, created). Reuses a running job, or a finished one whose places are still saved."""
        async with self._lock:
            existing = self.db.reusable_job(url)
            if existing:
                return existing, False
            return self.db.create_job(url, shared_text), True

    def get(self, job_id: str) -> Optional[Job]:
        return self.db.get_job(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        return self.db.list_jobs(limit)

    def update(self, job_id: str, **changes) -> None:
        self.db.update_job(job_id, **changes)

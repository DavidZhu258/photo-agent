from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.schemas.travel import TravelPlanResponse
from app.services.travel_query_understanding import TravelModelCallError


TravelJobStatus = Literal["queued", "running", "completed", "failed"]


@dataclass
class TravelJobRecord:
    job_id: str
    status: TravelJobStatus
    created_at: datetime
    updated_at: datetime
    response: TravelPlanResponse | None = None
    error: dict[str, object] | None = None
    task: asyncio.Task[None] | None = None


class TravelJobManager:
    """In-process job runner for long mobile travel requests."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self._jobs: dict[str, TravelJobRecord] = {}

    def start(
        self,
        run_plan: Callable[[], Awaitable[TravelPlanResponse]],
    ) -> TravelJobRecord:
        self._cleanup()
        now = _utc_now()
        record = TravelJobRecord(
            job_id=uuid.uuid4().hex,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        self._jobs[record.job_id] = record
        record.task = asyncio.create_task(self._run(record, run_plan))
        return record

    def get(self, job_id: str) -> TravelJobRecord | None:
        self._cleanup()
        return self._jobs.get(job_id)

    async def _run(
        self,
        record: TravelJobRecord,
        run_plan: Callable[[], Awaitable[TravelPlanResponse]],
    ) -> None:
        record.status = "running"
        record.updated_at = _utc_now()
        try:
            record.response = await run_plan()
            record.status = "completed"
        except TravelModelCallError as exc:
            record.error = {
                "error_type": "travel_model_call_failed",
                "failed_stage": exc.stage,
                "model": exc.model,
                "message": exc.message,
            }
            record.status = "failed"
        except Exception as exc:  # pragma: no cover - defensive boundary
            record.error = {
                "error_type": "travel_job_failed",
                "message": f"{exc.__class__.__name__}: {exc}",
            }
            record.status = "failed"
        finally:
            record.updated_at = _utc_now()

    def _cleanup(self) -> None:
        cutoff = _utc_now() - self.ttl
        expired = [
            job_id
            for job_id, record in self._jobs.items()
            if record.updated_at < cutoff and record.status in {"completed", "failed"}
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

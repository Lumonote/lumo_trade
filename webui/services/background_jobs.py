"""Background job orchestration for WebUI tasks.

This keeps framework routes from depending directly on threads or the job
storage backend. A future Robyn migration can replace this runner with an
async implementation without changing every route.
"""

from __future__ import annotations

import datetime
import threading
import uuid
from collections.abc import Callable
from typing import Any

from webui.services.job_store import JobStore


JobWorker = Callable[[str, dict[str, Any]], None]
Sanitizer = Callable[[Any], Any]


def _identity(value: Any) -> Any:
    return value


class BackgroundJobService:
    def __init__(self, store: JobStore, sanitizer: Sanitizer | None = None):
        self.store = store
        self.sanitize = sanitizer or _identity

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now().isoformat()

    @staticmethod
    def _format_datetime(ts: datetime.datetime | float | int | None = None) -> str:
        if ts is None:
            dt = datetime.datetime.now()
        elif isinstance(ts, (int, float)):
            dt = datetime.datetime.fromtimestamp(ts)
        elif isinstance(ts, datetime.datetime):
            dt = ts
        else:
            return str(ts)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    def create(self, job_type: str, params: dict[str, Any]) -> dict[str, Any]:
        job = {
            'id': uuid.uuid4().hex[:12],
            'type': job_type,
            'status': 'queued',
            'created_at': self._now(),
            'started_at': None,
            'finished_at': None,
            'params': params,
            'logs': ['任务已进入队列'],
            'result': None,
            'error': None,
        }
        return self.store.create(self.sanitize(job))

    def update(self, job_id: str, **updates: Any) -> dict[str, Any] | None:
        return self.store.update(job_id, **self.sanitize(updates))

    def append_log(self, job_id: str, message: str) -> dict[str, Any] | None:
        entry = f"{self._format_datetime()} {str(message).strip()}"
        return self.store.append_log(job_id, entry)

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.sanitize(self.store.get(job_id))

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.sanitize(self.store.list_recent(limit=limit))

    def snapshot(self, job_id: str | None = None, limit: int = 20) -> Any:
        if job_id:
            return self.get(job_id)
        return self.list_recent(limit=limit)

    def mark_interrupted_jobs(self, reason: str = '后台进程已重启，任务已中断') -> int:
        interrupted = 0
        finished_at = self._now()
        for job in self.store.list_by_status(('queued', 'running'), limit=200):
            logs = list(job.get('logs') or [])
            logs.append(f"{self._format_datetime()} {reason}")
            updated = self.update(
                job['id'],
                status='failed',
                finished_at=finished_at,
                logs=logs,
                error=reason,
            )
            if updated:
                interrupted += 1
        return interrupted

    def start(self, job_type: str, params: dict[str, Any], worker: JobWorker) -> dict[str, Any]:
        job = self.create(job_type, params)
        thread = threading.Thread(
            target=worker,
            args=(job['id'], params),
            daemon=True,
        )
        thread.start()
        return job

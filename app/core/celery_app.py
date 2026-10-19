"""The Celery application: the shared registry for background tasks.

Both sides of the system import this one object:
- the FastAPI app imports it (indirectly, via the task) to *enqueue* work,
- the worker process is started against it to *execute* that work.

`broker` is the Redis queue jobs are pushed to. `include` lists the modules
that define tasks, so the worker registers them on startup. Nothing here touches
the database or the AI - this file only wires up the queue.
"""

from celery import Celery
from app.core.config import settings


celery_app = Celery(
    "ez_takeoff",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.takeoff_tasks"],
)

celery_app.conf.update(
    # JSON only: never unpickle arbitrary payloads off the queue (safer).
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Mark a task "STARTED" while it runs, so status is visible, not just
    # queued-or-done.
    task_track_started=True,
    # One blueprint analysis is minutes long; don't prefetch a pile of them
    # onto one worker, so jobs spread across workers evenly.
    worker_prefetch_multiplier=1,
)

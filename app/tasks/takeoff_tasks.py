"""Celery tasks for takeoff analysis.

A task is deliberately a thin shell: it only forwards to run_takeoff_analysis,
the plain function that holds the real logic. That keeps the work unit-testable
without a running broker, and keeps the task free of anything but queue concerns.
"""

from app.core.celery_app import celery_app
from app.services.analysis_runner import run_takeoff_analysis


@celery_app.task(name="takeoff.analyze")
def analyze_takeoff_task(
    job_id: int,
    previous_status: str,
    had_existing_items: bool,
) -> int:
    return run_takeoff_analysis(job_id, previous_status, had_existing_items)

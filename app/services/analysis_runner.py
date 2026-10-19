"""The slow half of analysis, runnable outside a web request.

The web endpoint used to do this inline, which blocked the request for minutes.
Now a Celery worker calls run_takeoff_analysis in a separate process. Because it
is a different process, it opens its OWN database session (SessionLocal) - the
request's session from get_db does not exist here.

The transaction shape is deliberately the same as before: do the expensive AI
work first, then replace the rows and flip the status in one commit, so a failure
leaves the previous good result intact.
"""

from __future__ import annotations

from app.core.database import SessionLocal
from app.core.tracing import propagate_attributes
from app.models.takeoff import TakeoffItem, TakeoffJob
from app.services.ai_service import analyze_blueprint
from app.services.calculation_service import calculate_quantity
from app.services.matching_persistence_service import invalidate_downstream_results
from app.services.takeoff_normalization import normalize_detected_items


def run_takeoff_analysis(
    job_id: int,
    previous_status: str,
    had_existing_items: bool,
) -> int:
    """Analyze one job and persist the result. Returns the item count.

    `previous_status` / `had_existing_items` are captured by the caller BEFORE
    it flips the job to "processing", so a failed forced re-run can restore the
    previous "completed" state instead of marking the job failed.
    """
    db = SessionLocal()
    try:
        job = db.query(TakeoffJob).filter(TakeoffJob.id == job_id).first()
        if job is None:
            return 0
        file_path = job.file_path

        try:
            with propagate_attributes(
                trace_name="takeoff-analysis",
                metadata={"job_id": str(job_id)},
            ):
                detected_items = analyze_blueprint(file_path)

            # Geometry math lives here, not in the model, so quantities are
            # deterministic across runs.
            normalized_items = normalize_detected_items(detected_items.items)
            replacement_items: list[TakeoffItem] = []
            for item in normalized_items:
                calculated_quantity = calculate_quantity(item.model_dump())
                if calculated_quantity is not None:
                    item.quantity = calculated_quantity
                replacement_items.append(
                    TakeoffItem(
                        job_id=job_id,
                        item_name=item.item_name,
                        measurement_type=item.measurement_type,
                        length=item.length,
                        width=item.width,
                        height=item.height,
                        count=item.count,
                        quantity=item.quantity,
                        unit=item.unit,
                        confidence=item.confidence,
                    )
                )

            # One atomic replace: drop stale downstream results, swap the items,
            # flip to completed.
            invalidate_downstream_results(db, job_id)
            (
                db.query(TakeoffItem)
                .filter(TakeoffItem.job_id == job_id)
                .delete(synchronize_session=False)
            )
            db.add_all(replacement_items)
            (
                db.query(TakeoffJob)
                .filter(TakeoffJob.id == job_id)
                .update(
                    {TakeoffJob.status: "completed"},
                    synchronize_session=False,
                )
            )
            db.commit()
            return len(replacement_items)

        except Exception:
            db.rollback()
            # A failed forced refresh keeps the previous successful result usable.
            failure_status = (
                "completed"
                if previous_status == "completed" and had_existing_items
                else "failed"
            )
            try:
                (
                    db.query(TakeoffJob)
                    .filter(TakeoffJob.id == job_id)
                    .update(
                        {TakeoffJob.status: failure_status},
                        synchronize_session=False,
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
            raise
    finally:
        db.close()

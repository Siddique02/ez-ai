from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.estimate import TakeoffItemMatch
from app.models.takeoff import TakeoffItem, TakeoffJob
from app.schemas.matching import ProductMatchResult
from app.services.estimate_service import delete_estimate_for_job


_CONFIDENCE_QUANTUM = Decimal("0.0001")


class MatchingStateChangedError(RuntimeError):
    pass


def delete_matches_for_job(db: Session, job_id: int) -> None:
    item_ids = select(TakeoffItem.id).where(TakeoffItem.job_id == job_id)
    (
        db.query(TakeoffItemMatch)
        .filter(TakeoffItemMatch.takeoff_item_id.in_(item_ids))
        .delete(synchronize_session=False)
    )


def invalidate_downstream_results(db: Session, job_id: int) -> None:
    delete_estimate_for_job(db, job_id)
    delete_matches_for_job(db, job_id)


def replace_product_matches(
    db: Session,
    job_id: int,
    expected_item_ids: Sequence[int],
    matches: Sequence[ProductMatchResult],
) -> None:
    job = (
        db.query(TakeoffJob)
        .filter(TakeoffJob.id == job_id)
        .with_for_update()
        .first()
    )
    if job is None:
        raise MatchingStateChangedError("Takeoff job no longer exists")
    if job.status == "processing":
        raise MatchingStateChangedError(
            "Takeoff analysis changed while products were being matched"
        )

    current_item_ids = [
        item_id
        for (item_id,) in (
            db.query(TakeoffItem.id)
            .filter(TakeoffItem.job_id == job_id)
            .order_by(TakeoffItem.id)
            .all()
        )
    ]
    expected_ids = sorted(expected_item_ids)
    result_ids = sorted(
        result.item_id
        for result in matches
        if result.item_id is not None
    )
    if current_item_ids != expected_ids or result_ids != expected_ids:
        raise MatchingStateChangedError(
            "Takeoff items changed while products were being matched"
        )

    delete_estimate_for_job(db, job_id)
    delete_matches_for_job(db, job_id)

    db.add_all(
        [
            TakeoffItemMatch(
                takeoff_item_id=result.item_id,
                catalog_product_id=result.product_id if result.matched else None,
                product_code=result.code if result.matched else None,
                product_name=(
                    result.matched_product if result.matched else None
                ),
                catalog_unit=result.catalog_unit if result.matched else None,
                confidence=Decimal(str(result.confidence)).quantize(
                    _CONFIDENCE_QUANTUM,
                    rounding=ROUND_HALF_UP,
                ),
                status="matched" if result.matched else "review",
            )
            for result in matches
        ]
    )
    db.commit()

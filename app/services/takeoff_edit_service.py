"""User corrections of the AI takeoff: add, edit and delete items.

Every change is written to takeoff_item_edits with the item before and after,
so the corrections can later be reused to improve the AI.
"""

import math
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.models.estimate import TakeoffItemMatch
from app.models.takeoff import TakeoffItem, TakeoffItemEdit, TakeoffJob
from app.schemas.takeoff import TakeoffItemCreate, TakeoffItemUpdate
from app.services.calculation_service import calculate_quantity
from app.services.estimate_service import delete_estimate_for_job


_ITEM_FIELDS = (
    "item_name",
    "measurement_type",
    "length",
    "width",
    "height",
    "count",
    "quantity",
    "unit",
    "confidence",
)
# Fields the quantity is calculated from.
_MEASUREMENT_FIELDS = frozenset(
    {"measurement_type", "length", "width", "height", "count"}
)
# Fields the product match was chosen from.
_MATCH_FIELDS = frozenset({"item_name", "unit", "measurement_type"})


class TakeoffEditError(RuntimeError):
    pass


class TakeoffItemNotFoundError(TakeoffEditError):
    pass


class TakeoffNotEditableError(TakeoffEditError):
    pass


class QuantityConflictError(TakeoffEditError):
    def __init__(self, calculated: float) -> None:
        self.calculated = calculated
        super().__init__(
            f"The quantity conflicts with the dimensions, which give "
            f"{calculated:g}. Change the dimensions, or set them to null to "
            f"enter the quantity directly."
        )


def create_item(
    db: Session,
    job_id: int,
    payload: TakeoffItemCreate,
) -> TakeoffItem:
    _lock_editable_job(db, job_id)

    values = _plain(payload.model_dump())
    _settle_quantity(
        values,
        quantity_requested="quantity" in payload.model_fields_set,
        measurement_changed=True,
    )

    item = TakeoffItem(job_id=job_id, **values)
    db.add(item)
    # The saved estimate no longer covers every item.
    delete_estimate_for_job(db, job_id)
    db.flush()

    db.add(
        TakeoffItemEdit(
            job_id=job_id,
            takeoff_item_id=item.id,
            action="create",
            before=None,
            after=_snapshot(item),
        )
    )
    db.commit()
    db.refresh(item)
    return item


def update_item(
    db: Session,
    job_id: int,
    item_id: int,
    payload: TakeoffItemUpdate,
) -> TakeoffItem:
    _lock_editable_job(db, job_id)
    item = _get_item(db, job_id, item_id)

    before = _snapshot(item)
    changes = _plain(payload.model_dump(exclude_unset=True))
    after = {**before, **changes}
    _settle_quantity(
        after,
        quantity_requested="quantity" in changes,
        measurement_changed=bool(_MEASUREMENT_FIELDS & changes.keys()),
    )

    if after == before:
        return item

    for field in _ITEM_FIELDS:
        setattr(item, field, after[field])

    # Any change makes the saved estimate out of date.
    delete_estimate_for_job(db, job_id)
    # A renamed or re-typed item may no longer be the matched product.
    if any(before[field] != after[field] for field in _MATCH_FIELDS):
        _delete_match(db, item_id)

    db.add(
        TakeoffItemEdit(
            job_id=job_id,
            takeoff_item_id=item_id,
            action="update",
            before=before,
            after=after,
        )
    )
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, job_id: int, item_id: int) -> None:
    _lock_editable_job(db, job_id)
    item = _get_item(db, job_id, item_id)
    before = _snapshot(item)

    # Estimate lines and the match point at the item, so they go first.
    delete_estimate_for_job(db, job_id)
    _delete_match(db, item_id)
    db.delete(item)

    db.add(
        TakeoffItemEdit(
            job_id=job_id,
            takeoff_item_id=item_id,
            action="delete",
            before=before,
            after=None,
        )
    )
    db.commit()


def _lock_editable_job(db: Session, job_id: int) -> None:
    # The row lock stops an analysis from replacing the items mid-edit.
    job = (
        db.query(TakeoffJob)
        .filter(TakeoffJob.id == job_id)
        .with_for_update()
        .first()
    )
    if job is None:
        raise TakeoffItemNotFoundError("Takeoff job not found")
    if job.status == "processing":
        raise TakeoffNotEditableError(
            "Takeoff analysis is processing; edit the items when it finishes"
        )
    if job.status != "completed":
        raise TakeoffNotEditableError(
            "Analyze the takeoff before editing its items"
        )


def _get_item(db: Session, job_id: int, item_id: int) -> TakeoffItem:
    item = (
        db.query(TakeoffItem)
        .filter(TakeoffItem.id == item_id, TakeoffItem.job_id == job_id)
        .first()
    )
    if item is None:
        raise TakeoffItemNotFoundError("Takeoff item not found")
    return item


def _delete_match(db: Session, item_id: int) -> None:
    (
        db.query(TakeoffItemMatch)
        .filter(TakeoffItemMatch.takeoff_item_id == item_id)
        .delete(synchronize_session=False)
    )


def _settle_quantity(
    values: dict[str, Any],
    *,
    quantity_requested: bool,
    measurement_changed: bool,
) -> None:
    """Keep quantity consistent with the dimensions, as analysis does.

    The estimate prices items from their dimensions when they have them, so
    a typed quantity that disagrees with the dimensions would be silently
    ignored there. It is rejected here instead.
    """
    calculated = calculate_quantity(values)

    if quantity_requested:
        requested = values["quantity"]
        if (
            calculated is not None
            and requested is not None
            and not math.isclose(
                calculated,
                requested,
                rel_tol=1e-6,
                abs_tol=1e-4,
            )
        ):
            raise QuantityConflictError(calculated)
        if calculated is not None:
            values["quantity"] = calculated
    elif measurement_changed:
        values["quantity"] = calculated


def _snapshot(item: TakeoffItem) -> dict[str, Any]:
    return {field: getattr(item, field) for field in _ITEM_FIELDS}


def _plain(values: dict[str, Any]) -> dict[str, Any]:
    # Store "area" rather than MeasurementType.AREA.
    return {
        key: value.value if isinstance(value, Enum) else value
        for key, value in values.items()
    }

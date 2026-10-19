"""Turn the AI's raw measurement primitives into stored, priceable items.

The AI's job is perception: read whatever this drawing shows, in whatever words,
and report the raw numbers (each wall run, the roof pitch, the opening area). The
arithmetic is universal, so it belongs here, not in the model. This module folds
those primitives down to the length/width/height the database already stores, so
no schema change is needed, and the result still satisfies the edit contract:
calculate_quantity() on the stored columns reproduces the stored quantity.

Keeping the math here (not in the prompt) is what makes every quantity
deterministic and identical across runs and across different users' PDFs.
"""

from __future__ import annotations

from app.schemas.ai import ConfidenceLevel, DetectedItem, MeasurementType
from app.services.geometry import (
    is_implausible_dimension,
    slope_factor,
    sum_segments,
)


def normalize_detected_items(items: list[DetectedItem]) -> list[DetectedItem]:
    """Normalize every AI item; never raises, so one bad item cannot fail a job."""
    return [_normalize_item(item) for item in items]


def _normalize_item(item: DetectedItem) -> DetectedItem:
    # Work on a copy so the AI's original reading is never mutated in place.
    item = item.model_copy(deep=True)

    if item.measurement_type == MeasurementType.LINEAR:
        _fold_segments_into_length(item)
    elif item.measurement_type == MeasurementType.AREA:
        _normalize_area(item)

    _flag_if_implausible(item)
    return item


def _fold_segments_into_length(item: DetectedItem) -> None:
    """A run made of several traced segments becomes one summed length."""
    segment_total = sum_segments(item.wall_segments)
    if segment_total is not None:
        item.length = segment_total


def _normalize_area(item: DetectedItem) -> None:
    """Collapse a surface to the two stored dimensions that recompute its area.

    Vertical finishes: length (sum of wall runs) x height.
    Sloped roofs:      plan length x width, with the slope baked into length so
                       the stored dimensions still multiply to the true surface.
    Openings:          deducted here and stored as an explicit net quantity.
    """
    # 1. Wall finish: the summed wall runs are the length; height stays as read.
    segment_total = sum_segments(item.wall_segments)
    if segment_total is not None:
        item.length = segment_total
        item.width = None

    # 2. Sloped roof: scale the plan length by the pitch factor. The surface runs
    #    up the slope, so the slope-adjusted length is a real dimension, and
    #    length x width continues to equal the true (sloped) area on any re-edit.
    if item.pitch is not None and item.length is not None:
        item.length = item.length * slope_factor(item.pitch)

    # 3. Opening deductions: compute the gross area, subtract the openings, and
    #    store the net as an explicit quantity with the dimensions cleared, which
    #    is how the rest of the app already represents a deducted area.
    if item.openings_sqft:
        gross = _gross_area(item)
        if gross is not None:
            net = gross - item.openings_sqft
            if net <= 0:
                # The deduction is larger than the wall; keep the gross area and
                # ask for review instead of storing a zero or negative quantity.
                item.confidence = ConfidenceLevel.LOW
            else:
                item.quantity = net
                item.length = None
                item.width = None
                item.height = None


def _gross_area(item: DetectedItem) -> float | None:
    """The area the stored dimensions describe, before any opening deduction."""
    occurrences = item.count if item.count is not None else 1
    if item.length is not None and item.width is not None:
        return item.length * item.width * occurrences
    if item.length is not None and item.height is not None:
        return item.length * item.height * occurrences
    return None


def _flag_if_implausible(item: DetectedItem) -> None:
    """Downgrade confidence when a dimension cannot be real.

    A non-positive or absurdly large dimension is almost always a misread scale
    or a material spec (a "7/8 inch" thickness) captured as a length. We cannot
    know the true value, so we surface it for review rather than price a wrong
    number silently.
    """
    if any(
        is_implausible_dimension(dimension)
        for dimension in (item.length, item.width, item.height)
    ):
        item.confidence = ConfidenceLevel.LOW

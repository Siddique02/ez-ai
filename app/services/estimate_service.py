from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.estimate import Estimate, EstimateItem, TakeoffItemMatch
from app.models.takeoff import TakeoffItem, TakeoffJob
from app.schemas.estimate import EstimateItemResponse, EstimateResponse
from app.schemas.matching import CatalogProduct
from app.services.quantity_conversion_service import (
    QuantityConversionError,
    calculate_catalog_quantity,
    normalize_unit,
)


_FOUR_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class EstimateIssue:
    item_id: int | None
    item_name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EstimateServiceError(RuntimeError):
    pass


class EstimateJobNotFoundError(EstimateServiceError):
    pass


class EstimateNotReadyError(EstimateServiceError):
    def __init__(self, issues: Sequence[EstimateIssue]) -> None:
        self.issues = list(issues)
        super().__init__("The estimate has items that require review")


def _four_places(value: Decimal) -> Decimal:
    return value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


def calculate_estimate_line(
    item: TakeoffItem,
    product: CatalogProduct,
) -> dict[str, Decimal | str]:
    quantity = _four_places(
        calculate_catalog_quantity(item, product.unit_of_measure)
    )

    if quantity <= 0:
        raise QuantityConversionError(
            "Quantity must be greater than zero"
        )

    unit = normalize_unit(product.unit_of_measure)
    if unit is None:
        raise QuantityConversionError(
            f"Unsupported catalog unit: {product.unit_of_measure}"
        )

    material_cost = (
        product.adjusted_cost
        if product.adjusted_cost is not None
        else product.material_cost
    )

    missing_prices = []

    if product.labor_cost is None:
        missing_prices.append("labor_cost")

    if material_cost is None:
        missing_prices.append("material_cost")

    if missing_prices:
        raise QuantityConversionError(
            "Catalog product is missing pricing: "
            + ", ".join(missing_prices)
        )

    labor_unit_cost = _four_places(product.labor_cost)
    material_unit_cost = _four_places(material_cost)
    misc_unit_cost = _four_places(
        product.misc_cost or Decimal("0")
    )

    labor_total = _four_places(quantity * labor_unit_cost)
    material_total = _four_places(quantity * material_unit_cost)
    misc_total = _four_places(quantity * misc_unit_cost)

    return {
        "quantity": quantity,
        "unit": unit,
        "labor_unit_cost": labor_unit_cost,
        "material_unit_cost": material_unit_cost,
        "misc_unit_cost": misc_unit_cost,
        "labor_total": labor_total,
        "material_total": material_total,
        "misc_total": misc_total,
        "line_total": _four_places(
            labor_total + material_total + misc_total
        ),
    }


def delete_estimate_for_job(db: Session, job_id: int) -> None:
    estimate_ids = select(Estimate.id).where(Estimate.job_id == job_id)
    (
        db.query(EstimateItem)
        .filter(EstimateItem.estimate_id.in_(estimate_ids))
        .delete(synchronize_session=False)
    )
    (
        db.query(Estimate)
        .filter(Estimate.job_id == job_id)
        .delete(synchronize_session=False)
    )


def find_estimate_prerequisite_issues(
    db: Session,
    job_id: int,
) -> list[EstimateIssue]:
    items = (
        db.query(TakeoffItem)
        .filter(TakeoffItem.job_id == job_id)
        .order_by(TakeoffItem.id)
        .all()
    )
    if not items:
        return [
            EstimateIssue(
                item_id=None,
                item_name="Takeoff",
                reason="Analyze the takeoff before creating an estimate",
            )
        ]

    item_ids = [item.id for item in items]
    matches = (
        db.query(TakeoffItemMatch)
        .filter(TakeoffItemMatch.takeoff_item_id.in_(item_ids))
        .all()
    )
    matches_by_item_id = {match.takeoff_item_id: match for match in matches}

    issues: list[EstimateIssue] = []
    for item in items:
        match = matches_by_item_id.get(item.id)
        if (
            match is None
            or match.status != "matched"
            or match.catalog_product_id is None
        ):
            issues.append(
                EstimateIssue(
                    item_id=item.id,
                    item_name=item.item_name,
                    reason="A confirmed catalog match is required",
                )
            )
    return issues


def get_estimate_response(
    db: Session,
    job_id: int,
) -> EstimateResponse | None:
    estimate = (
        db.query(Estimate)
        .filter(Estimate.job_id == job_id)
        .first()
    )
    if estimate is None:
        return None

    rows = (
        db.query(EstimateItem, TakeoffItem.item_name)
        .join(TakeoffItem, TakeoffItem.id == EstimateItem.takeoff_item_id)
        .filter(EstimateItem.estimate_id == estimate.id)
        .order_by(EstimateItem.id)
        .all()
    )

    return EstimateResponse(
        job_id=estimate.job_id,
        status=estimate.status,
        labor_total=estimate.labor_total,
        material_total=estimate.material_total,
        misc_total=estimate.misc_total,
        grand_total=estimate.grand_total,
        items=[
            EstimateItemResponse(
                item_id=estimate_item.takeoff_item_id,
                item_name=item_name,
                product_code=estimate_item.product_code,
                product_name=estimate_item.product_name,
                quantity=estimate_item.quantity,
                unit=estimate_item.unit,
                labor_unit_cost=estimate_item.labor_unit_cost,
                material_unit_cost=estimate_item.material_unit_cost,
                misc_unit_cost=estimate_item.misc_unit_cost,
                labor_total=estimate_item.labor_total,
                material_total=estimate_item.material_total,
                misc_total=estimate_item.misc_total,
                line_total=estimate_item.line_total,
            )
            for estimate_item, item_name in rows
        ],
    )


def create_or_replace_estimate(
    db: Session,
    job_id: int,
    catalog_products: Sequence[CatalogProduct],
    *,
    force: bool = False,
) -> EstimateResponse:
    job = (
        db.query(TakeoffJob)
        .filter(TakeoffJob.id == job_id)
        .with_for_update()
        .first()
    )
    if job is None:
        raise EstimateJobNotFoundError("Takeoff job not found")
    if job.status != "completed":
        raise EstimateNotReadyError(
            [
                EstimateIssue(
                    item_id=None,
                    item_name="Takeoff",
                    reason="Takeoff analysis must be completed first",
                )
            ]
        )

    existing = (
        db.query(Estimate)
        .filter(Estimate.job_id == job_id)
        .first()
    )
    if existing is not None and not force:
        response = get_estimate_response(db, job_id)
        if response is None:
            raise EstimateServiceError("The existing estimate could not be loaded")
        return response

    prerequisite_issues = find_estimate_prerequisite_issues(db, job_id)
    if prerequisite_issues:
        raise EstimateNotReadyError(prerequisite_issues)

    items = (
        db.query(TakeoffItem)
        .filter(TakeoffItem.job_id == job_id)
        .order_by(TakeoffItem.id)
        .all()
    )
    item_ids = [item.id for item in items]
    matches = (
        db.query(TakeoffItemMatch)
        .filter(TakeoffItemMatch.takeoff_item_id.in_(item_ids))
        .all()
    )
    matches_by_item_id = {match.takeoff_item_id: match for match in matches}
    products_by_id = {product.id: product for product in catalog_products}

    calculated_lines: list[
        tuple[TakeoffItem, CatalogProduct, dict[str, Decimal | str]]
    ] = []
    calculation_issues: list[EstimateIssue] = []

    for item in items:
        match = matches_by_item_id[item.id]
        product = products_by_id.get(match.catalog_product_id)
        if product is None or not product.product_name:
            calculation_issues.append(
                EstimateIssue(
                    item_id=item.id,
                    item_name=item.item_name,
                    reason="The matched product is no longer in the PHP catalog",
                )
            )
            continue

        try:
            line = calculate_estimate_line(item, product)
        except QuantityConversionError as exc:
            calculation_issues.append(
                EstimateIssue(
                    item_id=item.id,
                    item_name=item.item_name,
                    reason=str(exc),
                )
            )
            continue

        calculated_lines.append((item, product, line))

    if calculation_issues:
        raise EstimateNotReadyError(calculation_issues)

    labor_total = _four_places(
        sum(
            (line["labor_total"] for _, _, line in calculated_lines),
            Decimal("0"),
        )
    )
    material_total = _four_places(
        sum(
            (line["material_total"] for _, _, line in calculated_lines),
            Decimal("0"),
        )
    )
    misc_total = _four_places(
        sum(
            (line["misc_total"] for _, _, line in calculated_lines),
            Decimal("0"),
        )
    )

    if existing is not None:
        db.expunge(existing)
    delete_estimate_for_job(db, job_id)
    db.flush()

    estimate = Estimate(
        job_id=job_id,
        labor_total=labor_total,
        material_total=material_total,
        misc_total=misc_total,
        grand_total=_four_places(
            labor_total + material_total + misc_total
        ),
        status="completed",
    )
    db.add(estimate)
    db.flush()

    for item, product, line in calculated_lines:
        db.add(
            EstimateItem(
                estimate_id=estimate.id,
                takeoff_item_id=item.id,
                catalog_product_id=product.id,
                product_code=product.code_name,
                product_name=product.product_name,
                unit=str(line["unit"]),
                quantity=line["quantity"],
                labor_unit_cost=line["labor_unit_cost"],
                material_unit_cost=line["material_unit_cost"],
                misc_unit_cost=line["misc_unit_cost"],
                labor_total=line["labor_total"],
                material_total=line["material_total"],
                misc_total=line["misc_total"],
                line_total=line["line_total"],
            )
        )

    db.commit()
    response = get_estimate_response(db, job_id)
    if response is None:
        raise EstimateServiceError("The estimate could not be loaded after saving")
    return response

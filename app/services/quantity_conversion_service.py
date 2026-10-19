from decimal import Decimal


class QuantityConversionError(ValueError):
    pass


_UNIT_ALIASES = {
    "ea": "ea",
    "each": "ea",
    "unit": "ea",
    "units": "ea",
    "pc": "ea",
    "pcs": "ea",
    "piece": "ea",
    "pieces": "ea",
    "door": "ea",
    "fixture": "ea",

    "sf": "sqft",
    "sqft": "sqft",
    "sq ft": "sqft",
    "square feet": "sqft",
    "square foot": "sqft",

    "ft": "ft",
    "lf": "ft",
    "feet": "ft",
    "foot": "ft",
    "lin ft": "ft",
    "linear ft": "ft",
    "linear feet": "ft",

    "square": "square",
    "squares": "square",
}


def _decimal(value: int | float | Decimal) -> Decimal:
    return Decimal(str(value))


def normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None

    normalized = " ".join(unit.replace(".", " ").casefold().split())
    return _UNIT_ALIASES.get(normalized) or _UNIT_ALIASES.get(
        normalized.replace(" ", "")
    )


def is_supported_unit(unit: str | None) -> bool:
    return normalize_unit(unit) is not None


def calculate_catalog_quantity(item, catalog_unit: str | None) -> Decimal:
    target_unit = normalize_unit(catalog_unit)

    if target_unit == "ea":
        if item.count is not None:
            return _decimal(item.count)

        if item.measurement_type == "count" and item.quantity is not None:
            return _decimal(item.quantity)

        raise QuantityConversionError("Count is required for an each item")

    if target_unit == "sqft":
        # A counted door/window priced by its surface area.
        if (
            item.count is not None
            and item.width is not None
            and item.height is not None
        ):
            return (
                _decimal(item.count)
                * _decimal(item.width)
                * _decimal(item.height)
            )

        # An area item such as drywall or flooring.
        if item.measurement_type == "area" and item.quantity is not None:
            return _decimal(item.quantity)

        raise QuantityConversionError(
            "Area or count with width and height is required"
        )

    if target_unit == "ft":
        # Length describes one occurrence, so six 5 ft headers are 30 ft.
        if item.length is not None:
            occurrences = item.count if item.count is not None else 1
            return _decimal(item.length) * _decimal(occurrences)

        if item.measurement_type == "linear" and item.quantity is not None:
            return _decimal(item.quantity)

        raise QuantityConversionError("Length is required")

    if target_unit == "square":
        square_feet = calculate_catalog_quantity(item, "sqft")
        return square_feet / Decimal("100")

    raise QuantityConversionError(
        f"Unsupported catalog unit: {catalog_unit}"
    )

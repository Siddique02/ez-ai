"""Score a produced takeoff against a known-good ("gold") reference.

The point of this module is to replace a human eyeballing the result with a
number anyone can reproduce. You give it the items a run produced and a gold
list of what the drawings actually contain, and it reports three things:

  coverage  - of the expected scope, how much did the run find at all?
  accuracy  - of what it found, how much was within tolerance of the truth?
  overall   - the single headline: expected items that were both found AND right.

Matching is by category, not exact name, and it SUMS the produced items in a
category before comparing. That is deliberate: a good run splits "slab" into a
house slab and a garage slab, and the gold says the total should be ~1,624 SF.
Summing lets the split answer score as correct instead of looking like a miss.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldItem:
    """One expected scope line and how close a run must get to be "right"."""

    key: str
    label: str
    unit: str                 # "ea", "ft", or "sqft"
    expected: float
    keywords: tuple[str, ...]  # any match (case-insensitive) in the item name
    tol: float = 0.15          # allowed relative error
    abs_tol: float = 0.0       # allowed absolute error (useful for small counts)
    # Words that, if present, disqualify a match. They stop a broad keyword like
    # "slab" from also matching "slab reinforcing" or "under-slab vapor barrier".
    exclude: tuple[str, ...] = ()


@dataclass
class LineResult:
    gold: GoldItem
    produced_quantity: float | None
    matched_names: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.produced_quantity is not None

    @property
    def within_tolerance(self) -> bool:
        if self.produced_quantity is None:
            return False
        allowed = abs(self.gold.expected) * self.gold.tol + self.gold.abs_tol
        return abs(self.produced_quantity - self.gold.expected) <= allowed

    @property
    def error_ratio(self) -> float | None:
        if self.produced_quantity is None or self.gold.expected == 0:
            return None
        return (self.produced_quantity - self.gold.expected) / self.gold.expected


@dataclass
class ScoreReport:
    lines: list[LineResult]

    @property
    def total(self) -> int:
        return len(self.lines)

    @property
    def found_count(self) -> int:
        return sum(1 for line in self.lines if line.found)

    @property
    def correct_count(self) -> int:
        return sum(1 for line in self.lines if line.within_tolerance)

    @property
    def coverage(self) -> float:
        return self.found_count / self.total if self.total else 0.0

    @property
    def accuracy(self) -> float:
        # Of what was found, how much was within tolerance.
        return self.correct_count / self.found_count if self.found_count else 0.0

    @property
    def overall(self) -> float:
        # Expected items that were both found and correct, as a 0-100 score.
        return 100.0 * self.correct_count / self.total if self.total else 0.0


def _match_quantity(
    gold: GoldItem,
    produced: list[dict],
) -> tuple[float | None, list[str]]:
    """Sum the produced items that belong to this gold category."""
    total = 0.0
    names: list[str] = []
    for item in produced:
        name = (item.get("item_name") or "").casefold()
        unit = _canonical_unit(item.get("unit"))
        if unit != gold.unit:
            continue
        if not any(keyword.casefold() in name for keyword in gold.keywords):
            continue
        if any(term.casefold() in name for term in gold.exclude):
            continue
        quantity = item.get("quantity")
        if quantity is None:
            # A matched-but-unquantified item counts as found-but-wrong: it
            # names the scope yet gives no number, so it must not score as hit.
            names.append(item.get("item_name") or "")
            continue
        total += float(quantity)
        names.append(item.get("item_name") or "")

    if not names:
        return None, []
    # If every match was null-quantity, treat as not measured.
    return (total if total > 0 else None), names


def _canonical_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    u = unit.strip().casefold()
    if u in {"ea", "each", "unit", "units", "pc", "pcs"}:
        return "ea"
    if u in {"sf", "sqft", "sq ft", "square feet"}:
        return "sqft"
    if u in {"ft", "lf", "feet", "linear feet", "lin ft"}:
        return "ft"
    return u


def score_takeoff(produced: list[dict], gold: list[GoldItem]) -> ScoreReport:
    lines = []
    for gold_item in gold:
        quantity, names = _match_quantity(gold_item, produced)
        lines.append(
            LineResult(
                gold=gold_item,
                produced_quantity=quantity,
                matched_names=names,
            )
        )
    return ScoreReport(lines=lines)

from enum import Enum
from pydantic import BaseModel, Field


class MeasurementType(str, Enum):
    AREA = "area"
    LINEAR = "linear"
    COUNT = "count"


# Raw geometry the AI reads off the drawing. The backend collapses these into
# the stored length/width/height before saving, so adding them needs no database
# change. They exist so the AI reports what it SEES (each wall run, the pitch,
# the opening area) and never does the arithmetic itself.


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DetectedItem(BaseModel):
    item_name: str = Field(
        description=(
            "Concise construction item name, including its schedule symbol when "
            "available but excluding dimensions"
        )
    )
    measurement_type: MeasurementType | None = Field(
        description="How the item must be measured: area, linear, or count"
    )
    length: float | None = Field(
        default=None,
        description=(
            "Physical length normalized to decimal feet; null for doors and "
            "windows whose scheduled size is width by height"
        ),
    )
    width: float | None = Field(
        default=None,
        description=(
            "Physical or scheduled width normalized to decimal feet, independent "
            "of the estimating quantity unit"
        ),
    )
    height: float | None = Field(
        default=None,
        description=(
            "Physical or scheduled height normalized to decimal feet, independent "
            "of the estimating quantity unit"
        ),
    )
    count: int | None = Field(
        default=None,
        description="Number of actual occurrences visible on the drawing",
    )
    wall_segments: list[float] = Field(
        default_factory=list,
        description=(
            "For a wall finish (stucco, siding, drywall, insulation, weep "
            "screed): the length in decimal feet of every wall run the finish "
            "covers, each as its own number. The backend sums them into the "
            "total length. Leave empty for anything that is not a wall."
        ),
    )
    pitch: str | None = Field(
        default=None,
        description=(
            "Roof pitch as rise:run, e.g. '4:12', when the item is a sloped "
            "surface (roofing, roof sheathing, roof underlayment). The backend "
            "converts the plan area to the sloped area; never pre-apply it."
        ),
    )
    openings_sqft: float | None = Field(
        default=None,
        description=(
            "Total area in square feet of doors and windows to deduct from a "
            "wall finish. The backend subtracts it from the gross wall area."
        ),
    )
    quantity: float | None = Field(
        default=None,
        description="Explicit total quantity from the drawing, otherwise null",
    )
    unit: str = Field(
        description=(
            "Unit for the final estimating quantity, normally ea, ft, or sqft; "
            "this is not the unit for length, width, or height"
        )
    )
    confidence: ConfidenceLevel | None = Field(
        default=None,
        description="Confidence in the extracted item and measurement",
    )


class AIAnalysisResponse(BaseModel):
    items: list[DetectedItem]

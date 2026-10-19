from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ai import ConfidenceLevel, MeasurementType


class TakeoffItemCreate(BaseModel):
    """A takeoff item the user adds because the AI missed it."""

    item_name: str = Field(min_length=1, max_length=255)
    measurement_type: MeasurementType | None = None
    length: float | None = Field(default=None, gt=0)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    count: int | None = Field(default=None, gt=0)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    confidence: ConfidenceLevel | None = None

    # Unknown fields are rejected so a typo such as "cout" is not ignored.
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class TakeoffItemUpdate(TakeoffItemCreate):
    """A partial correction: only the fields sent are changed.

    Sending null clears a field, for example "width": null.
    """

    item_name: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("item_name")
    @classmethod
    def item_name_cannot_be_cleared(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("item_name cannot be null")
        return value


class TakeoffItemResponse(BaseModel):
    id: int
    item_name: str
    measurement_type: str | None
    length: float | None
    width: float | None
    height: float | None
    count: int | None
    quantity: float | None
    unit: str | None
    confidence: str | None

    model_config = ConfigDict(
        from_attributes=True
    )


class TakeoffResponse(BaseModel):
    id: int
    file_name: str
    status: str

    model_config = ConfigDict(
        from_attributes=True
    )


class TakeoffAnalysisResponse(BaseModel):
    job_id: int
    status: str
    items_found: int
    reused: bool

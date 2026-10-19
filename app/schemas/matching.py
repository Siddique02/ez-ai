from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CatalogProduct(BaseModel):
    """The subset of a PHP catalog product used by the matching layer."""

    id: int
    code_name: str = Field(min_length=1)
    product_name: str | None = None
    description: str = ""
    unit_of_measure: str | None = None

    labor_cost: Decimal | None = None
    material_cost: Decimal | None = None
    misc_cost: Decimal | None = None
    adjusted_cost: Decimal | None = None

    type: str | None = None
    operator: str | None = None
    adjust_num: Decimal | None = None

    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        str_strip_whitespace=True,
    )


class CatalogData(BaseModel):
    product: list[CatalogProduct]
    pagination: "CatalogPagination | None" = None

    model_config = ConfigDict(extra="ignore")


class CatalogPagination(BaseModel):
    current_page: int
    per_page: int
    total: int
    last_page: int

    model_config = ConfigDict(extra="ignore")


class CatalogAPIResponse(BaseModel):
    data: CatalogData

    model_config = ConfigDict(extra="ignore")


class DetectedMatchItem(BaseModel):
    """A detected item reduced to the fields the matcher needs."""

    id: int | None = None
    item_name: str = Field(min_length=1)
    measurement_type: str | None = None

    length: float | None = None
    width: float | None = None
    height: float | None = None
    count: int | None = None

    quantity: float | None = None
    unit: str | None = None

    model_config = ConfigDict(
        extra="ignore",
        from_attributes=True,
        str_strip_whitespace=True,
    )


class LLMProductMatchDecision(BaseModel):
    """The LLM may select only an ID; catalog data supplies the code."""

    selected_product_id: int | None
    confidence: float = Field(ge=0.0, le=1.0)


class ProductMatchCandidate(BaseModel):
    product_id: int
    matched_product: str
    code: str
    confidence: float = Field(ge=0.0, le=1.0)
    unit: str | None = None


class ProductMatchResult(BaseModel):
    item_id: int | None = None
    item_name: str

    matched: bool
    product_id: int | None = None
    matched_product: str | None = None
    code: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    detected_quantity: float | None = None
    detected_unit: str | None = None
    catalog_unit: str | None = None
    possible_matches: list[ProductMatchCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_match_fields(self):
        if self.matched and (not self.matched_product or not self.code):
            raise ValueError(
                "A matched result must include a catalog product and code"
            )

        if not self.matched and (self.matched_product or self.code):
            raise ValueError(
                "An unmatched result cannot include a product or code"
            )

        return self


class ProductMatchingResponse(BaseModel):
    job_id: int
    matches: list[ProductMatchResult]


CatalogProductInput = CatalogProduct | dict[str, Any] | Any
DetectedItemInput = DetectedMatchItem | dict[str, Any] | Any

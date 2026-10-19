from decimal import Decimal
from pydantic import BaseModel



class EstimateItemResponse(BaseModel):
    item_id: int
    item_name: str
    product_code: str
    product_name: str

    quantity: Decimal
    unit: str

    labor_unit_cost: Decimal
    material_unit_cost: Decimal
    misc_unit_cost: Decimal

    labor_total: Decimal
    material_total: Decimal
    misc_total: Decimal
    line_total: Decimal


class EstimateResponse(BaseModel):
    job_id: int
    status: str
    labor_total: Decimal
    material_total: Decimal
    misc_total: Decimal
    grand_total: Decimal
    items: list[EstimateItemResponse]
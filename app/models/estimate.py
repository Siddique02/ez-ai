from decimal import Decimal
from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from sqlalchemy import String


class TakeoffItemMatch(Base):
    __tablename__ = "takeoff_item_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    takeoff_item_id: Mapped[int] = mapped_column(
        ForeignKey("takeoff_items.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    catalog_product_id: Mapped[int | None]
    product_code: Mapped[str | None] = mapped_column(String(255))
    product_name: Mapped[str | None] = mapped_column(String(255))
    catalog_unit: Mapped[str | None] = mapped_column(String(50))

    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="review",
    )


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("takeoff_jobs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    labor_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4),
        nullable=False,
        default=0,
    )
    material_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4),
        nullable=False,
        default=0,
    )
    misc_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4),
        nullable=False,
        default=0,
    )
    grand_total: Mapped[Decimal] = mapped_column(
        Numeric(19, 4),
        nullable=False,
        default=0,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="completed",
    )


class EstimateItem(Base):
    __tablename__ = "estimate_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    takeoff_item_id: Mapped[int] = mapped_column(
        ForeignKey("takeoff_items.id"),
        nullable=False,
    )

    catalog_product_id: Mapped[int] = mapped_column(nullable=False)
    product_code: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(19, 4),
        nullable=False,
    )

    labor_unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    material_unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    misc_unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 4))

    labor_total: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    material_total: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    misc_total: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(19, 4))
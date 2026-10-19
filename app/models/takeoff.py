from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, DateTime
from datetime import UTC, datetime
from app.core.database import Base
from sqlalchemy import JSON, Float, ForeignKey


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TakeoffJob(Base):

    __tablename__ = "takeoff_jobs"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="uploaded"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now
    )


class TakeoffItem(Base):

    __tablename__ = "takeoff_items"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("takeoff_jobs.id"),
        nullable=False
    )

    item_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    measurement_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    length: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    width: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    height: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )

    unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    confidence: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )


class TakeoffItemEdit(Base):
    """One user correction of the AI takeoff: the item before and after."""

    __tablename__ = "takeoff_item_edits"

    id: Mapped[int] = mapped_column(primary_key=True)

    job_id: Mapped[int] = mapped_column(
        ForeignKey("takeoff_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # No foreign key: the history must survive when the item is deleted.
    takeoff_item_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )

    # "create", "update" or "delete".
    action: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    before: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True
    )

    after: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now,
        nullable=False
    )

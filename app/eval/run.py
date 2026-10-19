"""Score a stored takeoff job against a project's gold reference.

Usage:
    python -m app.eval.run --job 6 --project el_sereno

It reads the job's items straight from the database, scores them, and prints a
per-line table plus the headline numbers. Nothing here calls the AI, so it is
cheap to run on every change and safe to put in CI.
"""

from __future__ import annotations
import argparse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.eval.gold import PROJECTS
from app.eval.scorer import GoldItem, ScoreReport, score_takeoff
from app.models.takeoff import TakeoffItem


def load_job_items(db: Session, job_id: int) -> list[dict]:
    rows = db.execute(
        select(TakeoffItem).where(TakeoffItem.job_id == job_id)
    ).scalars().all()
    return [
        {
            "item_name": row.item_name,
            "unit": row.unit,
            "quantity": row.quantity,
            "measurement_type": row.measurement_type,
            "count": row.count,
        }
        for row in rows
    ]


def format_report(report: ScoreReport, project: str, job_id: int) -> str:
    lines = [
        f"Takeoff score - job {job_id} vs gold '{project}'",
        "=" * 68,
        f"{'scope':24} {'expected':>10} {'produced':>10} {'err':>7}  result",
        "-" * 68,
    ]
    for line in report.lines:
        produced = (
            f"{line.produced_quantity:,.1f}"
            if line.produced_quantity is not None
            else "-"
        )
        err = (
            f"{line.error_ratio * 100:+.0f}%"
            if line.error_ratio is not None
            else "-"
        )
        if not line.found:
            result = "MISSING"
        elif line.within_tolerance:
            result = "ok"
        else:
            result = "off"
        lines.append(
            f"{line.gold.label[:24]:24} {line.gold.expected:>10,.1f} "
            f"{produced:>10} {err:>7}  {result}"
        )
    lines.append("-" * 68)
    lines.append(
        f"coverage {report.coverage*100:5.0f}%   "
        f"accuracy-on-found {report.accuracy*100:5.0f}%   "
        f"OVERALL {report.overall:5.1f}/100"
    )
    return "\n".join(lines)


def score_job(job_id: int, project: str) -> ScoreReport:
    gold: list[GoldItem] = PROJECTS[project]
    db = SessionLocal()
    try:
        produced = load_job_items(db, job_id)
    finally:
        db.close()
    return score_takeoff(produced, gold)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a takeoff job against gold.")
    parser.add_argument("--job", type=int, required=True, help="takeoff job id")
    parser.add_argument(
        "--project",
        choices=sorted(PROJECTS),
        required=True,
        help="which gold reference to score against",
    )
    args = parser.parse_args()

    report = score_job(args.job, args.project)
    print(format_report(report, args.project, args.job))


if __name__ == "__main__":
    main()

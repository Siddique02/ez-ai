"""Tests for the async analysis split.

Two halves, tested independently (no Redis or worker needed):
- AnalyzeEnqueueTests: the endpoint claims the job and enqueues a task.
- RunAnalysisTests: run_takeoff_analysis does the work and persists the result.
"""

import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.estimate import Estimate, EstimateItem, TakeoffItemMatch
from app.models.takeoff import TakeoffItem, TakeoffJob
from app.schemas.ai import AIAnalysisResponse, DetectedItem
from app.services.analysis_runner import run_takeoff_analysis


def _new_analysis_result():
    return AIAnalysisResponse(
        items=[
            DetectedItem(
                item_name="New Window W1",
                measurement_type="count",
                width=4,
                height=4,
                count=3,
                quantity=None,
                unit="ea",
                confidence="high",
            )
        ]
    )


class _DbTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.session_factory = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _create_job(self, *, status="completed", with_item=True):
        with self.session_factory() as db:
            job = TakeoffJob(
                file_name="plan.pdf",
                file_path="uploads/takeoffs/plan.pdf",
                status=status,
            )
            db.add(job)
            db.flush()
            if with_item:
                db.add(
                    TakeoffItem(
                        job_id=job.id,
                        item_name="Old drywall",
                        measurement_type="area",
                        quantity=100,
                        unit="sqft",
                        confidence="high",
                    )
                )
            db.commit()
            return job.id


class AnalyzeEnqueueTests(_DbTestBase):
    """The endpoint is the fast half: it claims, enqueues, and returns at once."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def override_get_db():
            db = cls.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)
        super().tearDownClass()

    @patch("app.api.takeoff.analyze_takeoff_task")
    def test_completed_retry_reuses_without_enqueue(self, task):
        job_id = self._create_job()

        response = self.client.post(f"/takeoff/{job_id}/analyze")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertTrue(response.json()["reused"])
        task.delay.assert_not_called()

    @patch("app.api.takeoff.analyze_takeoff_task")
    def test_force_claims_and_enqueues(self, task):
        job_id = self._create_job()

        response = self.client.post(f"/takeoff/{job_id}/analyze?force=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processing")
        self.assertFalse(response.json()["reused"])
        # Enqueued with the pre-claim status and whether items existed.
        task.delay.assert_called_once_with(job_id, "completed", True)
        with self.session_factory() as db:
            self.assertEqual(db.get(TakeoffJob, job_id).status, "processing")

    @patch("app.api.takeoff.analyze_takeoff_task")
    def test_processing_job_rejects_second_request(self, task):
        job_id = self._create_job(status="processing", with_item=False)

        response = self.client.post(f"/takeoff/{job_id}/analyze")

        self.assertEqual(response.status_code, 409)
        task.delay.assert_not_called()

    @patch("app.api.takeoff.analyze_takeoff_task")
    def test_enqueue_failure_releases_the_claim(self, task):
        job_id = self._create_job(status="uploaded", with_item=False)
        task.delay.side_effect = RuntimeError("redis down")

        response = self.client.post(f"/takeoff/{job_id}/analyze")

        self.assertEqual(response.status_code, 503)
        with self.session_factory() as db:
            # Claim released, not stuck in "processing".
            self.assertEqual(db.get(TakeoffJob, job_id).status, "uploaded")


class RunAnalysisTests(_DbTestBase):
    """The runner is the slow half: it persists items and sets final status."""

    def _patch_session(self):
        return patch(
            "app.services.analysis_runner.SessionLocal", self.session_factory
        )

    @patch("app.services.analysis_runner.analyze_blueprint")
    def test_replaces_items_and_completes(self, analyze_blueprint):
        job_id = self._create_job(status="processing")
        analyze_blueprint.return_value = _new_analysis_result()

        with self._patch_session():
            count = run_takeoff_analysis(job_id, "completed", True)

        self.assertEqual(count, 1)
        with self.session_factory() as db:
            items = db.query(TakeoffItem).filter_by(job_id=job_id).all()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].item_name, "New Window W1")
            self.assertEqual(items[0].quantity, 3)
            self.assertEqual(db.get(TakeoffJob, job_id).status, "completed")

    @patch("app.services.analysis_runner.analyze_blueprint")
    def test_failure_keeps_previous_completed_result(self, analyze_blueprint):
        job_id = self._create_job(status="processing")
        analyze_blueprint.side_effect = RuntimeError("AI unavailable")

        with self._patch_session():
            with self.assertRaises(RuntimeError):
                run_takeoff_analysis(job_id, "completed", True)

        with self.session_factory() as db:
            items = db.query(TakeoffItem).filter_by(job_id=job_id).all()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].item_name, "Old drywall")
            self.assertEqual(db.get(TakeoffJob, job_id).status, "completed")

    @patch("app.services.analysis_runner.analyze_blueprint")
    def test_first_failure_marks_job_failed(self, analyze_blueprint):
        job_id = self._create_job(status="processing", with_item=False)
        analyze_blueprint.side_effect = RuntimeError("AI unavailable")

        with self._patch_session():
            with self.assertRaises(RuntimeError):
                run_takeoff_analysis(job_id, "uploaded", False)

        with self.session_factory() as db:
            self.assertEqual(db.get(TakeoffJob, job_id).status, "failed")
            self.assertEqual(db.query(TakeoffItem).count(), 0)

    @patch("app.services.analysis_runner.analyze_blueprint")
    def test_invalidates_matches_and_estimate(self, analyze_blueprint):
        job_id = self._create_job(status="processing")
        analyze_blueprint.return_value = _new_analysis_result()

        with self.session_factory() as db:
            item = db.query(TakeoffItem).filter_by(job_id=job_id).one()
            db.add(
                TakeoffItemMatch(
                    takeoff_item_id=item.id,
                    catalog_product_id=10,
                    product_code="DW-10",
                    product_name="Drywall",
                    catalog_unit="sqft",
                    confidence=Decimal("0.9500"),
                    status="matched",
                )
            )
            estimate = Estimate(
                job_id=job_id,
                labor_total=Decimal("100"),
                material_total=Decimal("200"),
                misc_total=Decimal("0"),
                grand_total=Decimal("300"),
                status="completed",
            )
            db.add(estimate)
            db.flush()
            db.add(
                EstimateItem(
                    estimate_id=estimate.id,
                    takeoff_item_id=item.id,
                    catalog_product_id=10,
                    product_code="DW-10",
                    product_name="Drywall",
                    unit="sqft",
                    quantity=Decimal("100"),
                    labor_unit_cost=Decimal("1"),
                    material_unit_cost=Decimal("2"),
                    misc_unit_cost=Decimal("0"),
                    labor_total=Decimal("100"),
                    material_total=Decimal("200"),
                    misc_total=Decimal("0"),
                    line_total=Decimal("300"),
                )
            )
            db.commit()

        with self._patch_session():
            run_takeoff_analysis(job_id, "completed", True)

        with self.session_factory() as db:
            self.assertEqual(db.query(TakeoffItemMatch).count(), 0)
            self.assertEqual(db.query(Estimate).count(), 0)
            self.assertEqual(db.query(EstimateItem).count(), 0)


if __name__ == "__main__":
    unittest.main()

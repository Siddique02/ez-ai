import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.estimate import Estimate, EstimateItem, TakeoffItemMatch
from app.models.takeoff import TakeoffItem, TakeoffItemEdit, TakeoffJob


class TakeoffItemEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.session_factory = sessionmaker(bind=cls.engine)

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
        cls.engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _create_takeoff(self, *, status="completed"):
        """A job with a matched door, a matched stucco item and an estimate."""
        with self.session_factory() as db:
            job = TakeoffJob(
                file_name="plan.pdf",
                file_path="uploads/takeoffs/plan.pdf",
                status=status,
            )
            db.add(job)
            db.flush()

            door = TakeoffItem(
                job_id=job.id,
                item_name="New Door D1",
                measurement_type="count",
                width=2.6667,
                height=5.6667,
                count=5,
                quantity=5,
                unit="ea",
                confidence="high",
            )
            stucco = TakeoffItem(
                job_id=job.id,
                item_name="Exterior Stucco Finish",
                measurement_type="area",
                length=140,
                height=9,
                quantity=1260,
                unit="sqft",
                confidence="medium",
            )
            db.add_all([door, stucco])
            db.flush()

            for item, product_id in ((door, 1), (stucco, 2)):
                db.add(
                    TakeoffItemMatch(
                        takeoff_item_id=item.id,
                        catalog_product_id=product_id,
                        product_code=f"P-{product_id}",
                        product_name=f"Product {product_id}",
                        catalog_unit=item.unit,
                        confidence=Decimal("0.9000"),
                        status="matched",
                    )
                )

            estimate = Estimate(
                job_id=job.id,
                labor_total=Decimal("10"),
                material_total=Decimal("20"),
                misc_total=Decimal("0"),
                grand_total=Decimal("30"),
                status="completed",
            )
            db.add(estimate)
            db.flush()
            db.add(
                EstimateItem(
                    estimate_id=estimate.id,
                    takeoff_item_id=door.id,
                    catalog_product_id=1,
                    product_code="P-1",
                    product_name="Product 1",
                    unit="ea",
                    quantity=Decimal("5"),
                    labor_unit_cost=Decimal("1"),
                    material_unit_cost=Decimal("2"),
                    misc_unit_cost=Decimal("0"),
                    labor_total=Decimal("5"),
                    material_total=Decimal("10"),
                    misc_total=Decimal("0"),
                    line_total=Decimal("15"),
                )
            )
            db.commit()
            return job.id, door.id, stucco.id

    def test_correcting_a_count_recalculates_quantity_and_logs_the_edit(self):
        job_id, door_id, _ = self._create_takeoff()

        response = self.client.patch(
            f"/takeoff/{job_id}/items/{door_id}",
            json={"count": 7, "height": 6.6667},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["count"], 7)
        self.assertEqual(body["quantity"], 7)
        self.assertEqual(body["height"], 6.6667)
        self.assertEqual(body["item_name"], "New Door D1")

        with self.session_factory() as db:
            # The estimate is out of date; the match still fits the item.
            self.assertEqual(db.query(Estimate).count(), 0)
            self.assertEqual(db.query(EstimateItem).count(), 0)
            self.assertEqual(
                db.query(TakeoffItemMatch).filter_by(takeoff_item_id=door_id).count(),
                1,
            )

            edit = db.query(TakeoffItemEdit).one()
            self.assertEqual(edit.action, "update")
            self.assertEqual(edit.takeoff_item_id, door_id)
            self.assertEqual(edit.before["count"], 5)
            self.assertEqual(edit.before["height"], 5.6667)
            self.assertEqual(edit.after["count"], 7)
            self.assertEqual(edit.after["quantity"], 7)

    def test_renaming_an_item_removes_only_its_match(self):
        job_id, door_id, stucco_id = self._create_takeoff()

        response = self.client.patch(
            f"/takeoff/{job_id}/items/{door_id}",
            json={"item_name": "New Pocket Door D1"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        with self.session_factory() as db:
            matched_ids = {
                match.takeoff_item_id for match in db.query(TakeoffItemMatch)
            }
        self.assertEqual(matched_ids, {stucco_id})

    def test_quantity_that_contradicts_dimensions_is_rejected(self):
        job_id, _, stucco_id = self._create_takeoff()

        response = self.client.patch(
            f"/takeoff/{job_id}/items/{stucco_id}",
            json={"quantity": 1500},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["calculated_quantity"], 1260)
        with self.session_factory() as db:
            self.assertEqual(db.get(TakeoffItem, stucco_id).quantity, 1260)
            self.assertEqual(db.query(TakeoffItemEdit).count(), 0)
            self.assertEqual(db.query(Estimate).count(), 1)

    def test_quantity_can_be_entered_directly_after_clearing_dimensions(self):
        job_id, _, stucco_id = self._create_takeoff()

        # A net wall area, with the window and door openings deducted.
        response = self.client.patch(
            f"/takeoff/{job_id}/items/{stucco_id}",
            json={"length": None, "height": None, "quantity": 1180.5},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["quantity"], 1180.5)
        self.assertIsNone(body["length"])
        self.assertIsNone(body["height"])

    def test_changing_dimensions_recalculates_an_area(self):
        job_id, _, stucco_id = self._create_takeoff()

        response = self.client.patch(
            f"/takeoff/{job_id}/items/{stucco_id}",
            json={"length": 180.5},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["quantity"], 1624.5)

    def test_adding_a_missing_item(self):
        job_id, _, _ = self._create_takeoff()

        response = self.client.post(
            f"/takeoff/{job_id}/items",
            json={
                "item_name": "Vinyl Plank Flooring",
                "measurement_type": "area",
                "length": 30,
                "width": 20,
                "unit": "sqft",
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["quantity"], 600)
        self.assertEqual(body["measurement_type"], "area")

        with self.session_factory() as db:
            self.assertEqual(db.query(TakeoffItem).filter_by(job_id=job_id).count(), 3)
            self.assertEqual(db.query(Estimate).count(), 0)
            edit = db.query(TakeoffItemEdit).one()
            self.assertEqual(edit.action, "create")
            self.assertIsNone(edit.before)
            self.assertEqual(edit.after["item_name"], "Vinyl Plank Flooring")

    def test_deleting_a_wrong_item(self):
        job_id, door_id, _ = self._create_takeoff()

        response = self.client.delete(f"/takeoff/{job_id}/items/{door_id}")

        self.assertEqual(response.status_code, 204, response.text)
        with self.session_factory() as db:
            self.assertIsNone(db.get(TakeoffItem, door_id))
            self.assertEqual(
                db.query(TakeoffItemMatch).filter_by(takeoff_item_id=door_id).count(),
                0,
            )
            self.assertEqual(db.query(Estimate).count(), 0)
            self.assertEqual(db.query(EstimateItem).count(), 0)

            # The history keeps what the AI had produced.
            edit = db.query(TakeoffItemEdit).one()
            self.assertEqual(edit.action, "delete")
            self.assertEqual(edit.before["item_name"], "New Door D1")
            self.assertIsNone(edit.after)

    def test_edit_that_changes_nothing_is_not_logged(self):
        job_id, door_id, _ = self._create_takeoff()

        response = self.client.patch(
            f"/takeoff/{job_id}/items/{door_id}",
            json={"count": 5},
        )

        self.assertEqual(response.status_code, 200, response.text)
        with self.session_factory() as db:
            self.assertEqual(db.query(TakeoffItemEdit).count(), 0)
            self.assertEqual(db.query(Estimate).count(), 1)

    def test_processing_job_cannot_be_edited(self):
        job_id, door_id, _ = self._create_takeoff(status="processing")

        response = self.client.patch(
            f"/takeoff/{job_id}/items/{door_id}",
            json={"count": 7},
        )

        self.assertEqual(response.status_code, 409, response.text)

    def test_item_from_another_job_is_not_found(self):
        job_id, _, _ = self._create_takeoff()
        _, other_door_id, _ = self._create_takeoff()

        response = self.client.delete(f"/takeoff/{job_id}/items/{other_door_id}")

        self.assertEqual(response.status_code, 404, response.text)

    def test_invalid_input_is_rejected(self):
        job_id, door_id, _ = self._create_takeoff()

        for payload in (
            {"cout": 7},
            {"count": 0},
            {"width": -3},
            {"item_name": None},
            {"item_name": "   "},
            {"measurement_type": "volume"},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch(
                    f"/takeoff/{job_id}/items/{door_id}",
                    json=payload,
                )
                self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()

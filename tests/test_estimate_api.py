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
from app.schemas.matching import CatalogProduct, ProductMatchResult


class EstimateAPITests(unittest.TestCase):
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

    def _create_takeoff(self, *, matched=True):
        with self.session_factory() as db:
            job = TakeoffJob(
                file_name="plan.pdf",
                file_path="uploads/takeoffs/plan.pdf",
                status="completed",
            )
            db.add(job)
            db.flush()
            item = TakeoffItem(
                job_id=job.id,
                item_name="Drywall",
                measurement_type="area",
                quantity=100,
                unit="sqft",
                confidence="high",
            )
            db.add(item)
            db.flush()

            if matched:
                db.add(
                    TakeoffItemMatch(
                        takeoff_item_id=item.id,
                        catalog_product_id=10,
                        product_code="DW-10",
                        product_name="Drywall installation",
                        catalog_unit="sqft",
                        confidence=Decimal("0.9500"),
                        status="matched",
                    )
                )

            db.commit()
            return job.id, item.id

    @staticmethod
    def _product(*, labor="2", material="3", misc="1", unit="sqft"):
        return CatalogProduct(
            id=10,
            code_name="DW-10",
            product_name="Drywall installation",
            description="Supply and install drywall",
            unit_of_measure=unit,
            labor_cost=Decimal(labor),
            material_cost=Decimal(material),
            misc_cost=Decimal(misc),
        )

    def test_estimate_is_created_reused_and_force_replaced(self):
        job_id, _ = self._create_takeoff()

        with patch(
            "app.api.takeoff.catalog_service.get_products",
            return_value=[self._product()],
        ) as get_products:
            first = self.client.post(f"/takeoff/{job_id}/estimate")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(Decimal(first.json()["grand_total"]), Decimal("600"))
        self.assertEqual(len(first.json()["items"]), 1)
        get_products.assert_called_once_with()

        with patch(
            "app.api.takeoff.catalog_service.get_products",
            side_effect=AssertionError("catalog should not be loaded"),
        ):
            reused = self.client.post(f"/takeoff/{job_id}/estimate")

        self.assertEqual(reused.status_code, 200, reused.text)
        self.assertEqual(
            Decimal(reused.json()["grand_total"]),
            Decimal("600"),
        )

        with patch(
            "app.api.takeoff.catalog_service.get_products",
            return_value=[self._product(labor="4", material="5")],
        ):
            replaced = self.client.post(
                f"/takeoff/{job_id}/estimate?force=true"
            )

        self.assertEqual(replaced.status_code, 200, replaced.text)
        self.assertEqual(
            Decimal(replaced.json()["grand_total"]),
            Decimal("1000"),
        )

        fetched = self.client.get(f"/takeoff/{job_id}/estimate")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(
            Decimal(fetched.json()["grand_total"]),
            Decimal("1000"),
        )

        with self.session_factory() as db:
            self.assertEqual(db.query(Estimate).count(), 1)
            self.assertEqual(db.query(EstimateItem).count(), 1)

    def test_estimate_requires_every_item_to_be_matched(self):
        job_id, item_id = self._create_takeoff(matched=False)

        with patch(
            "app.api.takeoff.catalog_service.get_products"
        ) as get_products:
            response = self.client.post(f"/takeoff/{job_id}/estimate")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["items"][0]["item_id"], item_id)
        get_products.assert_not_called()

    def test_unsupported_catalog_unit_returns_review_response(self):
        job_id, item_id = self._create_takeoff()

        with patch(
            "app.api.takeoff.catalog_service.get_products",
            return_value=[self._product(unit="LS")],
        ):
            response = self.client.post(f"/takeoff/{job_id}/estimate")

        self.assertEqual(response.status_code, 409, response.text)
        issue = response.json()["detail"]["items"][0]
        self.assertEqual(issue["item_id"], item_id)
        self.assertIn("Unsupported catalog unit", issue["reason"])

        with self.session_factory() as db:
            self.assertEqual(db.query(Estimate).count(), 0)

    def test_matching_results_are_replaced_not_duplicated(self):
        job_id, item_id = self._create_takeoff(matched=False)
        product = self._product()
        matched_result = ProductMatchResult(
            item_id=item_id,
            item_name="Drywall",
            matched=True,
            product_id=product.id,
            matched_product=product.product_name,
            code=product.code_name,
            confidence=0.95,
            detected_quantity=100,
            detected_unit="sqft",
            catalog_unit="sqft",
        )

        with (
            patch(
                "app.api.takeoff.catalog_service.get_products",
                return_value=[product],
            ),
            patch(
                "app.api.takeoff.match_products",
                return_value=[matched_result],
            ),
        ):
            first = self.client.post(f"/takeoff/{job_id}/match")
            second = self.client.post(f"/takeoff/{job_id}/match")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        with self.session_factory() as db:
            self.assertEqual(db.query(TakeoffItemMatch).count(), 1)
            stored = db.query(TakeoffItemMatch).one()
            self.assertEqual(stored.catalog_product_id, product.id)
            self.assertEqual(stored.product_code, product.code_name)


if __name__ == "__main__":
    unittest.main()

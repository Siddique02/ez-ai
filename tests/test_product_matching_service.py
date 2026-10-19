import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.schemas.matching import (
    CatalogAPIResponse,
    DetectedMatchItem,
    LLMProductMatchDecision,
)
from app.services.product_matching_service import (
    OpenAIEmbeddingRetriever,
    ProductMatchingService,
    ProductMatchingServiceError,
    RankedCatalogProduct,
)


class StaticRetriever:
    def __init__(self):
        self.received_products = []

    def retrieve(self, items, products, *, top_k):
        self.received_products = list(products)
        candidates = [
            RankedCatalogProduct(product=product, similarity=0.90)
            for product in products[:top_k]
        ]
        return [candidates for _ in items]


class SelectingReranker:
    def __init__(self, decisions):
        self._decisions = decisions
        self.call_count = 0

    def choose(self, item, candidates):
        self.call_count += 1
        product_id, confidence = self._decisions[item.item_name]
        return LLMProductMatchDecision(
            selected_product_id=product_id,
            confidence=confidence,
        )


class FakeEmbeddingEndpoint:
    def __init__(self):
        self.call_count = 0

    def create(self, *, model, input, dimensions, encoding_format):
        self.call_count += 1
        data = []
        for index, text in enumerate(input):
            if "Gypsum wallboard" in text or "drywall" in text:
                vector = [1.0, 0.0]
            else:
                vector = [0.0, 1.0]
            data.append(SimpleNamespace(index=index, embedding=vector))
        return SimpleNamespace(data=data)


class FakeOpenAIClient:
    def __init__(self):
        self.embeddings = FakeEmbeddingEndpoint()


def _service(decisions, *, threshold=0.75):
    reranker = SelectingReranker(decisions)
    service = ProductMatchingService(
        retriever=StaticRetriever(),
        reranker=reranker,
        candidate_count=8,
        confidence_threshold=threshold,
    )
    return service, reranker


class ProductMatchingServiceTests(unittest.TestCase):
    def test_embedding_retriever_finds_semantically_related_candidate(self):
        client = FakeOpenAIClient()
        retriever = OpenAIEmbeddingRetriever(
            client,
            model="test-embedding-model",
            dimensions=2,
            batch_size=10,
        )
        products = CatalogAPIResponse.model_validate(
            {
                "data": {
                    "product": [
                        {
                            "id": 1,
                            "product_name": "Gypsum wallboard",
                            "code_name": "GWB-1",
                            "description": "Interior wall panel",
                        },
                        {
                            "id": 2,
                            "product_name": "Concrete slab",
                            "code_name": "CONC-1",
                            "description": "Concrete flatwork",
                        },
                    ]
                }
            }
        ).data.product
        item = DetectedMatchItem(item_name="drywall")
        first = retriever.retrieve([item], products, top_k=1)
        second = retriever.retrieve([item], products, top_k=1)

        self.assertEqual(first[0][0].product.id, 1)
        self.assertEqual(second[0][0].product.id, 1)
        # One catalog embedding call plus one query call for each retrieval.
        self.assertEqual(client.embeddings.call_count, 3)

    def test_code_always_comes_from_selected_catalog_product(self):
        service, _ = _service({"gypsum wallboard": (2694, 0.94)})
        results = service.match_products(
            [
                {
                    "item_name": "gypsum wallboard",
                    "quantity": 500,
                    "unit": "sq ft",
                    "code": "AI-MUST-NOT-BE-USED",
                }
            ],
            [
                {
                    "id": 2694,
                    "product_name": "Drywall",
                    "code_name": "gcdrywall",
                    "description": "Supply and install gypsum wallboard",
                    "unit_of_measure": "sqft",
                }
            ],
        )

        result = results[0]
        self.assertTrue(result.matched)
        self.assertEqual(result.matched_product, "Drywall")
        self.assertEqual(result.code, "gcdrywall")
        self.assertEqual(result.confidence, 0.94)
        self.assertEqual(result.detected_quantity, 500)
        self.assertEqual(result.detected_unit, "sq ft")
        self.assertEqual(result.catalog_unit, "sqft")

    def test_low_confidence_returns_unmatched(self):
        service, _ = _service({"unknown item": (1, 0.40)})
        result = service.match_products(
            [{"item_name": "unknown item"}],
            [
                {
                    "id": 1,
                    "product_name": "Demo drywall",
                    "code_name": "DMdrywall",
                    "description": "Demolition of drywall",
                    "unit_of_measure": "sqft",
                }
            ],
        )[0]

        self.assertFalse(result.matched)
        self.assertIsNone(result.code)
        self.assertEqual(result.possible_matches, [])

    def test_null_selection_returns_unmatched(self):
        service, _ = _service({"unknown item": (None, 0.15)})
        result = service.match_products(
            [{"item_name": "unknown item"}],
            [
                {
                    "id": 1,
                    "product_name": "Demo drywall",
                    "code_name": "DMdrywall",
                    "description": "Demolition of drywall",
                    "unit_of_measure": "sqft",
                }
            ],
        )[0]

        self.assertFalse(result.matched)
        self.assertEqual(result.confidence, 0.15)

    def test_rejects_product_id_outside_retrieved_candidates(self):
        service, _ = _service({"drywall": (999, 0.99)})
        with self.assertRaises(ProductMatchingServiceError):
            service.match_products(
                [{"item_name": "drywall"}],
                [
                    {
                        "id": 1,
                        "product_name": "Drywall",
                        "code_name": "DW-1",
                        "description": "Drywall product",
                        "unit_of_measure": "sqft",
                    }
                ],
            )

    def test_reuses_decision_for_duplicate_detected_items(self):
        service, reranker = _service({"Drywall": (1, 0.92)})
        results = service.match_products(
            [{"item_name": "Drywall"}, {"item_name": "Drywall"}],
            [
                {
                    "id": 1,
                    "product_name": "Gypsum wallboard",
                    "code_name": "GWB-1",
                    "description": "Interior drywall panel",
                    "unit_of_measure": "sqft",
                }
            ],
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(reranker.call_count, 1)

    def test_products_with_unpriceable_units_are_never_offered(self):
        retriever = StaticRetriever()
        service = ProductMatchingService(
            retriever=retriever,
            reranker=SelectingReranker({"Drywall": (1, 0.95)}),
            candidate_count=8,
            confidence_threshold=0.75,
        )
        service.match_products(
            [{"item_name": "Drywall"}],
            [
                {
                    "id": 1,
                    "product_name": "Drywall",
                    "code_name": "DW-1",
                    "unit_of_measure": "sq. ft.",
                },
                {
                    "id": 2,
                    "product_name": "Drywall crew",
                    "code_name": "DW-LS",
                    "unit_of_measure": "ls",
                },
                {
                    "id": 3,
                    "product_name": "Drywall typo",
                    "code_name": "DW-X",
                    "unit_of_measure": "sqdt",
                },
            ],
        )

        self.assertEqual(
            [product.id for product in retriever.received_products],
            [1],
        )

    def test_catalog_fixture_matches_php_contract(self):
        fixture_path = Path(__file__).resolve().parents[1] / "php-output"
        payload = CatalogAPIResponse.model_validate(
            json.loads(fixture_path.read_text(encoding="utf-8"))
        )

        self.assertGreater(len(payload.data.product), 0)
        self.assertTrue(payload.data.product[0].code_name)

    def test_rejects_invalid_configuration(self):
        reranker = SelectingReranker({})
        with self.assertRaises(ValueError):
            ProductMatchingService(
                retriever=StaticRetriever(),
                reranker=reranker,
                candidate_count=0,
                confidence_threshold=0.75,
            )
        with self.assertRaises(ValueError):
            ProductMatchingService(
                retriever=StaticRetriever(),
                reranker=reranker,
                candidate_count=8,
                confidence_threshold=1.1,
            )


if __name__ == "__main__":
    unittest.main()

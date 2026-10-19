import unittest
from unittest.mock import Mock, patch

from app.services.catalog_service import CatalogService, CatalogServiceError


def _catalog_page(
    *,
    page: int,
    last_page: int,
    total: int,
    product_id: int,
) -> dict:
    return {
        "data": {
            "product": [
                {
                    "id": product_id,
                    "code_name": f"CODE-{product_id}",
                    "product_name": f"Product {product_id}",
                    "description": "Catalog product",
                    "unit_of_measure": "ea",
                }
            ],
            "pagination": {
                "current_page": page,
                "per_page": 1,
                "total": total,
                "last_page": last_page,
            },
        }
    }


def _response(payload: dict) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


class CatalogServiceTests(unittest.TestCase):
    @patch("app.services.catalog_service.httpx.Client")
    def test_fetches_all_pages_and_caches_complete_catalog(self, client_class):
        client = client_class.return_value.__enter__.return_value
        pages = {
            1: _response(
                _catalog_page(page=1, last_page=2, total=2, product_id=10)
            ),
            2: _response(
                _catalog_page(page=2, last_page=2, total=2, product_id=20)
            ),
        }
        client.get.side_effect = lambda _url, params: pages[params["page"]]

        service = CatalogService(
            "https://catalog.test/products",
            page_size=1,
            parallel_requests=1,
        )

        first_result = service.get_products()
        second_result = service.get_products()

        self.assertEqual([product.id for product in first_result], [10, 20])
        self.assertEqual([product.id for product in second_result], [10, 20])
        self.assertEqual(client.get.call_count, 2)

    @patch("app.services.catalog_service.httpx.Client")
    def test_rejects_incomplete_paginated_catalog(self, client_class):
        client = client_class.return_value.__enter__.return_value
        pages = {
            1: _response(
                _catalog_page(page=1, last_page=2, total=3, product_id=10)
            ),
            2: _response(
                _catalog_page(page=2, last_page=2, total=3, product_id=20)
            ),
        }
        client.get.side_effect = lambda _url, params: pages[params["page"]]

        service = CatalogService(
            "https://catalog.test/products",
            page_size=1,
            parallel_requests=1,
        )

        with self.assertRaises(CatalogServiceError):
            service.get_products()


if __name__ == "__main__":
    unittest.main()

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from time import monotonic
import httpx
from app.core.config import settings
from app.schemas.matching import CatalogAPIResponse, CatalogProduct


class CatalogServiceError(RuntimeError):
    pass


class CatalogService:
    """Read-only client for the PHP product catalog."""

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 15.0,
        cache_ttl_seconds: int = 300,
        page_size: int = 100,
        max_pages: int = 200,
        parallel_requests: int = 4,
    ) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._page_size = page_size
        self._max_pages = max_pages
        self._parallel_requests = parallel_requests
        self._cached_products: tuple[CatalogProduct, ...] = ()
        self._cache_expires_at = 0.0
        self._cache_lock = Lock()

    def get_products(self, *, refresh: bool = False) -> list[CatalogProduct]:
        now = monotonic()
        if (
            not refresh
            and self._cached_products
            and now < self._cache_expires_at
        ):
            return list(self._cached_products)

        with self._cache_lock:
            now = monotonic()
            if (
                not refresh
                and self._cached_products
                and now < self._cache_expires_at
            ):
                return list(self._cached_products)

            try:
                with httpx.Client(
                    timeout=self._timeout_seconds,
                    follow_redirects=True,
                ) as client:
                    first_page = self._fetch_page(client, 1)
                    products = list(first_page.data.product)

                    pagination = first_page.data.pagination
                    last_page = pagination.last_page if pagination else 1
                    if last_page > self._max_pages:
                        raise CatalogServiceError(
                            "The PHP catalog exceeds the configured page limit"
                        )

                    if last_page > 1:
                        pages: dict[int, list[CatalogProduct]] = {}
                        with ThreadPoolExecutor(
                            max_workers=self._parallel_requests
                        ) as executor:
                            futures = {
                                executor.submit(self._fetch_page, client, page): page
                                for page in range(2, last_page + 1)
                            }
                            for future in as_completed(futures):
                                page = futures[future]
                                pages[page] = future.result().data.product

                        for page in range(2, last_page + 1):
                            products.extend(pages[page])
            except (httpx.HTTPError, ValueError) as exc:
                raise CatalogServiceError(
                    "Unable to load the PHP product catalog"
                ) from exc

            if not products:
                raise CatalogServiceError("The PHP product catalog is empty")

            products_by_id = {product.id: product for product in products}
            if pagination and len(products_by_id) != pagination.total:
                raise CatalogServiceError(
                    "The PHP product catalog response was incomplete"
                )
            self._cached_products = tuple(products_by_id.values())
            self._cache_expires_at = monotonic() + self._cache_ttl_seconds
            return list(self._cached_products)

    def _fetch_page(
        self,
        client: httpx.Client,
        page: int,
    ) -> CatalogAPIResponse:
        response = client.get(
            self._url,
            params={
                "page": page,
                "per_page": self._page_size,
            },
        )
        response.raise_for_status()
        return CatalogAPIResponse.model_validate(response.json())


catalog_service = CatalogService(
    settings.catalog_api_url,
    timeout_seconds=settings.catalog_request_timeout_seconds,
    cache_ttl_seconds=settings.catalog_cache_ttl_seconds,
    page_size=settings.catalog_page_size,
    max_pages=settings.catalog_max_pages,
    parallel_requests=settings.catalog_parallel_requests,
)

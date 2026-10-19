import hashlib
import json
import math
from dataclasses import dataclass
from threading import Lock
from typing import Protocol, Sequence

from openai import OpenAIError, RateLimitError

from app.core.config import settings
from app.core.tracing import OpenAI, langfuse, observe
from app.schemas.matching import (
    CatalogProduct,
    CatalogProductInput,
    DetectedItemInput,
    DetectedMatchItem,
    LLMProductMatchDecision,
    ProductMatchResult,
)
from app.services.quantity_conversion_service import is_supported_unit


class ProductMatchingServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RankedCatalogProduct:
    product: CatalogProduct
    similarity: float


class ProductCandidateRetriever(Protocol):
    def retrieve(
        self,
        items: Sequence[DetectedMatchItem],
        products: Sequence[CatalogProduct],
        *,
        top_k: int,
    ) -> list[list[RankedCatalogProduct]]:
        ...


class ProductCandidateReranker(Protocol):
    def choose(
        self,
        item: DetectedMatchItem,
        candidates: Sequence[RankedCatalogProduct],
    ) -> LLMProductMatchDecision:
        ...


class OpenAIEmbeddingRetriever:
    """Retrieve semantically related catalog products using embeddings."""

    def __init__(
        self,
        client: OpenAI,
        *,
        model: str,
        dimensions: int,
        batch_size: int,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._catalog_fingerprint: str | None = None
        self._catalog_embeddings: tuple[tuple[float, ...], ...] = ()
        self._cache_lock = Lock()

    def retrieve(
        self,
        items: Sequence[DetectedMatchItem],
        products: Sequence[CatalogProduct],
        *,
        top_k: int,
    ) -> list[list[RankedCatalogProduct]]:
        if not items:
            return []
        if not products:
            return [[] for _ in items]

        catalog_embeddings = self._get_catalog_embeddings(products)
        unique_item_texts = list(
            dict.fromkeys(self._item_text(item) for item in items)
        )
        unique_item_embeddings = self._create_embeddings(unique_item_texts)
        item_embeddings_by_text = dict(
            zip(unique_item_texts, unique_item_embeddings, strict=True)
        )

        rankings: list[list[RankedCatalogProduct]] = []
        candidate_limit = min(top_k, len(products))
        for item in items:
            item_embedding = item_embeddings_by_text[self._item_text(item)]
            scored_products = (
                RankedCatalogProduct(
                    product=product,
                    similarity=self._cosine_similarity(
                        item_embedding,
                        product_embedding,
                    ),
                )
                for product, product_embedding in zip(
                    products,
                    catalog_embeddings,
                    strict=True,
                )
            )
            rankings.append(
                sorted(
                    scored_products,
                    key=lambda candidate: (
                        -candidate.similarity,
                        candidate.product.id,
                    ),
                )[:candidate_limit]
            )

        return rankings

    def _get_catalog_embeddings(
        self,
        products: Sequence[CatalogProduct],
    ) -> tuple[tuple[float, ...], ...]:
        fingerprint = self._fingerprint(products)
        if (
            fingerprint == self._catalog_fingerprint
            and self._catalog_embeddings
        ):
            return self._catalog_embeddings

        with self._cache_lock:
            if (
                fingerprint == self._catalog_fingerprint
                and self._catalog_embeddings
            ):
                return self._catalog_embeddings

            embeddings = self._create_embeddings(
                [self._product_text(product) for product in products]
            )
            self._catalog_fingerprint = fingerprint
            self._catalog_embeddings = tuple(embeddings)
            return self._catalog_embeddings

    def _create_embeddings(
        self,
        texts: Sequence[str],
    ) -> list[tuple[float, ...]]:
        embeddings: list[tuple[float, ...]] = []
        try:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                response = self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                    dimensions=self._dimensions,
                    encoding_format="float",
                )
                ordered_data = sorted(response.data, key=lambda item: item.index)
                embeddings.extend(
                    self._normalize_vector(item.embedding)
                    for item in ordered_data
                )
        except RateLimitError as exc:
            raise ProductMatchingServiceError(
                "OpenAI API quota or rate limit prevented semantic retrieval"
            ) from exc
        except OpenAIError as exc:
            raise ProductMatchingServiceError(
                "Semantic catalog retrieval failed"
            ) from exc

        if len(embeddings) != len(texts):
            raise ProductMatchingServiceError(
                "The embedding response was incomplete"
            )
        return embeddings

    @staticmethod
    def _product_text(product: CatalogProduct) -> str:
        return "\n".join(
            (
                f"Product name: {product.product_name or ''}",
                f"Code name: {product.code_name}",
                f"Description: {product.description}",
                f"Unit: {product.unit_of_measure or ''}",
            )
        )

    @staticmethod
    def _item_text(item: DetectedMatchItem) -> str:
        return "\n".join(
            (
                f"Construction takeoff item: {item.item_name}",
                f"Unit: {item.unit or ''}",
            )
        )

    @classmethod
    def _fingerprint(cls, products: Sequence[CatalogProduct]) -> str:
        digest = hashlib.sha256()
        for product in products:
            digest.update(cls._product_text(product).encode("utf-8"))
            digest.update(str(product.id).encode("ascii"))
            digest.update(b"\x00")
        return digest.hexdigest()

    @staticmethod
    def _normalize_vector(vector: Sequence[float]) -> tuple[float, ...]:
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return tuple(float(value) for value in vector)
        return tuple(float(value) / magnitude for value in vector)

    @staticmethod
    def _cosine_similarity(
        left: Sequence[float],
        right: Sequence[float],
    ) -> float:
        return sum(
            left_value * right_value
            for left_value, right_value in zip(left, right, strict=True)
        )


class OpenAIProductReranker:
    """Choose only from retrieved PHP catalog products."""

    _INSTRUCTIONS = """
You match one AI-detected construction takeoff item to an authoritative product
catalog. Understand construction synonyms and equivalent trade terminology, but
do not treat different work scopes as equivalent. Demolition, installation,
repair, painting, material supply, sizes, assemblies, and units can materially
change the correct product.

Select exactly one supplied product ID only when it is a strong match. Return a
null product ID when no candidate is suitable or when the choice is materially
ambiguous. Never invent an ID or product. Confidence must reflect certainty that
the detected item and selected catalog product represent the same billable work.
""".strip()

    def __init__(self, client: OpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    def choose(
        self,
        item: DetectedMatchItem,
        candidates: Sequence[RankedCatalogProduct],
    ) -> LLMProductMatchDecision:
        payload = {
            "detected_item": {
                "item_name": item.item_name,
                "quantity": item.quantity,
                "unit": item.unit,
            },
            "allowed_catalog_candidates": [
                {
                    "product_id": candidate.product.id,
                    "product_name": candidate.product.product_name,
                    "code_name": candidate.product.code_name,
                    "description": candidate.product.description[:1500],
                    "unit_of_measure": candidate.product.unit_of_measure,
                    "semantic_similarity": round(candidate.similarity, 4),
                }
                for candidate in candidates
            ],
        }

        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=self._INSTRUCTIONS,
                input=json.dumps(payload, ensure_ascii=False),
                text_format=LLMProductMatchDecision,
                temperature=0,
                store=False,
            )
        except RateLimitError as exc:
            raise ProductMatchingServiceError(
                "OpenAI API quota or rate limit prevented catalog selection"
            ) from exc
        except OpenAIError as exc:
            raise ProductMatchingServiceError(
                "Catalog candidate selection failed"
            ) from exc

        decision = response.output_parsed
        if decision is None:
            raise ProductMatchingServiceError(
                "The product matching model returned no decision"
            )
        return decision


class ProductMatchingService:
    def __init__(
        self,
        retriever: ProductCandidateRetriever,
        reranker: ProductCandidateReranker,
        *,
        candidate_count: int,
        confidence_threshold: float,
    ) -> None:
        if candidate_count < 1:
            raise ValueError("candidate_count must be at least 1")
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")

        self._retriever = retriever
        self._reranker = reranker
        self._candidate_count = candidate_count
        self._confidence_threshold = confidence_threshold

    # The whole catalog is too large to store in every trace; a summary of
    # the inputs is recorded below instead.
    @observe(name="match-products", capture_input=False)
    def match_products(
        self,
        detected_items: Sequence[DetectedItemInput],
        catalog_products: Sequence[CatalogProductInput],
    ) -> list[ProductMatchResult]:
        items = [_coerce_detected_item(item) for item in detected_items]
        # A product whose unit cannot be converted could never be priced, so
        # it must not be offered as a match.
        products = [
            product
            for raw_product in catalog_products
            if (product := _coerce_catalog_product(raw_product)).product_name
            and is_supported_unit(product.unit_of_measure)
        ]
        langfuse.update_current_span(
            input={
                "items": [item.item_name for item in items],
                "catalog_products": len(catalog_products),
                "priceable_products": len(products),
            }
        )

        rankings = self._retriever.retrieve(
            items,
            products,
            top_k=self._candidate_count,
        )
        if len(rankings) != len(items):
            raise ProductMatchingServiceError(
                "Candidate retrieval returned an invalid result count"
            )

        decisions: dict[
            tuple[str, str | None, tuple[int, ...]],
            LLMProductMatchDecision,
        ] = {}
        results: list[ProductMatchResult] = []

        for item, candidates in zip(items, rankings, strict=True):
            if not candidates:
                results.append(_unmatched_result(item, confidence=0.0))
                continue

            candidate_ids = tuple(
                candidate.product.id for candidate in candidates
            )
            decision_key = (
                item.item_name.casefold(),
                item.unit.casefold() if item.unit else None,
                candidate_ids,
            )
            decision = decisions.get(decision_key)
            if decision is None:
                decision = self._reranker.choose(item, candidates)
                decisions[decision_key] = decision

            candidate_by_id = {
                candidate.product.id: candidate.product
                for candidate in candidates
            }
            if decision.selected_product_id is None:
                results.append(
                    _unmatched_result(item, confidence=decision.confidence)
                )
                continue

            product = candidate_by_id.get(decision.selected_product_id)
            if product is None:
                raise ProductMatchingServiceError(
                    "The model selected a product outside the allowed catalog candidates"
                )

            if decision.confidence < self._confidence_threshold:
                results.append(
                    _unmatched_result(item, confidence=decision.confidence)
                )
                continue

            results.append(
                ProductMatchResult(
                    item_id=item.id,
                    item_name=item.item_name,
                    matched=True,
                    product_id=product.id,
                    matched_product=product.product_name,
                    code=product.code_name,
                    confidence=round(decision.confidence, 4),
                    detected_quantity=item.quantity,
                    detected_unit=item.unit,
                    catalog_unit=product.unit_of_measure,
                )
            )

        return results


def _coerce_detected_item(item: DetectedItemInput) -> DetectedMatchItem:
    if isinstance(item, DetectedMatchItem):
        return item
    return DetectedMatchItem.model_validate(item, from_attributes=True)


def _coerce_catalog_product(product: CatalogProductInput) -> CatalogProduct:
    if isinstance(product, CatalogProduct):
        return product
    return CatalogProduct.model_validate(product, from_attributes=True)


def _unmatched_result(
    item: DetectedMatchItem,
    *,
    confidence: float,
) -> ProductMatchResult:
    return ProductMatchResult(
        item_id=item.id,
        item_name=item.item_name,
        matched=False,
        confidence=round(confidence, 4),
        detected_quantity=item.quantity,
        detected_unit=item.unit,
        catalog_unit=None,
        possible_matches=[],
    )


_openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

product_matching_service = ProductMatchingService(
    retriever=OpenAIEmbeddingRetriever(
        _openai_client,
        model=settings.product_match_embedding_model,
        dimensions=settings.product_match_embedding_dimensions,
        batch_size=settings.product_match_embedding_batch_size,
    ),
    reranker=OpenAIProductReranker(
        _openai_client,
        model=settings.product_match_model,
    ),
    candidate_count=settings.product_match_candidate_count,
    confidence_threshold=settings.product_match_confidence_threshold,
)


def match_products(
    detected_items: Sequence[DetectedItemInput],
    catalog_products: Sequence[CatalogProductInput],
) -> list[ProductMatchResult]:
    return product_matching_service.match_products(
        detected_items,
        catalog_products,
    )

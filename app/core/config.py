from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Takeoff API"
    app_env: str = "development"
    app_debug: bool = True
    database_url: str
    OPENAI_API_KEY: str
    # llm_model: str = "gpt-4.1-mini"
    llm_model: str = "gpt-6-luna"
    # "single" = one call reads the whole set (cheaper, default).
    # "pipeline" = focused per-trade passes (better coverage, ~6x the calls).
    analysis_mode: str = "pipeline"
    # Pipeline only: send each pass just its relevant pages (faster, cheaper).
    page_routing: bool = True
    # Pipeline only: how many passes run at once. Keep the burst under the TPM
    # limit (each routed pass is small; a few in parallel stays safe).
    pipeline_max_workers: int = 3
    max_upload_size_mb: int = 100
    catalog_api_url: str = "https://admin.ezestimater.com/api/public/code"
    catalog_request_timeout_seconds: float = 30.0
    catalog_cache_ttl_seconds: int = 300
    catalog_page_size: int = 100
    catalog_max_pages: int = 200
    catalog_parallel_requests: int = 4
    product_match_embedding_model: str = "text-embedding-3-small"
    product_match_embedding_dimensions: int = 512
    product_match_embedding_batch_size: int = 128
    product_match_model: str = "gpt-4.1-mini"
    product_match_candidate_count: int = 8
    product_match_confidence_threshold: float = 0.75
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST"),
    )
    allowed_file_types: list[str] = [
        "application/pdf",
        "image/png",
        "image/jpeg"
    ]
    # Celery/Redis: /0 carries the job queue (broker), /1 stores task bookkeeping
    # (result backend). The API writes jobs to the broker; workers read from it.
    celery_broker_url: str = "redis://localhost:6380/0"
    celery_result_backend: str = "redis://localhost:6380/1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()

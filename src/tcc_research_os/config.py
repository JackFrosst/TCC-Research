from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./tcc_research.db"
    redis_url: str = "redis://localhost:6379/0"
    academic_api_email: str = "research@example.com"
    academic_api_user_agent: str = "TCCResearchOS/0.2"
    openalex_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    request_timeout_seconds: float = Field(default=20, gt=0, le=120)
    max_results_per_provider: int = Field(default=100, ge=1, le=1000)
    max_results_per_query: int = Field(default=250, ge=1, le=5000)
    max_total_results_per_run: int = Field(default=5000, ge=1, le=50000)
    academic_page_size: int = Field(default=100, ge=1, le=1000)
    academic_max_retries: int = Field(default=3, ge=0, le=10)
    academic_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=30)
    allow_live_academic_search: bool = False
    pdf_storage_root: str = "storage"
    unpaywall_email: str | None = None
    max_pdf_size_mb: int = Field(default=100, ge=1, le=500)
    allow_pdf_downloads: bool = False
    pdf_download_timeout_seconds: float = Field(default=60, gt=0, le=300)
    scielo_articlemeta_url: str = "https://articlemeta.scielo.org"
    scielo_default_collection: str = "scl"
    repository_harvest_max_records: int = Field(default=500, ge=1, le=5000)
    repository_crawl_user_agent: str = "TCCResearchOS/0.2 (+academic-harvester)"


@lru_cache
def get_settings() -> Settings:
    return Settings()

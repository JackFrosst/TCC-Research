from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Provider(str, Enum):
    crossref = "crossref"
    openalex = "openalex"
    semantic_scholar = "semantic_scholar"
    dblp = "dblp"
    arxiv = "arxiv"
    openaire = "openaire"
    datacite = "datacite"
    europe_pmc = "europe_pmc"
    scielo = "scielo"
    scielo_crossref = "scielo_crossref"


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    title: str
    technical_focus: str


class CriterionInput(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{1,19}$")
    text: str = Field(min_length=5, max_length=1000)


class QueryInput(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{1,19}$")
    query: str = Field(min_length=3, max_length=4000)
    purpose: str = Field(min_length=3, max_length=500)
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


class ProjectCreate(BaseModel):
    slug: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    title: str = Field(min_length=5, max_length=500)
    technical_focus: str = Field(min_length=5, max_length=4000)
    research_question: str = Field(min_length=10, max_length=4000)
    year_from: int = Field(ge=1900, le=2100)
    year_to: int = Field(ge=1900, le=2100)
    languages: list[str] = Field(min_length=1, max_length=10)
    inclusion_criteria: list[CriterionInput] = Field(min_length=1, max_length=50)
    exclusion_criteria: list[CriterionInput] = Field(min_length=1, max_length=50)
    queries: list[QueryInput] = Field(min_length=1, max_length=100)
    created_by: str = Field(default="api", min_length=2, max_length=200)

    @model_validator(mode="after")
    def validate_protocol(self):
        if self.year_to < self.year_from:
            raise ValueError("year_to deve ser maior ou igual a year_from")
        if len(set(self.languages)) != len(self.languages):
            raise ValueError("languages não pode conter valores repetidos")
        for field_name in ("inclusion_criteria", "exclusion_criteria", "queries"):
            values = getattr(self, field_name)
            codes = [item.code.upper() for item in values]
            if len(set(codes)) != len(codes):
                raise ValueError(f"{field_name} não pode conter códigos repetidos")
        return self


class ProjectSetupOut(BaseModel):
    project: ProjectOut
    protocol: "ProtocolOut"


class QueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    query_text: str
    purpose: str
    language: str


class ProtocolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    version: int
    status: str
    research_question: str
    year_from: int
    year_to: int
    languages: list[str]
    inclusion_criteria: list[dict]
    exclusion_criteria: list[dict]
    approved_at: datetime | None
    approved_by: str | None
    queries: list[QueryOut] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=2, max_length=200)


class SearchRequest(BaseModel):
    providers: list[Provider] = [
        Provider.crossref,
        Provider.openalex,
        Provider.semantic_scholar,
        Provider.dblp,
        Provider.arxiv,
        Provider.openaire,
        Provider.datacite,
    ]
    max_results_per_query: int = Field(default=100, ge=1, le=5000)
    max_results_per_provider: int | None = Field(default=None, ge=1, le=1000)
    max_total_results: int = Field(default=2000, ge=1, le=50000)
    resume_failed: bool = False
    extend_completed: bool = False
    idempotency_key: str = Field(min_length=4, max_length=200)


class SearchMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    query_code: str
    pages_fetched: int
    records_returned: int
    records_ingested: int
    articles_created: int
    duplicates: int
    duration_ms: int
    completed: bool
    error: str | None


class SearchRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    protocol_id: str
    idempotency_key: str
    providers: list[str]
    status: str
    records_received: int
    articles_created: int
    error: str | None
    metrics: list[SearchMetricOut] = Field(default_factory=list)


class ArticleSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    provider_id: str


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    title: str
    abstract: str | None
    year: int | None
    journal: str | None
    doi: str | None
    language: str | None
    authors: list[dict]
    external_ids: dict
    document_type: str | None
    peer_reviewed: bool | None
    oa_locations: list[dict]
    sources: list[ArticleSourceOut]


class SnowballRequest(BaseModel):
    seed_article_ids: list[str] = Field(min_length=1, max_length=20)
    providers: list[Provider] = [Provider.semantic_scholar]
    directions: list[str] = ["backward", "forward"]
    max_results_per_seed: int = Field(default=100, ge=1, le=1000)
    depth: int = Field(default=1, ge=1, le=1)
    idempotency_key: str = Field(min_length=4, max_length=200)


class ManualImportRecord(BaseModel):
    provider_id: str | None = None
    title: str
    abstract: str | None = None
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    language: str | None = None
    authors: list[dict] = Field(default_factory=list)
    external_ids: dict = Field(default_factory=dict)
    document_type: str | None = None
    peer_reviewed: bool | None = None
    oa_locations: list[dict] = Field(default_factory=list)


class ManualImportRequest(BaseModel):
    source: str = Field(pattern=r"^(ieee|acm|scopus|web_of_science|proquest|manual)$")
    records: list[ManualImportRecord] = Field(min_length=1, max_length=5000)
    idempotency_key: str = Field(min_length=4, max_length=200)


class PdfAcquisitionRequest(BaseModel):
    max_articles: int = Field(default=5, ge=1, le=20)
    require_known_license: bool = True
    article_ids: list[str] | None = None


class FullTextCandidateRequest(BaseModel):
    source_url: str = Field(pattern=r"^https://")
    landing_page_url: str | None = None
    license: str | None = None
    version: str | None = None
    provider: str = "manual"


class DeduplicationDecision(BaseModel):
    decision: str = Field(pattern=r"^(same_work|version_of|keep_separate)$")
    decided_by: str = Field(min_length=2, max_length=200)


class ScieloHarvestRequest(BaseModel):
    collection: str = Field(default="scl", pattern=r"^[a-z]{3}$")
    from_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    until_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    max_records: int = Field(default=100, ge=1, le=5000)
    idempotency_key: str = Field(min_length=4, max_length=200)


class RepositorySourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    slug: str
    name: str
    domain: str
    acquisition_method: str
    base_url: str
    enabled: bool


class HarvestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_id: str
    idempotency_key: str
    status: str
    checkpoint: dict
    records_received: int
    records_created: int
    records_updated: int
    error: str | None

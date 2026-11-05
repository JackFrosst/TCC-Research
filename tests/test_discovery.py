import pytest
from sqlalchemy import func, select

from tcc_research_os.config import Settings
from tcc_research_os.connectors.base import SearchPage
from tcc_research_os.models import Article, ArticleSource, ProtocolStatus, SearchRun
from tcc_research_os.services.bootstrap import bootstrap_themes
from tcc_research_os.services.discovery import DiscoveryError, run_discovery
from tcc_research_os.services.normalization import normalize_crossref, normalize_openalex


class FakeConnector:
    def __init__(self, provider, records):
        self.provider = provider
        self.records = records

    def search(self, query, year_from, year_to, limit, cursor=None):
        return SearchPage(provider=self.provider, records=self.records[:limit])


class PagedConnector(FakeConnector):
    def search(self, query, year_from, year_to, limit, cursor=None):
        offset = int(cursor or 0)
        records = self.records[offset : offset + limit]
        next_cursor = (
            str(offset + len(records)) if offset + len(records) < len(self.records) else None
        )
        return SearchPage(self.provider, records, next_cursor)


CROSSREF_RECORD = {
    "DOI": "10.1234/cloud.1",
    "title": ["Hybrid Cloud Disaster Recovery"],
    "abstract": "<jats:p>Measured failover latency.</jats:p>",
    "published": {"date-parts": [[2024]]},
    "container-title": ["Journal of Cloud Systems"],
    "author": [{"given": "Ana", "family": "Silva"}],
}

OPENALEX_RECORD = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1234/CLOUD.1",
    "title": "Hybrid Cloud Disaster Recovery",
    "publication_year": 2024,
    "language": "en",
    "authorships": [{"author": {"display_name": "Ana Silva", "orcid": None}}],
    "primary_location": {"source": {"display_name": "Journal of Cloud Systems"}},
}


def _protocol(db):
    return bootstrap_themes(db)[0].protocols[0]


def _connectors():
    return {
        "crossref": (FakeConnector("crossref", [CROSSREF_RECORD]), normalize_crossref),
        "openalex": (FakeConnector("openalex", [OPENALEX_RECORD]), normalize_openalex),
    }


def test_search_requires_approved_protocol(db):
    protocol = _protocol(db)
    with pytest.raises(DiscoveryError, match="aprovação humana"):
        run_discovery(
            db,
            protocol.id,
            ["crossref"],
            10,
            "blocked-search",
            Settings(),
            _connectors(),
        )


def test_deduplicates_same_doi_and_preserves_two_sources(db):
    protocol = _protocol(db)
    protocol.status = ProtocolStatus.approved
    db.commit()

    run = run_discovery(
        db,
        protocol.id,
        ["crossref", "openalex"],
        10,
        "dedup-search",
        Settings(),
        _connectors(),
    )

    assert run.records_received == 2
    assert run.articles_created == 1
    assert db.scalar(select(func.count(Article.id))) == 1
    assert db.scalar(select(func.count(ArticleSource.id))) == 2


def test_idempotency_returns_existing_run_without_duplicates(db):
    protocol = _protocol(db)
    protocol.status = ProtocolStatus.approved
    db.commit()

    first = run_discovery(
        db,
        protocol.id,
        ["crossref"],
        10,
        "same-key",
        Settings(),
        _connectors(),
    )
    second = run_discovery(
        db,
        protocol.id,
        ["crossref"],
        10,
        "same-key",
        Settings(),
        _connectors(),
    )

    assert first.id == second.id
    assert db.scalar(select(func.count(SearchRun.id))) == 1
    assert db.scalar(select(func.count(Article.id))) == 1


def test_can_extend_completed_run_from_saved_cursor(db):
    protocol = _protocol(db)
    protocol.status = ProtocolStatus.approved
    protocol.queries = protocol.queries[:1]
    second_record = {**CROSSREF_RECORD, "DOI": "10.1234/cloud.2", "title": ["Cloud Failback"]}
    connectors = {
        "crossref": (
            PagedConnector("crossref", [CROSSREF_RECORD, second_record]),
            normalize_crossref,
        )
    }
    db.commit()

    first = run_discovery(db, protocol.id, ["crossref"], 1, "extend-search", Settings(), connectors)
    extended = run_discovery(
        db,
        protocol.id,
        ["crossref"],
        2,
        "extend-search",
        Settings(),
        connectors,
        extend_completed=True,
    )

    assert first.id == extended.id
    assert extended.records_received == 2
    assert db.scalar(select(func.count(Article.id))) == 2

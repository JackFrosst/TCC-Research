import httpx
import pytest
from sqlalchemy import func, select

from tcc_research_os.config import Settings
from tcc_research_os.connectors.base import SearchPage
from tcc_research_os.models import (
    Article,
    ArticleRelation,
    ProtocolStatus,
    SearchRunMetric,
    SourceRecord,
)
from tcc_research_os.services.bootstrap import bootstrap_themes
from tcc_research_os.services.discovery import (
    AcademicProviderError,
    run_discovery,
    run_manual_import,
    run_snowball,
)
from tcc_research_os.services.normalization import (
    normalize_crossref,
    normalize_semantic_scholar,
)


class PagedConnector:
    def search(self, query, year_from, year_to, limit, cursor=None):
        page = int(cursor or 0)
        record = {
            "DOI": f"10.1234/{abs(hash(query))}.{page}",
            "title": [f"{query} result {page}"],
            "published": {"date-parts": [[2024]]},
            "type": "journal-article",
        }
        return SearchPage("crossref", [record], "1" if page == 0 else None)


class SnowballConnector:
    def related(self, identifier, direction, limit, cursor=None):
        return SearchPage(
            "semantic_scholar",
            [
                {
                    "paperId": f"related-{direction}",
                    "title": f"Related {direction} work",
                    "year": 2023,
                    "authors": [{"name": "Researcher"}],
                }
            ],
        )


class InterruptingConnector:
    def search(self, query, year_from, year_to, limit, cursor=None):
        if cursor == "1":
            raise httpx.ConnectError("temporary outage")
        return SearchPage(
            "crossref",
            [
                {
                    "DOI": "10.1234/resume.0",
                    "title": ["Resume page zero"],
                    "published": {"date-parts": [[2024]]},
                }
            ],
            "1",
        )


class ResumingConnector:
    def search(self, query, year_from, year_to, limit, cursor=None):
        assert cursor == "1"
        return SearchPage(
            "crossref",
            [
                {
                    "DOI": "10.1234/resume.1",
                    "title": ["Resume page one"],
                    "published": {"date-parts": [[2024]]},
                }
            ],
        )


def test_paginates_each_query_and_records_metrics(db):
    protocol = bootstrap_themes(db)[0].protocols[0]
    protocol.status = ProtocolStatus.approved
    db.commit()

    run = run_discovery(
        db,
        protocol.id,
        ["crossref"],
        2,
        "paged-each-query",
        Settings(max_total_results_per_run=100),
        {"crossref": (PagedConnector(), normalize_crossref)},
    )

    assert run.records_received == len(protocol.queries) * 2
    metrics = list(
        db.scalars(select(SearchRunMetric).where(SearchRunMetric.search_run_id == run.id))
    )
    assert len(metrics) == len(protocol.queries)
    assert all(metric.pages_fetched == 2 for metric in metrics)


def test_resumes_failed_run_from_last_cursor(db):
    protocol = bootstrap_themes(db)[0].protocols[0]
    protocol.status = ProtocolStatus.approved
    db.commit()
    settings = Settings(max_total_results_per_run=2)

    with pytest.raises(AcademicProviderError):
        run_discovery(
            db,
            protocol.id,
            ["crossref"],
            2,
            "resume-same-key",
            settings,
            {"crossref": (InterruptingConnector(), normalize_crossref)},
            max_total_results=2,
        )

    run = run_discovery(
        db,
        protocol.id,
        ["crossref"],
        2,
        "resume-same-key",
        settings,
        {"crossref": (ResumingConnector(), normalize_crossref)},
        max_total_results=2,
        resume_failed=True,
    )

    assert run.records_received == 2
    assert run.articles_created == 2
    metric = db.scalar(select(SearchRunMetric).where(SearchRunMetric.search_run_id == run.id))
    assert metric.error is None


def test_manual_import_is_audited_and_deduplicated(db):
    project = bootstrap_themes(db)[0]
    project.protocols[0].status = ProtocolStatus.approved
    db.commit()

    run = run_manual_import(
        db,
        project.id,
        "ieee",
        [
            {
                "provider_id": "ieee-1",
                "title": "Resilient hybrid cloud",
                "doi": "10.1234/imported",
                "peer_reviewed": True,
            },
            {
                "provider_id": "ieee-2",
                "title": "Resilient hybrid cloud",
                "doi": "10.1234/imported",
                "peer_reviewed": True,
            },
        ],
        "manual-ieee-001",
    )

    assert run.records_received == 2
    assert run.articles_created == 1
    assert db.scalar(select(func.count(Article.id))) == 1


def test_snowball_records_seed_depth_and_relation(db):
    project = bootstrap_themes(db)[0]
    project.protocols[0].status = ProtocolStatus.approved
    seed = Article(
        project_id=project.id,
        code="A900000",
        title="Seed work",
        normalized_title="seed work",
        doi="10.1234/seed",
        authors=[],
    )
    db.add(seed)
    db.commit()

    run = run_snowball(
        db,
        project.id,
        [seed.id],
        ["semantic_scholar"],
        ["forward", "backward"],
        10,
        "snowball-001",
        Settings(),
        {
            "semantic_scholar": (
                SnowballConnector(),
                normalize_semantic_scholar,
            )
        },
    )

    records = list(db.scalars(select(SourceRecord).where(SourceRecord.search_run_id == run.id)))
    assert {record.discovery_method for record in records} == {
        "forward_citation",
        "backward_reference",
    }
    assert all(record.seed_article_id == seed.id and record.depth == 1 for record in records)
    assert db.scalar(select(func.count(ArticleRelation.id))) == 2

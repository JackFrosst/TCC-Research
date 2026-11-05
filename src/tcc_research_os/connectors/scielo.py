import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import HarvestedRecord, RepositorySource
from ..services.normalization import normalize_title
from .base import SearchPage
from .http import request_with_retry


def _boolean_groups(query: str) -> list[list[str]]:
    """Converte as consultas simples do protocolo em grupos AND de alternativas OR."""
    groups = re.split(r"\s+AND\s+", query, flags=re.IGNORECASE)
    parsed: list[list[str]] = []
    for group in groups:
        alternatives = re.split(r"\s+OR\s+", group.strip().strip("()"), flags=re.IGNORECASE)
        terms = [normalize_title(term.strip().strip('"').strip("()")) for term in alternatives]
        terms = [term for term in terms if term]
        if terms:
            parsed.append(terms)
    return parsed


def _boolean_match(query: str, text: str) -> tuple[bool, int]:
    haystack = normalize_title(text)
    groups = _boolean_groups(query)
    if not groups:
        return False, 0
    matched = [
        max((len(term.split()) for term in group if term in haystack), default=0)
        for group in groups
    ]
    return all(score > 0 for score in matched), sum(matched)


class ScieloLocalConnector:
    """Pesquisa somente o espelho local; nunca coleta durante uma busca."""

    def __init__(self, db: Session):
        self.db = db

    def search(self, query: str, year_from: int, year_to: int, limit: int, cursor=None):
        source = self.db.scalar(select(RepositorySource).where(RepositorySource.slug == "scielo"))
        if source is None:
            return SearchPage(provider="scielo", records=[])
        statement = select(HarvestedRecord).where(
            HarvestedRecord.source_id == source.id,
            HarvestedRecord.year.between(year_from, year_to),
        )
        candidates = list(self.db.scalars(statement.limit(5000)))
        scored = []
        for record in candidates:
            matched, score = _boolean_match(query, f"{record.title} {record.abstract or ''}")
            if matched:
                if any(
                    term in record.normalized_title
                    for group in _boolean_groups(query)
                    for term in group
                ):
                    score += 3
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], -(item[1].year or 0), item[1].title))
        offset = int(cursor or 0)
        page = scored[offset : offset + limit]
        records = [
            {
                "id": item.external_id,
                "title": item.title,
                "abstract": item.abstract,
                "year": item.year,
                "journal": item.journal,
                "doi": item.doi,
                "language": item.language,
                "authors": item.authors,
                "external_ids": item.external_ids,
                "document_type": item.document_type,
                "peer_reviewed": item.peer_reviewed,
                "oa_locations": item.oa_locations,
                "raw_payload": item.raw_payload,
            }
            for _, item in page
        ]
        next_cursor = str(offset + len(page)) if offset + len(page) < len(scored) else None
        return SearchPage("scielo", records, next_cursor, len(scored))


class ScieloCrossrefConnector:
    """Busca temática na Crossref limitada ao prefixo DOI usado pela rede SciELO."""

    base_url = "https://api.crossref.org/works"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.academic_api_user_agent},
        )

    def search(
        self, query: str, year_from: int, year_to: int, limit: int, cursor: str | None = None
    ) -> SearchPage:
        params = {
            "query.bibliographic": query,
            "filter": (
                f"prefix:10.1590,from-pub-date:{year_from}-01-01,until-pub-date:{year_to}-12-31"
            ),
            "rows": min(limit, 1000),
            "cursor": cursor or "*",
            "select": "DOI,title,author,published,issued,container-title,abstract,URL,type",
            "mailto": self.settings.academic_api_email,
        }
        response = request_with_retry(
            self.client, "GET", self.base_url, self.settings, params=params
        )
        response.raise_for_status()
        message = response.json()["message"]
        records = [
            item
            for item in message.get("items", [])
            if str(item.get("DOI") or "").lower().startswith("10.1590/")
        ]
        return SearchPage(
            provider="scielo_crossref",
            records=records,
            next_cursor=message.get("next-cursor"),
            total=None,
        )

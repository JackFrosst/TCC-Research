from urllib.parse import quote

import httpx

from ..config import Settings
from .base import SearchPage
from .http import request_with_retry


class SemanticScholarConnector:
    base_url = "https://api.semanticscholar.org/graph/v1"
    fields = (
        "paperId,externalIds,title,abstract,year,venue,authors,publicationTypes,"
        "publicationDate,openAccessPdf,isOpenAccess,url"
    )

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        headers = {"User-Agent": settings.academic_api_user_agent}
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds, headers=headers
        )

    def search(
        self, query: str, year_from: int, year_to: int, limit: int, cursor: str | None = None
    ) -> SearchPage:
        params = {
            "query": query,
            "year": f"{year_from}-{year_to}",
            "limit": min(limit, 100),
            "fields": self.fields,
        }
        if cursor:
            params["token"] = cursor
        response = request_with_retry(
            self.client,
            "GET",
            f"{self.base_url}/paper/search/bulk",
            self.settings,
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        return SearchPage(
            provider="semantic_scholar",
            records=payload.get("data", []),
            next_cursor=payload.get("token"),
            total=payload.get("total"),
        )

    def related(
        self, identifier: str, direction: str, limit: int, cursor: str | None = None
    ) -> SearchPage:
        endpoint = "citations" if direction == "forward" else "references"
        params = {"limit": min(limit, 1000), "fields": self.fields}
        if cursor:
            params["offset"] = int(cursor)
        response = request_with_retry(
            self.client,
            "GET",
            f"{self.base_url}/paper/{quote(identifier, safe=':')}/{endpoint}",
            self.settings,
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        key = "citingPaper" if direction == "forward" else "citedPaper"
        records = [item[key] for item in (payload.get("data") or []) if item.get(key)]
        next_offset = (int(cursor or 0) + len(records)) if payload.get("next") else None
        return SearchPage("semantic_scholar", records, str(next_offset) if next_offset else None)

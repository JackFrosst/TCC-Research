from urllib.parse import quote

import httpx

from ..config import Settings
from .base import SearchPage
from .http import request_with_retry


class CrossrefConnector:
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
            "filter": f"from-pub-date:{year_from}-01-01,until-pub-date:{year_to}-12-31",
            "rows": min(limit, 1000),
            "cursor": cursor or "*",
            "select": ("DOI,title,author,published,issued,container-title,abstract,URL,type"),
            "mailto": self.settings.academic_api_email,
        }
        response = request_with_retry(
            self.client, "GET", self.base_url, self.settings, params=params
        )
        response.raise_for_status()
        message = response.json()["message"]
        return SearchPage(
            provider="crossref",
            records=message.get("items", []),
            next_cursor=message.get("next-cursor"),
            total=message.get("total-results"),
        )


def crossref_preview_url(query: str, year_from: int, year_to: int) -> str:
    return (
        "https://api.crossref.org/works?query.bibliographic="
        f"{quote(query)}&filter=from-pub-date:{year_from}-01-01,"
        f"until-pub-date:{year_to}-12-31&rows=5"
    )

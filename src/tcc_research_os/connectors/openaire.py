import httpx

from ..config import Settings
from .base import SearchPage
from .http import request_with_retry


class OpenAireConnector:
    base_url = "https://api.openaire.eu/graph/v3/research-products"

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
            "search": query,
            "type": "publication",
            "fromPublicationYear": year_from,
            "toPublicationYear": year_to,
            "pageSize": min(limit, 100),
            "cursor": cursor or "*",
        }
        response = request_with_retry(
            self.client, "GET", self.base_url, self.settings, params=params
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("results") or payload.get("data") or []
        header = payload.get("header", {})
        return SearchPage(
            "openaire",
            records,
            payload.get("nextCursor") or header.get("nextCursor"),
            payload.get("total") or header.get("total"),
        )

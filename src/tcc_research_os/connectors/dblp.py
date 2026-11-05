import httpx

from ..config import Settings
from .base import SearchPage
from .http import request_with_retry


class DblpConnector:
    base_url = "https://dblp.org/search/publ/api"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={
                "User-Agent": settings.academic_api_user_agent,
                "Accept": "application/json",
            },
        )

    def search(
        self, query: str, year_from: int, year_to: int, limit: int, cursor: str | None = None
    ) -> SearchPage:
        offset = int(cursor or 0)
        params = {"q": query, "format": "json", "h": min(limit, 1000), "f": offset}
        response = request_with_retry(
            self.client, "GET", self.base_url, self.settings, params=params
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "desconhecido")
            raise httpx.RequestError(
                "DBLP não retornou JSON "
                f"(content-type: {content_type}); o serviço pode estar exibindo uma "
                "proteção anti-bot.",
                request=response.request,
            ) from exc
        result = payload.get("result", {})
        hits = result.get("hits", {})
        records = [item.get("info", {}) for item in hits.get("hit", [])]
        total = int(hits.get("@total", 0))
        next_offset = offset + len(records)
        return SearchPage("dblp", records, str(next_offset) if next_offset < total else None, total)

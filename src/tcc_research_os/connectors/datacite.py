import httpx

from ..config import Settings
from .base import SearchPage
from .http import request_with_retry


class DataCiteConnector:
    base_url = "https://api.datacite.org/dois"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.academic_api_user_agent},
        )

    def search(
        self, query: str, year_from: int, year_to: int, limit: int, cursor: str | None = None
    ) -> SearchPage:
        page = int(cursor or 1)
        size = min(limit, 1000)
        params = {
            "query": f"({query}) AND publicationYear:[{year_from} TO {year_to}]",
            "page[size]": size,
            "page[number]": page,
        }
        response = request_with_retry(
            self.client, "GET", self.base_url, self.settings, params=params
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("data", [])
        total = payload.get("meta", {}).get("total")
        has_next = bool(payload.get("links", {}).get("next")) and len(records) == size
        return SearchPage("datacite", records, str(page + 1) if has_next else None, total)

import xml.etree.ElementTree as ET

import httpx

from ..config import Settings
from .base import SearchPage
from .http import request_with_retry

ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
ARXIV = "{http://arxiv.org/schemas/atom}"


class ArxivConnector:
    base_url = "https://export.arxiv.org/api/query"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.academic_api_user_agent},
        )

    def search(
        self, query: str, year_from: int, year_to: int, limit: int, cursor: str | None = None
    ) -> SearchPage:
        offset = int(cursor or 0)
        date_filter = f"submittedDate:[{year_from}01010000 TO {year_to}12312359]"
        params = {
            "search_query": f"{query} AND {date_filter}",
            "start": offset,
            "max_results": min(limit, 100),
            "sortBy": "relevance",
        }
        response = request_with_retry(
            self.client, "GET", self.base_url, self.settings, params=params
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        total = int(root.findtext(f"{OPENSEARCH}totalResults", "0"))
        records = [_entry_to_dict(entry) for entry in root.findall(f"{ATOM}entry")]
        next_offset = offset + len(records)
        return SearchPage(
            "arxiv", records, str(next_offset) if next_offset < total else None, total
        )


def _entry_to_dict(entry: ET.Element) -> dict:
    links = {
        item.attrib.get("type", item.attrib.get("rel", "")): item.attrib.get("href")
        for item in entry.findall(f"{ATOM}link")
    }
    license_element = entry.find(f"{ARXIV}license")
    return {
        "id": entry.findtext(f"{ATOM}id"),
        "title": entry.findtext(f"{ATOM}title"),
        "summary": entry.findtext(f"{ATOM}summary"),
        "published": entry.findtext(f"{ATOM}published"),
        "updated": entry.findtext(f"{ATOM}updated"),
        "authors": [author.findtext(f"{ATOM}name") for author in entry.findall(f"{ATOM}author")],
        "doi": entry.findtext(f"{ARXIV}doi"),
        "journal_ref": entry.findtext(f"{ARXIV}journal_ref"),
        "pdf_url": links.get("application/pdf"),
        "landing_page_url": links.get("alternate"),
        "license": license_element.attrib.get("href") if license_element is not None else None,
    }

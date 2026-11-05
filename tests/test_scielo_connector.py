import httpx

from tcc_research_os.config import Settings
from tcc_research_os.connectors.scielo import (
    ScieloCrossrefConnector,
    _boolean_match,
)


def test_boolean_match_requires_every_and_group():
    query = '(multicloud OR "multi-cloud") AND (redundancy OR resilience) AND interoperability'
    assert _boolean_match(query, "Multi-cloud resilience and interoperability")[0]
    assert not _boolean_match(query, "Resilience of agricultural communities")[0]


def test_scielo_crossref_applies_scielo_prefix_and_dates():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "prefix%3A10.1590" in str(request.url)
        assert "from-pub-date%3A2020-01-01" in str(request.url)
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {"DOI": "10.1590/example", "title": ["Paper"]},
                        {"DOI": "10.1016/not-scielo", "title": ["Other"]},
                    ]
                }
            },
        )

    connector = ScieloCrossrefConnector(
        Settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    page = connector.search("multi-cloud", 2020, 2026, 10)
    assert page.provider == "scielo_crossref"
    assert page.records[0]["DOI"] == "10.1590/example"
    assert len(page.records) == 1

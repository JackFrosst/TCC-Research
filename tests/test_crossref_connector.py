import httpx

from tcc_research_os.config import Settings
from tcc_research_os.connectors.crossref import CrossrefConnector


def test_crossref_select_uses_only_supported_fields():
    captured_url = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url
        captured_url = str(request.url)
        return httpx.Response(
            200,
            json={"message": {"items": [], "next-cursor": None}},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = CrossrefConnector(Settings(), client=client)
    connector.search("immutable backup", 2015, 2026, 10)

    assert captured_url is not None
    decoded_url = httpx.URL(captured_url)
    selected = decoded_url.params["select"].split(",")
    assert "language" not in selected
    assert {"DOI", "title", "abstract", "type"}.issubset(selected)

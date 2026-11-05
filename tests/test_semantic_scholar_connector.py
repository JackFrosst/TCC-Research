import httpx

from tcc_research_os.config import Settings
from tcc_research_os.connectors.semantic_scholar import SemanticScholarConnector


def test_related_treats_null_data_as_empty_page():
    def handler(request):
        return httpx.Response(200, json={"data": None, "next": None}, request=request)

    connector = SemanticScholarConnector(
        Settings(), httpx.Client(transport=httpx.MockTransport(handler))
    )
    page = connector.related("DOI:10.0000/example", "forward", 100)

    assert page.records == []
    assert page.next_cursor is None

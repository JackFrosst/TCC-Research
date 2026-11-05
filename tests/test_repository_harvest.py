import json

import httpx
from sqlalchemy import func, select

from tcc_research_os.config import Settings
from tcc_research_os.connectors.scielo import ScieloLocalConnector
from tcc_research_os.harvesters.parsers import parse_oai_dc, parse_sitemap, parse_structured_html
from tcc_research_os.models import HarvestedRecord
from tcc_research_os.services.repository_harvest import harvest_scielo


def _article():
    return {
        "code": "S00000000000000001",
        "doi": "10.1590/example",
        "publication_year": "2024",
        "document_type": "research-article",
        "article": {
            "code": "S00000000000000001",
            "v12": [{"l": "pt", "_": "Backup imutável contra ransomware"}],
            "v83": [{"l": "pt", "a": "Análise de WORM e Object Lock."}],
            "v40": [{"_": "pt"}],
            "v100": [{"_": "Revista de Teste"}],
            "v10": [{"n": "Ana", "s": "Silva"}],
        },
        "fulltexts": {"html": {"pt": "http://www.scielo.br/example"}},
    }


def test_scielo_harvest_is_idempotent_and_searches_local_index(db):
    def handler(request):
        if request.url.path.endswith("identifiers/"):
            payload = {"objects": [{"code": "S00000000000000001", "collection": "scl"}]}
        else:
            payload = _article()
        return httpx.Response(200, content=json.dumps(payload).encode(), request=request)

    settings = Settings(repository_harvest_max_records=10)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    run = harvest_scielo(
        db, settings, "scl", "2024-01-01", "2024-01-02", 5, "scielo-test-001", client
    )
    repeated = harvest_scielo(
        db, settings, "scl", "2024-01-01", "2024-01-02", 5, "scielo-test-001", client
    )
    assert run.id == repeated.id
    assert db.scalar(select(func.count(HarvestedRecord.id))) == 1
    page = ScieloLocalConnector(db).search("immutable backup OR ransomware", 2020, 2026, 10)
    assert page.total == 1
    assert page.records[0]["doi"] == "10.1590/example"


def test_repository_parsers_extract_only_metadata():
    oai = """<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
      <ListRecords><record><header><identifier>x:1</identifier></header><metadata>
      <dc xmlns="http://purl.org/dc/elements/1.1/"><title>Artigo</title></dc>
      </metadata></record><resumptionToken>next</resumptionToken></ListRecords></OAI-PMH>"""
    records, token = parse_oai_dc(oai)
    assert records[0]["title"] == ["Artigo"]
    assert token == "next"
    sitemap = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.org/a</loc><lastmod>2024-01-01</lastmod></url></urlset>"""
    assert parse_sitemap(sitemap)[0]["url"] == "https://example.org/a"
    html = (
        '<meta name="citation_title" content="Artigo">'
        '<script type="application/ld+json">{"@type":"ScholarlyArticle"}</script>'
    )
    parsed = parse_structured_html(html)
    assert parsed["meta"]["citation_title"] == ["Artigo"]
    assert parsed["json_ld"][0]["@type"] == "ScholarlyArticle"

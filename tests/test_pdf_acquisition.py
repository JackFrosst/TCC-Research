from io import BytesIO

import httpx
from pypdf import PdfWriter
from sqlalchemy import func, select

from tcc_research_os.config import Settings
from tcc_research_os.connectors.unpaywall import OpenAccessLocation
from tcc_research_os.models import Article, FullTextAsset, FullTextCandidate
from tcc_research_os.services.bootstrap import bootstrap_themes
from tcc_research_os.services.normalization import normalize_title
from tcc_research_os.services.pdf_acquisition import acquire_pdfs, preview_acquisition
from tcc_research_os.services.pdf_downloader import SafePdfDownloader


class FakeUnpaywall:
    def find_pdf(self, doi):
        return OpenAccessLocation(
            pdf_url="https://repository.example.org/paper.pdf",
            landing_page_url="https://repository.example.org/paper",
            license="cc-by",
            version="publishedVersion",
            host_type="repository",
            raw_payload={"is_oa": True},
        )


class FailingLookup:
    def find_pdf(self, doi):
        raise AssertionError("external lookup should not run for a licensed stored candidate")


def _seed_article(db):
    project = bootstrap_themes(db)[0]
    article = Article(
        project_id=project.id,
        code="A999999",
        title="Test paper",
        normalized_title=normalize_title("Test paper"),
        doi="10.1234/test",
        authors=[],
    )
    db.add(article)
    db.commit()
    return project, article


def test_preview_uses_embedded_open_access_location_without_doi(db, tmp_path):
    project = bootstrap_themes(db)[0]
    article = Article(
        project_id=project.id,
        code="A888888",
        title="Repository paper",
        normalized_title=normalize_title("Repository paper"),
        authors=[],
        oa_locations=[
            {
                "provider": "openaire",
                "pdf_url": "https://repository.example.org/open.pdf",
                "license": "cc-by",
            }
        ],
    )
    db.add(article)
    db.commit()

    preview = preview_acquisition(
        db,
        project.id,
        5,
        True,
        Settings(pdf_storage_root=str(tmp_path), unpaywall_email=None),
    )

    assert preview["counts"]["eligible_for_download"] == 1
    assert preview["items"][0]["status"] == "ELIGIBLE"


def _downloader(settings):
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.write(output)
    pdf = output.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=pdf,
            headers={"content-type": "application/pdf"},
            request=request,
        )

    return SafePdfDownloader(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        url_validator=lambda _: None,
    )


def test_preview_persists_candidate_without_downloading(db, tmp_path):
    project, article = _seed_article(db)
    settings = Settings(pdf_storage_root=str(tmp_path), unpaywall_email="research@uni.edu")

    preview = preview_acquisition(db, project.id, 5, True, settings, connector=FakeUnpaywall())

    assert preview["counts"]["eligible_for_download"] == 1
    assert db.scalar(select(func.count(FullTextCandidate.id))) == 1
    assert db.scalar(select(func.count(FullTextAsset.id))) == 0
    assert not list(tmp_path.rglob("*.pdf"))
    assert preview["items"][0]["article_id"] == article.id


def test_preview_uses_manually_registered_candidate(db, tmp_path):
    project, article = _seed_article(db)
    candidate = FullTextCandidate(
        article_id=article.id,
        provider="publisher",
        source_url="https://publisher.example.org/paper.pdf",
        landing_page_url="https://publisher.example.org/paper",
        license="cc-by-4.0",
        version="publishedVersion",
        host_type="manual",
        status="AVAILABLE",
        raw_payload={"registered_manually": True},
    )
    db.add(candidate)
    db.commit()

    preview = preview_acquisition(
        db,
        project.id,
        5,
        True,
        Settings(pdf_storage_root=str(tmp_path), unpaywall_email="research@uni.edu"),
        connector=FailingLookup(),
    )

    assert preview["counts"]["eligible_for_download"] == 1
    assert preview["items"][0]["candidate_id"] == candidate.id
    assert preview["items"][0]["status"] == "ELIGIBLE"


def test_acquisition_downloads_valid_pdf_and_writes_manifest(db, tmp_path):
    project, _ = _seed_article(db)
    settings = Settings(
        pdf_storage_root=str(tmp_path),
        unpaywall_email="research@uni.edu",
        allow_pdf_downloads=True,
    )

    result = acquire_pdfs(
        db,
        project.id,
        5,
        True,
        settings,
        connector=FakeUnpaywall(),
        downloader=_downloader(settings),
    )

    assert result["completed"] == 1
    assert db.scalar(select(func.count(FullTextAsset.id))) == 1
    assert len(list(tmp_path.rglob("*.pdf"))) == 1
    assert (tmp_path / project.slug / "manifest.json").exists()

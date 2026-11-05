from tcc_research_os.models import Article
from tcc_research_os.services.reranking import _clean_document


def article(*, title: str = "Multi-cloud recovery", abstract: str | None = None) -> Article:
    return Article(
        project_id="project",
        code="A1",
        title=title,
        normalized_title=title.lower(),
        abstract=abstract,
        authors=[],
        external_ids={},
        oa_locations=[],
    )


def test_clean_document_keeps_normal_abstract():
    document, quality = _clean_document(
        article(abstract="A technical evaluation of failover across AWS and Azure.")
    )

    assert quality == "TITLE_ABSTRACT"
    assert "AWS and Azure" in document


def test_clean_document_rejects_prompt_contamination():
    document, quality = _clean_document(
        article(abstract="The user wants me to rewrite a long unrelated manuscript.")
    )

    assert quality == "ABSTRACT_REJECTED"
    assert "user wants" not in document


def test_clean_document_rejects_index_page_as_title():
    document, quality = _clean_document(article(title="issue contents " * 200))

    assert quality == "MALFORMED_TITLE"
    assert len(document) == 1000

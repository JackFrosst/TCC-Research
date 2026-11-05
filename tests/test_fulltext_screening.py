from pathlib import Path

from pypdf import PdfWriter

from tcc_research_os.services.fulltext_screening import (
    _reduce_maps,
    extract_pdf_chunks,
    select_relevant_chunks,
)


def test_extract_pdf_rejects_pdf_without_extractable_text(tmp_path: Path):
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with path.open("wb") as handle:
        writer.write(handle)
    try:
        extract_pdf_chunks(path)
    except Exception as exc:
        assert "OCR" in str(exc)
    else:
        raise AssertionError("PDF sem texto deveria exigir OCR")


def test_reduce_maps_includes_only_with_all_inclusion_criteria():
    findings = [
        {
            "criterion": code,
            "assessment": "SUPPORTS",
            "page": number,
            "quote": f"evidence {code}",
        }
        for number, code in enumerate(("IC01", "IC02", "IC03"), start=1)
    ]
    result = _reduce_maps([{"findings": findings, "uncertainties": []}])
    assert result["decision"] == "INCLUDE"
    assert result["exclusion_code"] == "NONE"


def test_reduce_maps_excludes_on_explicit_exclusion_evidence():
    result = _reduce_maps(
        [
            {
                "findings": [
                    {
                        "criterion": "EC01",
                        "assessment": "SUPPORTS",
                        "page": 2,
                        "quote": "outside scope",
                    }
                ],
                "uncertainties": [],
            }
        ]
    )
    assert result["decision"] == "EXCLUDE"
    assert result["exclusion_code"] == "EC01"


def test_select_relevant_chunks_keeps_boundaries_and_domain_evidence():
    chunks = [
        "front matter",
        *[f"generic section {index}" for index in range(10)],
        "AWS multi-cloud disaster recovery failover",
        "references",
    ]
    selected = select_relevant_chunks(chunks, max_chunks=4)
    assert chunks[0] in selected
    assert chunks[-1] in selected
    assert "AWS multi-cloud disaster recovery failover" in selected

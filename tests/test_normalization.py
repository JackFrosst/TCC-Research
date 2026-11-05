from tcc_research_os.services.normalization import normalize_doi, normalize_title


def test_normalize_doi_variants():
    expected = "10.1000/xyz"
    assert normalize_doi("HTTPS://DOI.ORG/10.1000/XYZ") == expected
    assert normalize_doi("doi:10.1000/XYZ.") == expected
    assert normalize_doi(" 10.1000/XYZ ") == expected


def test_invalid_doi_returns_none():
    assert normalize_doi(None) is None
    assert normalize_doi("not-a-doi") is None


def test_normalize_title_removes_accents_and_punctuation():
    assert normalize_title("Resiliência: Nuvem Híbrida!") == "resiliencia nuvem hibrida"

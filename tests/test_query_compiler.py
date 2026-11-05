from tcc_research_os.services.query_compiler import compile_query


def test_compiles_representative_terms_for_plain_text_providers():
    query = '("immutable backup" OR "immutable storage" OR WORM) AND (ransomware OR resilience)'

    assert compile_query("semantic_scholar", query) == "immutable backup ransomware"
    assert compile_query("dblp", query) == "immutable backup ransomware"


def test_preserves_boolean_query_for_capable_provider():
    query = '("immutable backup" OR WORM) AND ransomware'

    assert compile_query("crossref", query) == query


def test_limits_openaire_query_to_four_logical_operators():
    query = (
        '("hybrid cloud" OR "hybrid infrastructure") '
        'AND (failover OR failback OR "disaster recovery") '
        'AND ("data replication" OR "continuous replication" OR synchronization)'
    )

    compiled = compile_query("openaire", query)

    assert len(__import__("re").findall(r"\b(?:AND|OR|NOT)\b", compiled)) <= 4
    assert "hybrid cloud" in compiled
    assert "failover" in compiled
    assert "data replication" in compiled

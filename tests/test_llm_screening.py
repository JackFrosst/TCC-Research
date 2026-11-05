from tcc_research_os.services.llm_screening import _fallback_decision


def test_fallback_decision_is_auditable_and_conservative():
    result = _fallback_decision(RuntimeError("servidor indisponivel"))

    assert result["decision"] == "UNCERTAIN"
    assert result["confidence"] == 0.0
    assert result["requires_human_review"] is True
    assert result["exclusion_code"] == "NONE"
    assert result["criteria"]["IC01"] == "UNKNOWN"
    assert "servidor indisponivel" in result["uncertainties"][0]

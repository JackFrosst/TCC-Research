from tcc_research_os.agents.contracts import ENABLED_AGENT_ROLES, PROHIBITED_CAPABILITIES


def test_no_writer_agent_or_writing_capability_is_enabled():
    assert "writer" not in ENABLED_AGENT_ROLES
    assert "write_tcc" in PROHIBITED_CAPABILITIES
    assert "write_chapter" in PROHIBITED_CAPABILITIES

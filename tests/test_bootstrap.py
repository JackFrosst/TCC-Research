from sqlalchemy import func, select

from tcc_research_os.models import Project, ReviewProtocol, SearchQuery
from tcc_research_os.services.bootstrap import bootstrap_themes, load_theme_definitions


def test_bootstrap_creates_four_idempotent_themes(db):
    bootstrap_themes(db)
    bootstrap_themes(db)

    assert db.scalar(select(func.count(Project.id))) == 4
    assert db.scalar(select(func.count(ReviewProtocol.id))) == 4
    expected_queries = sum(len(theme["queries"]) for theme in load_theme_definitions())
    assert db.scalar(select(func.count(SearchQuery.id))) == expected_queries

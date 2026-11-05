import json
from importlib.resources import files

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, ReviewProtocol, SearchQuery, WorkflowEvent


def load_theme_definitions() -> list[dict]:
    resource = files("tcc_research_os").joinpath("data/themes.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def bootstrap_themes(db: Session, actor: str = "bootstrap") -> list[Project]:
    projects: list[Project] = []
    for definition in load_theme_definitions():
        project = db.scalar(select(Project).where(Project.slug == definition["slug"]))
        if project is None:
            project = Project(
                slug=definition["slug"],
                title=definition["title"],
                technical_focus=definition["technical_focus"],
            )
            db.add(project)
            db.flush()
            protocol = ReviewProtocol(
                project_id=project.id,
                research_question=definition["research_question"],
                year_from=definition["year_from"],
                year_to=definition["year_to"],
                languages=definition["languages"],
                inclusion_criteria=definition["inclusion_criteria"],
                exclusion_criteria=definition["exclusion_criteria"],
            )
            db.add(protocol)
            db.flush()
            for query in definition["queries"]:
                db.add(
                    SearchQuery(
                        protocol_id=protocol.id,
                        code=query["code"],
                        query_text=query["query"],
                        purpose=query["purpose"],
                        language=query["language"],
                    )
                )
            db.add(
                WorkflowEvent(
                    project_id=project.id,
                    event_type="THEME_BOOTSTRAPPED",
                    actor=actor,
                    payload={"protocol_id": protocol.id, "version": protocol.version},
                )
            )
        projects.append(project)
    db.commit()
    return projects

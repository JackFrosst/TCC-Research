from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import Project, ReviewProtocol, SearchQuery, WorkflowEvent


class ProjectSetupError(RuntimeError):
    pass


def create_project_with_protocol(db: Session, definition: dict) -> tuple[Project, ReviewProtocol]:
    slug = definition["slug"]
    if db.scalar(select(Project).where(Project.slug == slug)) is not None:
        raise ProjectSetupError(f"Já existe um projeto com o slug '{slug}'")

    project = Project(
        slug=slug,
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
                code=query["code"].upper(),
                query_text=query["query"],
                purpose=query["purpose"],
                language=query["language"],
            )
        )

    db.add(
        WorkflowEvent(
            project_id=project.id,
            event_type="PROJECT_CREATED",
            actor=definition["created_by"],
            payload={"protocol_id": protocol.id, "version": protocol.version},
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = "Não foi possível criar o projeto; verifique valores únicos"
        raise ProjectSetupError(message) from exc

    saved_protocol = db.scalar(
        select(ReviewProtocol)
        .where(ReviewProtocol.id == protocol.id)
        .options(selectinload(ReviewProtocol.queries))
    )
    if saved_protocol is None:
        raise ProjectSetupError("O protocolo criado não pôde ser recarregado")
    db.refresh(project)
    return project, saved_protocol

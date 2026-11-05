from fastapi.testclient import TestClient

from tcc_research_os.database import get_db
from tcc_research_os.main import app


def _payload() -> dict:
    return {
        "slug": "observabilidade-sistemas-distribuidos",
        "title": "Observabilidade em sistemas distribuídos",
        "technical_focus": "Métricas, logs e rastreamento distribuído em serviços críticos.",
        "research_question": (
            "Como a observabilidade afeta a confiabilidade de sistemas distribuídos?"
        ),
        "year_from": 2018,
        "year_to": 2026,
        "languages": ["pt", "en"],
        "inclusion_criteria": [
            {"code": "IC01", "text": "Estudo técnico sobre sistemas distribuídos."}
        ],
        "exclusion_criteria": [
            {"code": "EC01", "text": "Material comercial sem avaliação técnica."}
        ],
        "queries": [
            {
                "code": "Q001",
                "language": "en",
                "purpose": "Busca principal",
                "query": '(observability OR telemetry) AND "distributed systems"',
            }
        ],
        "created_by": "teste",
    }


def test_create_custom_project_with_draft_protocol(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post("/v1/projects", json=_payload())
        assert response.status_code == 201
        body = response.json()
        assert body["project"]["slug"] == "observabilidade-sistemas-distribuidos"
        assert body["protocol"]["status"] == "DRAFT"
        assert body["protocol"]["queries"][0]["code"] == "Q001"

        duplicate = client.post("/v1/projects", json=_payload())
        assert duplicate.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_project_rejects_reversed_year_range(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        payload = _payload()
        payload["year_from"] = 2026
        payload["year_to"] = 2020
        response = TestClient(app).post("/v1/projects", json=payload)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()

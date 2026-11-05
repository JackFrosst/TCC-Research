from fastapi.testclient import TestClient

from tcc_research_os.database import get_db
from tcc_research_os.main import app


def test_root_redirects_to_api_documentation():
    client = TestClient(app, follow_redirects=False)

    response = client.get("/")

    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_api_bootstrap_and_scope_capabilities(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/v1/capabilities")
        assert response.status_code == 200
        assert response.json()["writing_enabled"] is False

        response = client.post("/v1/bootstrap/themes")
        assert response.status_code == 200
        assert len(response.json()) == 4

        response = client.get("/v1/projects")
        assert response.status_code == 200
        assert len(response.json()) == 4
    finally:
        app.dependency_overrides.clear()

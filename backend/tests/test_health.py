from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from esp.api.main import app
from esp.db import get_session


def test_health_reports_database_postgis_and_schema_revision(database_url: str) -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["postgis_version"].startswith("3.")
    assert body["schema_revision"] == "0001"


def test_health_is_degraded_when_database_is_unreachable() -> None:
    dead = create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")

    def unreachable_session():  # type: ignore[no-untyped-def]
        with Session(dead) as session:
            yield session

    app.dependency_overrides[get_session] = unreachable_session
    try:
        response = TestClient(app).get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"

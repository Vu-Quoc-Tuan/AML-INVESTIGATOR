"""FastAPI runtime contract tests."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_is_available() -> None:
    response = TestClient(create_app(cors_origins="")).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_configured_origin_is_allowed_by_cors() -> None:
    client = TestClient(create_app(cors_origins="https://aml.example, http://localhost:3000"))

    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unconfigured_origin_is_not_allowed_by_cors() -> None:
    client = TestClient(create_app(cors_origins="https://aml.example"))

    response = client.options(
        "/health",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers

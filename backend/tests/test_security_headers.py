"""Unit tests for the security response-header middleware (app.main.add_security_headers).

Hits /health (no DB dependency, lifespan not triggered without `with TestClient`)
to assert the headers land on every response, and that HSTS is gated to production.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.constants import (
    APP_ENV_DEVELOPMENT,
    HSTS_HEADER_NAME,
    HSTS_HEADER_VALUE,
    SECURITY_HEADERS,
)
from app.main import app

client = TestClient(app)


def test_security_headers_present_on_every_response():
    resp = client.get("/health")
    assert resp.status_code == 200
    for name, value in SECURITY_HEADERS.items():
        assert resp.headers[name] == value


def test_hsts_absent_in_development():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        resp = client.get("/health")

    assert HSTS_HEADER_NAME not in resp.headers


def test_hsts_present_in_production():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = "production"
        resp = client.get("/health")

    assert resp.headers[HSTS_HEADER_NAME] == HSTS_HEADER_VALUE

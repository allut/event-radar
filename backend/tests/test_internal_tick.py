"""Regression test for GET /internal/tick (app/main.py::tick).

Starlette decodes headers as latin-1, so any header byte >= 0x80 produces a
non-ASCII str; CPython's secrets.compare_digest raises TypeError on non-ASCII
str operands. Before the fix, an invalid X-Internal-Token containing such a
byte crashed with an unhandled 500 instead of the intended 403 — on an
unauthenticated, rate-limited-but-otherwise-open endpoint.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.constants import APP_ENV_DEVELOPMENT
from app.main import app

client = TestClient(app)


def test_non_ascii_token_returns_403_not_500():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = "production"
        mock_settings.ALLOW_INSECURE_DEV = False
        mock_settings.INTERNAL_TOKEN = "correct-token"
        resp = client.get(
            "/internal/tick",
            # httpx's Headers rejects a non-ASCII str value client-side (encodes
            # as ascii); pass the raw latin-1 byte directly to reach the server
            # unchanged, reproducing what Starlette's own latin-1 header decode
            # would hand the handler.
            headers={"X-Internal-Token": "wrong\xff".encode("latin-1")},
        )
    assert resp.status_code == 403


def test_valid_token_returns_ok():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = "production"
        mock_settings.ALLOW_INSECURE_DEV = False
        mock_settings.INTERNAL_TOKEN = "correct-token"
        resp = client.get(
            "/internal/tick",
            headers={"X-Internal-Token": "correct-token"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_unset_token_dev_fail_open_returns_ok():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_settings.ALLOW_INSECURE_DEV = True
        mock_settings.INTERNAL_TOKEN = ""
        resp = client.get("/internal/tick")
    assert resp.status_code == 200

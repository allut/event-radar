"""Unit tests for POST /webhooks/inbound-mail.

Tests the webhook endpoint in isolation — DB and background task are mocked.
"""
import http
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from app.constants import APP_ENV_DEVELOPMENT
from httpx import ASGITransport, AsyncClient


def _build_app(resend_secret: str = "") -> FastAPI:
    """Create a minimal FastAPI app with the webhooks router and patched settings."""
    from app.routers.webhooks import router

    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _email_payload(
    *,
    from_addr: str = "newsletter@example.com",
    to: object = "inbound@eventradar.ee",
    subject: str = "Upcoming events",
    text: str = "Jazz Night on Friday at Telliskivi.",
) -> dict:
    return {"from": from_addr, "to": to, "subject": subject, "text": text}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_mail_accepted_with_valid_body(mock_db):
    email_obj = MagicMock()
    email_obj.id = 1
    mock_db.flush.side_effect = lambda: setattr(email_obj, "id", 7)

    app = _build_app()

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings, \
         patch("app.routers.webhooks.RawInboundEmail", return_value=email_obj), \
         patch("app.routers.webhooks._run_extraction"):
        mock_settings.RESEND_WEBHOOK_SECRET = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail",
                json=_email_payload(),
            )

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["status"] == "accepted"
    assert "id" in body


@pytest.mark.asyncio
async def test_inbound_mail_fails_closed_in_production_when_secret_unset(mock_db):
    """Empty RESEND_WEBHOOK_SECRET in a non-development APP_ENV must refuse with 503
    (mirrors routers/admin.py::_require_admin) instead of accepting unauthenticated POSTs."""
    app = _build_app()

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = ""
        mock_settings.APP_ENV = "production"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail",
                json=_email_payload(),
            )

    assert resp.status_code == http.HTTPStatus.SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_inbound_mail_rejects_wrong_secret(mock_db):
    app = _build_app()

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = "correct-secret"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail?secret=wrong",
                json=_email_payload(),
            )

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_inbound_mail_accepts_correct_secret(mock_db):
    email_obj = MagicMock()
    email_obj.id = 1
    mock_db.flush.side_effect = lambda: setattr(email_obj, "id", 3)

    app = _build_app()

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings, \
         patch("app.routers.webhooks.RawInboundEmail", return_value=email_obj), \
         patch("app.routers.webhooks._run_extraction"):
        mock_settings.RESEND_WEBHOOK_SECRET = "my-secret"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail?secret=my-secret",
                json=_email_payload(),
            )

    assert resp.status_code == http.HTTPStatus.OK


@pytest.mark.asyncio
async def test_inbound_mail_rejects_non_json_body(mock_db):
    app = _build_app()

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail",
                content=b"this is not json",
                headers={"Content-Type": "application/json"},
            )

    assert resp.status_code == http.HTTPStatus.BAD_REQUEST
    assert resp.json()["reason"] == "invalid json"


@pytest.mark.asyncio
async def test_inbound_mail_to_field_as_list_is_joined(mock_db):
    """'to' field sent as a JSON array must be stored as a comma-joined string."""
    email_obj = MagicMock()
    email_obj.id = 1
    mock_db.flush.side_effect = lambda: setattr(email_obj, "id", 5)

    captured: dict = {}

    def capture_email(**kwargs):
        captured.update(kwargs)
        return email_obj

    app = _build_app()

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings, \
         patch("app.routers.webhooks.RawInboundEmail", side_effect=capture_email), \
         patch("app.routers.webhooks._run_extraction"):
        mock_settings.RESEND_WEBHOOK_SECRET = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        payload = _email_payload(to=["a@example.com", "b@example.com"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/webhooks/inbound-mail", json=payload)

    assert resp.status_code == http.HTTPStatus.OK
    assert captured.get("to_addr") == "a@example.com, b@example.com"


@pytest.mark.asyncio
async def test_inbound_mail_no_text_and_no_subject_skips_extraction(mock_db):
    """Empty text body + empty subject — email is stored but extraction is skipped."""
    from starlette.requests import Request
    from fastapi import BackgroundTasks
    from app.routers.webhooks import inbound_mail

    email_obj = MagicMock()
    email_obj.id = 1
    mock_db.flush.side_effect = lambda: setattr(email_obj, "id", 9)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhooks/inbound-mail",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }
    body = json.dumps({"from": "x@x.com", "to": "", "subject": "", "text": ""}).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(scope, receive)
    bg = BackgroundTasks()

    with patch("app.routers.webhooks.settings") as s, \
         patch("app.routers.webhooks.RawInboundEmail", return_value=email_obj):
        s.RESEND_WEBHOOK_SECRET = ""
        s.APP_ENV = APP_ENV_DEVELOPMENT
        result = await inbound_mail(
            request=request,
            background_tasks=bg,
            secret="",
            db=mock_db,
        )

    assert result.status_code == http.HTTPStatus.OK
    assert len(bg.tasks) == 0  # no extraction task added


@pytest.mark.asyncio
async def test_inbound_mail_with_text_body_queues_extraction(mock_db):
    """Non-empty text body causes an extraction background task to be queued."""
    email_obj = MagicMock()
    email_obj.id = 1
    mock_db.flush.side_effect = lambda: setattr(email_obj, "id", 11)

    import json as _json
    from starlette.requests import Request
    from fastapi import BackgroundTasks
    from app.routers.webhooks import inbound_mail

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhooks/inbound-mail",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }
    body = _json.dumps(_email_payload()).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(scope, receive)
    bg = BackgroundTasks()

    with patch("app.routers.webhooks.settings") as s, \
         patch("app.routers.webhooks.RawInboundEmail", return_value=email_obj):
        s.RESEND_WEBHOOK_SECRET = ""
        s.APP_ENV = APP_ENV_DEVELOPMENT
        result = await inbound_mail(
            request=request,
            background_tasks=bg,
            secret="",
            db=mock_db,
        )

    assert result.status_code == http.HTTPStatus.OK
    assert len(bg.tasks) == 1

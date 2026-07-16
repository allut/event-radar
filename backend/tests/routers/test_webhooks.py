"""Unit tests for POST /webhooks/inbound-mail.

Tests the webhook endpoint in isolation — DB and background task are mocked.
"""
import base64
import hashlib
import hmac
import http
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from app.constants import (
    APP_ENV_DEVELOPMENT,
    SVIX_ID_HEADER,
    SVIX_SIGNATURE_HEADER,
    SVIX_TIMESTAMP_HEADER,
)
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "whsec_" + base64.b64encode(b"0" * 24).decode()


def _build_app() -> FastAPI:
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


def _svix_headers(
    body: bytes, *, secret: str = TEST_SECRET, svix_id: str = "msg_test", timestamp: str | None = None
) -> dict:
    """Build valid svix-id/svix-timestamp/svix-signature headers for body."""
    ts = timestamp or str(int(time.time()))
    key = base64.b64decode(secret[len("whsec_") :])
    signed_content = f"{svix_id}.{ts}.".encode() + body
    sig = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()
    return {
        SVIX_ID_HEADER: svix_id,
        SVIX_TIMESTAMP_HEADER: ts,
        SVIX_SIGNATURE_HEADER: f"v1,{sig}",
    }


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
async def test_inbound_mail_rejects_missing_signature_headers(mock_db):
    app = _build_app()

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = TEST_SECRET

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail",
                json=_email_payload(),
            )

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_inbound_mail_rejects_tampered_body(mock_db):
    """A body modified after signing must fail signature verification."""
    app = _build_app()
    payload = _email_payload()
    signed_body = json.dumps(payload).encode()
    headers = _svix_headers(signed_body)

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    tampered_payload = {**payload, "from": "attacker@evil.com"}

    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = TEST_SECRET

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail",
                content=json.dumps(tampered_payload).encode(),
                headers={**headers, "Content-Type": "application/json"},
            )

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_inbound_mail_rejects_stale_timestamp(mock_db):
    """A svix-timestamp far outside tolerance must be rejected (anti-replay)."""
    app = _build_app()
    payload = _email_payload()
    body = json.dumps(payload).encode()
    stale_ts = str(int(time.time()) - 3600)  # 1 hour old, well past tolerance
    headers = _svix_headers(body, timestamp=stale_ts)

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = TEST_SECRET

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail",
                content=body,
                headers={**headers, "Content-Type": "application/json"},
            )

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_inbound_mail_rejects_wrong_secret(mock_db):
    """A signature computed with a different secret must be rejected."""
    app = _build_app()
    payload = _email_payload()
    body = json.dumps(payload).encode()
    wrong_secret = "whsec_" + base64.b64encode(b"1" * 24).decode()
    headers = _svix_headers(body, secret=wrong_secret)

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.RESEND_WEBHOOK_SECRET = TEST_SECRET

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail",
                content=body,
                headers={**headers, "Content-Type": "application/json"},
            )

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_inbound_mail_accepts_valid_signature(mock_db):
    email_obj = MagicMock()
    email_obj.id = 1
    mock_db.flush.side_effect = lambda: setattr(email_obj, "id", 3)

    app = _build_app()
    payload = _email_payload()
    body = json.dumps(payload).encode()
    headers = _svix_headers(body)

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    with patch("app.routers.webhooks.settings") as mock_settings, \
         patch("app.routers.webhooks.RawInboundEmail", return_value=email_obj), \
         patch("app.routers.webhooks._run_extraction"):
        mock_settings.RESEND_WEBHOOK_SECRET = TEST_SECRET

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/inbound-mail",
                content=body,
                headers={**headers, "Content-Type": "application/json"},
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
         patch("app.routers.webhooks.RawInboundEmail", return_value=email_obj), \
         patch("app.routers.webhooks.NEWSLETTER_SENDER_ALLOWED_DOMAINS", frozenset({"example.com"})):
        s.RESEND_WEBHOOK_SECRET = ""
        s.APP_ENV = APP_ENV_DEVELOPMENT
        result = await inbound_mail(
            request=request,
            background_tasks=bg,
            db=mock_db,
        )

    assert result.status_code == http.HTTPStatus.OK
    assert len(bg.tasks) == 1


@pytest.mark.asyncio
async def test_inbound_mail_sender_not_allowlisted_skips_extraction(mock_db):
    """Sender domain absent from NEWSLETTER_SENDER_ALLOWED_DOMAINS — email is
    stored but extraction is not queued, even with a non-empty text body."""
    email_obj = MagicMock()
    email_obj.id = 1
    mock_db.flush.side_effect = lambda: setattr(email_obj, "id", 13)

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
    body = _json.dumps(_email_payload(from_addr="newsletter@untrusted.com")).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(scope, receive)
    bg = BackgroundTasks()

    with patch("app.routers.webhooks.settings") as s, \
         patch("app.routers.webhooks.RawInboundEmail", return_value=email_obj), \
         patch("app.routers.webhooks.NEWSLETTER_SENDER_ALLOWED_DOMAINS", frozenset({"example.com"})):
        s.RESEND_WEBHOOK_SECRET = ""
        s.APP_ENV = APP_ENV_DEVELOPMENT
        result = await inbound_mail(
            request=request,
            background_tasks=bg,
            db=mock_db,
        )

    assert result.status_code == http.HTTPStatus.OK
    assert len(bg.tasks) == 0  # sender domain not allowlisted

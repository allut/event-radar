"""L6: GET /explore?q= must be capped at BROWSE_QUERY_MAX_LEN — an unbounded
string is cheap to send and expensive to scan (two trigram GIN indexes)."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app._generated.shared_constants import BROWSE_QUERY_MAX_LEN
from app.db import get_db
from app.auth.dependencies import get_current_user


def _build_app() -> FastAPI:
    from app.routers.browse import router

    app = FastAPI()
    app.include_router(router)

    async def _override_db():
        yield MagicMock()

    async def _override_user():
        return MagicMock(id=1, locale="en")

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


@pytest.mark.asyncio
async def test_query_over_max_length_rejected_422():
    app = _build_app()
    too_long = "x" * (BROWSE_QUERY_MAX_LEN + 1)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/explore", params={"q": too_long}, headers={"Authorization": "Bearer x"}
        )

    assert resp.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_query_at_max_length_is_not_rejected_by_length_validation():
    """At exactly the cap, FastAPI's Query(max_length=...) must not itself
    422 — any failure past this point would come from elsewhere (DB, etc.),
    not the length validator this test targets."""
    app = _build_app()
    at_cap = "x" * BROWSE_QUERY_MAX_LEN

    with patch(
        "app.routers.browse._browse_sql_path",
        new_callable=AsyncMock,
        return_value={"events": [], "total": 0, "limit": 20, "offset": 0, "has_more": False},
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/explore",
                params={"q": at_cap, "sort": "date", "for_you": "false"},
                headers={"Authorization": "Bearer x"},
            )

    assert resp.status_code != http.HTTPStatus.UNPROCESSABLE_ENTITY

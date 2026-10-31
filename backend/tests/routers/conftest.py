import importlib
import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.models.models import AdminAction
from app.rate_limit import limiter


# Every admin console router except admin_auth (login/session, mounted by its own tests).
ADMIN_ROUTER_MODULES = (
    "app.routers.admin",
    "app.routers.admin_claims",
    "app.routers.admin_events",
    "app.routers.admin_jobs",
    "app.routers.admin_reports",
    "app.routers.admin_submissions",
)


@pytest.fixture
def admin_app() -> FastAPI:
    """Minimal FastAPI app wiring every admin console router — shared by every
    admin-router test module that needs a bare app to mount them on."""
    app = FastAPI()
    for module_name in ADMIN_ROUTER_MODULES:
        app.include_router(importlib.import_module(module_name).router)
    return app


def admin_action_calls(db) -> list[AdminAction]:
    """The AdminAction rows a test's mocked db session had `add`ed. Shared by the
    admin audit-row test modules."""
    return [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], AdminAction)
    ]


def ndjson_lines(resp) -> list:
    """Parse a streamed NDJSON admin-trigger response body (issue #159) into
    its envelope lines. Shared by every admin-router test module exercising
    a streaming /admin/* trigger endpoint."""
    return [json.loads(line) for line in resp.text.strip().split("\n") if line]


def scalars_returning(items):
    """A sync MagicMock whose `.all()` returns `items` — stands in for the
    object `(await db.scalars(...))` resolves to. Shared by every admin-router
    test module that mocks a `db.scalars()` call."""
    r = MagicMock()
    r.all.return_value = items
    return r


def execute_rows(rows):
    """A sync MagicMock whose `.all()` returns `rows` — stands in for the
    object `(await db.execute(...))` resolves to. Shared by every admin-router
    test module that mocks a `db.execute()` call returning row tuples."""
    r = MagicMock()
    r.all.return_value = rows
    return r


@contextmanager
def patch_admin_settings() -> Iterator[MagicMock]:
    """Patch `settings` with one shared MagicMock in every module the admin
    auth path reads it from (the lockout helpers, the session dependency), so a test sets ADMIN_PASSWORD/APP_ENV/... once. Shared by
    every admin-router test module."""
    mock_settings = MagicMock()
    with ExitStack() as stack:
        for target in (
            "app.auth.admin_lockout.settings",
            "app.auth.dependencies.settings",
        ):
            stack.enter_context(patch(target, mock_settings))
        yield mock_settings


@pytest.fixture
def make_db_ctx():
    """Factory for a mock async-context-manager that yields the given db on
    __aenter__ — mirrors what `AsyncSessionLocal()` returns when used as
    `async with AsyncSessionLocal() as db:`."""
    def _factory(db: AsyncMock) -> MagicMock:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx
    return _factory


@pytest.fixture(autouse=True)
def _reset_admin_auth_failures():
    """The failure counter is a module-level dict (in-memory, single-process
    by design — see ADMIN_AUTH_MAX_FAILURES in app/constants/auth.py) shared across
    tests in this process; isolate each test from the others. Shared by
    every admin-auth-surface test module (Basic-auth lockout, admin console
    session login)."""
    from app.auth import admin_lockout

    admin_lockout._admin_auth_failures.clear()
    yield
    admin_lockout._admin_auth_failures.clear()


@pytest.fixture(autouse=True)
def _reset_public_caches():
    """_showcase_cache/_counts_cache/_prerender_event_ids_cache (routers/public.py)
    are module-level process-wide TTL caches (by design — see docstrings),
    shared across every test in this process. Isolate each test so an
    earlier test's cached payload for a given locale never leaks into a
    later one."""
    from app.routers import public as public_module

    public_module._showcase_cache.clear()
    public_module._counts_cache.clear()
    public_module._prerender_event_ids_cache = None
    yield
    public_module._showcase_cache.clear()
    public_module._counts_cache.clear()
    public_module._prerender_event_ids_cache = None


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The slowapi Limiter is a module-level singleton shared by every router
    test in this directory. Since L2 (routers/admin.py) moved every /admin/*
    route onto ONE shared_limit(..., scope="admin") bucket per client instead
    of one bucket per route, the whole admin test suite would otherwise share
    a single 10/minute allowance and start seeing spurious 429s partway
    through a run. Reset before (and after, for tests that don't clean up
    themselves) every test so each one starts with a fresh bucket."""
    limiter.reset()
    yield
    limiter.reset()

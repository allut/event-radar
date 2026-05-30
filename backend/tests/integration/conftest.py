import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# The top-level tests/conftest.py injects a fake SECRET_KEY for unit tests.
# Integration tests hit a live server, so tokens must be signed with the real
# key from .env — otherwise verify_magic_token gets BadSignature.
_env_path = Path(__file__).parent.parent.parent / ".env"
for _line in _env_path.read_text(encoding="utf-8").splitlines():
    if _line.startswith("SECRET_KEY="):
        os.environ["SECRET_KEY"] = _line.partition("=")[2].strip().strip('"').strip("'")
        break

from app.constants import HTTP_TIMEOUT_SECONDS  # noqa: E402
from app.config import settings  # noqa: E402

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")

# Engine is module-level (connection pool); sessions and clients are function-scoped
# to avoid asyncio event-loop mismatch between session fixtures and per-test loops.
_engine = create_async_engine(settings.DATABASE_URL)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def int_db():
    async with _session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=HTTP_TIMEOUT_SECONDS) as c:
        yield c


@pytest.fixture(scope="session")
def admin_auth():
    return (settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD or "test")

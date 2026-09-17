import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings
from app.constants import (
    ALEMBIC_DIR_NAME,
    APP_ENV_DEVELOPMENT,
    DB_POOL_RECYCLE_SECONDS,
    ERROR_SCHEMA_DRIFT,
    LOG_EVENT_SCHEMA_DRIFT,
)

log = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=DB_POOL_RECYCLE_SECONDS,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ALEMBIC_INI_PATH = _BACKEND_DIR / "alembic.ini"


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def assert_schema_at_head() -> None:
    """Compare the DB's current alembic revision against the migration
    head; raise in production rather than let a stale schema serve traffic
    (the admin_actions/0030 incident: prod code shipped ahead of a DB still
    on an older revision, and every audited admin action 500'd instead of
    failing loudly at boot). Development only warns, so a devcontainer with
    a half-migrated DB still boots."""
    alembic_cfg = Config(str(_ALEMBIC_INI_PATH))
    # script_location ("alembic") in alembic.ini is cwd-relative by alembic's
    # own resolution — pin it absolute so this guard doesn't depend on the
    # process's working directory matching backend/.
    alembic_cfg.set_main_option("script_location", str(_BACKEND_DIR / ALEMBIC_DIR_NAME))
    script = ScriptDirectory.from_config(alembic_cfg)
    head_revision = script.get_current_head()

    async with engine.begin() as conn:
        current_revision = await conn.run_sync(
            lambda sync_conn: MigrationContext.configure(
                sync_conn
            ).get_current_revision()
        )

    if current_revision == head_revision:
        return

    message = ERROR_SCHEMA_DRIFT.format(
        db_revision=current_revision, head_revision=head_revision
    )
    log_extra = {
        "event": LOG_EVENT_SCHEMA_DRIFT,
        "db_revision": current_revision,
        "head_revision": head_revision,
    }
    if settings.APP_ENV != APP_ENV_DEVELOPMENT:
        log.error(message, extra=log_extra)
        raise RuntimeError(message)
    log.warning(message, extra=log_extra)

"""`alembic check` locally: the ORM's tables and indexes match what the
migrations build. CI runs the same command; this catches drift (an index
declared in models.py but not in a migration, or the reverse) before a push.
Runs against the migrated scratch database and skips without one."""

import os
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).parent.parent


@pytest.mark.asyncio
async def test_models_match_migrated_schema(engine) -> None:
    result = subprocess.run(
        ["alembic", "check"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": engine.url.render_as_string(hide_password=False)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

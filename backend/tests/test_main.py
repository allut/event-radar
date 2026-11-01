"""Tests for the startup checks in app/main.py: the M1 dev-database-host
sanity check (_check_dev_database_host)."""

from unittest.mock import patch

from app.constants.core import APP_ENV_DEVELOPMENT
from app.main import _check_dev_database_host


# ---------------------------------------------------------------------------
# _check_dev_database_host (M1)
# ---------------------------------------------------------------------------


def test_dev_database_host_check_skips_outside_development():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = "production"
        mock_settings.DATABASE_URL = "postgresql+asyncpg://user:pass@real-host.example.com/db"
        with patch("app.main.log") as mock_log:
            _check_dev_database_host()
    mock_log.error.assert_not_called()


def test_dev_database_host_check_silent_for_localhost():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_settings.DATABASE_URL = "postgresql+asyncpg://eventradar:eventradar@localhost:5432/eventradar"
        with patch("app.main.log") as mock_log:
            _check_dev_database_host()
    mock_log.error.assert_not_called()


def test_dev_database_host_check_logs_error_for_non_local_host():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_settings.DATABASE_URL = (
            "postgresql+asyncpg://user:pass@ep-xxx.eu-central-1.aws.neon.tech/neondb?ssl=require"
        )
        with patch("app.main.log") as mock_log:
            _check_dev_database_host()
    mock_log.error.assert_called_once()

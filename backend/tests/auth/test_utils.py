"""Unit tests for app.auth.utils."""

import pytest
from fastapi import HTTPException

from app.constants.core import APP_ENV_DEVELOPMENT
from app.auth.utils import mask_email, require_configured_secret


class TestRequireConfiguredSecret:
    """M1: a dev-shaped APP_ENV alone must never be sufficient to fail open —
    ALLOW_INSECURE_DEV must also be explicitly true."""

    def test_configured_secret_returns_true_regardless_of_env(self):
        assert require_configured_secret(
            "s3cret",
            feature="Admin",
            setting_name="ADMIN_PASSWORD",
            app_env="production",
            allow_insecure_dev=False,
        ) is True

    def test_unset_secret_in_production_raises_503(self):
        with pytest.raises(HTTPException) as exc_info:
            require_configured_secret(
                "",
                feature="Admin",
                setting_name="ADMIN_PASSWORD",
                app_env="production",
                allow_insecure_dev=True,
            )
        assert exc_info.value.status_code == 503

    def test_unset_secret_in_dev_without_allow_insecure_dev_raises_503(self):
        """The core M1 regression guard: APP_ENV=development alone is not enough."""
        with pytest.raises(HTTPException) as exc_info:
            require_configured_secret(
                None,
                feature="Admin",
                setting_name="ADMIN_PASSWORD",
                app_env=APP_ENV_DEVELOPMENT,
                allow_insecure_dev=False,
            )
        assert exc_info.value.status_code == 503

    def test_unset_secret_in_dev_with_allow_insecure_dev_returns_false(self):
        result = require_configured_secret(
            "",
            feature="Admin",
            setting_name="ADMIN_PASSWORD",
            app_env=APP_ENV_DEVELOPMENT,
            allow_insecure_dev=True,
        )
        assert result is False

    def test_allow_insecure_dev_true_but_wrong_env_still_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            require_configured_secret(
                "",
                feature="Admin",
                setting_name="ADMIN_PASSWORD",
                app_env="production",
                allow_insecure_dev=True,
            )
        assert exc_info.value.status_code == 503


class TestMaskEmail:
    def test_keeps_visible_prefix_and_domain(self):
        assert mask_email("jane.doe@example.com") == "ja***@example.com"

    def test_short_local_part(self):
        assert mask_email("a@b.example") == "a***@b.example"

    def test_no_at_sign_returns_placeholder(self):
        assert mask_email("not-an-email") == "***"

    def test_never_includes_full_local_part(self):
        masked = mask_email("verylongusername@example.com")
        assert "verylongusername" not in masked
        assert masked.endswith("@example.com")

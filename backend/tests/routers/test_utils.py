"""Unit tests for app.routers.utils.mask_email — PII redaction for log output."""
from app.routers.utils import mask_email


class TestMaskEmail:
    def test_keeps_visible_prefix_and_domain(self):
        assert mask_email("aleksei.lutkov@gmail.com") == "al***@gmail.com"

    def test_short_local_part(self):
        assert mask_email("a@b.com") == "a***@b.com"

    def test_no_at_sign_returns_placeholder(self):
        assert mask_email("not-an-email") == "***"

    def test_never_includes_full_local_part(self):
        masked = mask_email("verylongusername@example.com")
        assert "verylongusername" not in masked
        assert masked.endswith("@example.com")

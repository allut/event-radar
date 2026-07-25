"""Tests for GET/POST /email/unsubscribe and /email/resubscribe (app/routers/unsubscribe.py)."""
import pytest

from app.auth.tokens import generate_unsubscribe_token


class TestUnsubscribe:
    @pytest.mark.asyncio
    async def test_flips_opt_in_off(self, mock_db, make_request, make_user):
        from app.routers.unsubscribe import unsubscribe

        user = make_user(user_id=5, opt_in=True)
        mock_db.get.return_value = user
        token = generate_unsubscribe_token(5)

        result = await unsubscribe(make_request(method="POST"), token, mock_db)

        assert user.email_digest_opt_in is False
        assert result["ok"] is True
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bad_token_raises_400(self, mock_db, make_request):
        from fastapi import HTTPException
        from app.routers.unsubscribe import unsubscribe

        with pytest.raises(HTTPException) as exc_info:
            await unsubscribe(make_request(method="POST"), "not-a-valid-token", mock_db)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_expired_token_raises_400(self, mock_db, make_request, monkeypatch):
        from fastapi import HTTPException
        from app.routers import unsubscribe as unsubscribe_module
        from itsdangerous import SignatureExpired

        def _raise(*args, **kwargs):
            raise SignatureExpired("expired")

        monkeypatch.setattr(unsubscribe_module, "verify_unsubscribe_token", _raise)

        with pytest.raises(HTTPException) as exc_info:
            await unsubscribe_module.unsubscribe(
                make_request(method="POST"), "expired-token", mock_db
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_user_not_found_raises_400(self, mock_db, make_request):
        from fastapi import HTTPException
        from app.routers.unsubscribe import unsubscribe

        mock_db.get.return_value = None
        token = generate_unsubscribe_token(999)

        with pytest.raises(HTTPException) as exc_info:
            await unsubscribe(make_request(method="POST"), token, mock_db)
        assert exc_info.value.status_code == 400


class TestResubscribe:
    @pytest.mark.asyncio
    async def test_flips_opt_in_on(self, mock_db, make_request, make_user):
        from app.routers.unsubscribe import resubscribe

        user = make_user(user_id=5, opt_in=False)
        mock_db.get.return_value = user
        token = generate_unsubscribe_token(5)

        result = await resubscribe(make_request(method="POST"), token, mock_db)

        assert user.email_digest_opt_in is True
        assert result["ok"] is True
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bad_token_raises_400(self, mock_db, make_request):
        from fastapi import HTTPException
        from app.routers.unsubscribe import resubscribe

        with pytest.raises(HTTPException) as exc_info:
            await resubscribe(make_request(method="POST"), "garbage", mock_db)
        assert exc_info.value.status_code == 400

"""POST /email/ads-off and /email/ads-on (undo), plus the unsubscribe coupling."""

import pytest
from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired

from app.auth.tokens import (
    generate_ads_off_token,
    generate_unsubscribe_token,
    verify_ads_off_token,
    verify_unsubscribe_token,
)
from app.config import settings
from app.constants.email import EMAIL_AD_CONSENT_WORDING_VERSION


def _consenting(make_user, user_id: int = 5, opt_in: bool = True):
    user = make_user(user_id=user_id, opt_in=opt_in)
    user.email_ad_consent = True
    user.email_ad_consent_version = EMAIL_AD_CONSENT_WORDING_VERSION
    return user


def _logged(db):
    return [c.args[0] for c in db.add.call_args_list]


def test_tokens_are_purpose_bound() -> None:
    assert verify_ads_off_token(generate_ads_off_token(5)) == 5
    with pytest.raises(BadSignature):
        verify_ads_off_token(generate_unsubscribe_token(5))
    with pytest.raises(BadSignature):
        verify_unsubscribe_token(generate_ads_off_token(5))


@pytest.mark.asyncio
async def test_ads_off_withdraws_and_logs_email_link(mock_db, make_request, make_user) -> None:
    from app.routers.unsubscribe import ads_off

    user = _consenting(make_user)
    mock_db.get.return_value = user
    result = await ads_off(make_request(method="POST"), generate_ads_off_token(5), mock_db)
    assert result["ok"] is True
    assert user.email_ad_consent is False
    assert user.email_digest_opt_in is True  # the digest keeps coming
    assert _logged(mock_db)[0].source == "email_link"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ads_off_twice_is_harmless(mock_db, make_request, make_user) -> None:
    from app.routers.unsubscribe import ads_off

    user = make_user(user_id=5)
    user.email_ad_consent = False
    mock_db.get.return_value = user
    result = await ads_off(make_request(method="POST"), generate_ads_off_token(5), mock_db)
    assert result["ok"] is True
    assert _logged(mock_db) == []


@pytest.mark.asyncio
async def test_ads_on_undo_grants_from_email_link_undo(
    mock_db, make_request, make_user, monkeypatch
) -> None:
    from app.routers.unsubscribe import ads_on

    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    user = make_user(user_id=5)
    user.email_ad_consent = False
    mock_db.get.return_value = user
    await ads_on(make_request(method="POST"), generate_ads_off_token(5), mock_db)
    assert user.email_ad_consent is True
    row = _logged(mock_db)[0]
    assert (row.granted, row.source) == (True, "email_link_undo")


@pytest.mark.asyncio
async def test_ads_on_refused_while_digest_off(
    mock_db, make_request, make_user, monkeypatch
) -> None:
    from app.routers.unsubscribe import ads_on

    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    user = make_user(user_id=5, opt_in=False)
    user.email_ad_consent = False
    mock_db.get.return_value = user
    with pytest.raises(HTTPException) as exc:
        await ads_on(make_request(method="POST"), generate_ads_off_token(5), mock_db)
    assert exc.value.status_code == 409
    assert user.email_ad_consent is False


@pytest.mark.asyncio
async def test_ads_on_refused_while_slots_flag_off(
    mock_db, make_request, make_user, monkeypatch
) -> None:
    from app.routers.unsubscribe import ads_on

    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    user = make_user(user_id=5)
    user.email_ad_consent = False
    mock_db.get.return_value = user
    with pytest.raises(HTTPException) as exc:
        await ads_on(make_request(method="POST"), generate_ads_off_token(5), mock_db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["ads_off", "ads_on"])
async def test_bad_token_gets_the_unsubscribe_error(
    name, mock_db, make_request
) -> None:
    from app.constants.email import ERROR_UNSUBSCRIBE_LINK_INVALID
    from app.routers import unsubscribe

    with pytest.raises(HTTPException) as exc:
        await getattr(unsubscribe, name)(make_request(method="POST"), "nope", mock_db)
    assert (exc.value.status_code, exc.value.detail) == (400, ERROR_UNSUBSCRIBE_LINK_INVALID)


@pytest.mark.asyncio
async def test_expired_token_gets_the_unsubscribe_error(
    mock_db, make_request, monkeypatch
) -> None:
    from app.constants.email import ERROR_UNSUBSCRIBE_LINK_EXPIRED
    from app.routers import unsubscribe

    def _raise(token):
        raise SignatureExpired("old")

    monkeypatch.setattr(unsubscribe, "verify_ads_off_token", _raise)
    with pytest.raises(HTTPException) as exc:
        await unsubscribe.ads_off(make_request(method="POST"), "t", mock_db)
    assert exc.value.detail == ERROR_UNSUBSCRIBE_LINK_EXPIRED


@pytest.mark.asyncio
async def test_email_link_unsubscribe_withdraws_consent(
    mock_db, make_request, make_user
) -> None:
    from app.routers.unsubscribe import unsubscribe

    user = _consenting(make_user)
    mock_db.get.return_value = user
    await unsubscribe(make_request(method="POST"), generate_unsubscribe_token(5), mock_db)
    assert user.email_ad_consent is False
    assert _logged(mock_db)[0].source == "digest_unsubscribe"


@pytest.mark.asyncio
async def test_resubscribe_leaves_consent_off(mock_db, make_request, make_user) -> None:
    from app.routers.unsubscribe import resubscribe, unsubscribe

    user = _consenting(make_user)
    mock_db.get.return_value = user
    token = generate_unsubscribe_token(5)
    await unsubscribe(make_request(method="POST"), token, mock_db)
    await resubscribe(make_request(method="POST"), token, mock_db)
    assert user.email_digest_opt_in is True
    assert user.email_ad_consent is False

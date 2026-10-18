"""Email ad consent in GET/PATCH /users/me."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.config import settings
from app.constants.email import EMAIL_AD_CONSENT_WORDING_VERSION


def _personas(db) -> None:
    result = MagicMock()
    result.all.return_value = []
    result.scalars.return_value.first.return_value = None
    db.execute.return_value = result


async def _patch(db, user, make_request, **fields):
    from app.routers.settings import PatchSettingsBody, patch_settings

    return await patch_settings(
        body=PatchSettingsBody(**fields),
        request=make_request(method="PATCH", path="/users/me"),
        current_user=user,
        db=db,
    )


def _logged(db):
    return [c.args[0] for c in db.add.call_args_list]


@pytest.mark.asyncio
async def test_get_reports_consent_and_availability(
    mock_db, make_user, make_request, monkeypatch
) -> None:
    from app.routers.settings import get_settings

    _personas(mock_db)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    user = make_user(opt_in=True)
    result = await get_settings(
        request=make_request(method="GET", path="/users/me"), current_user=user, db=mock_db
    )
    assert result["email_ad_consent"] is False
    assert result["email_ad_consent_available"] is True
    assert result["email_ad_consent_wording_version"] == EMAIL_AD_CONSENT_WORDING_VERSION

    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    result = await get_settings(
        request=make_request(method="GET", path="/users/me"), current_user=user, db=mock_db
    )
    assert result["email_ad_consent_available"] is False


@pytest.mark.asyncio
async def test_toggle_grants_and_withdraws_with_log_rows(
    mock_db, make_user, make_request, monkeypatch
) -> None:
    _personas(mock_db)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    user = make_user(opt_in=True)
    result = await _patch(mock_db, user, make_request, email_ad_consent=True)
    assert user.email_ad_consent is True
    assert result["email_ad_consent"] is True
    await _patch(mock_db, user, make_request, email_ad_consent=False)
    assert user.email_ad_consent is False
    rows = _logged(mock_db)
    assert [(r.granted, r.source) for r in rows] == [(True, "settings"), (False, "settings")]


@pytest.mark.asyncio
@pytest.mark.parametrize("opt_in,flag", [(False, True), (True, False)])
async def test_grant_refused_when_digest_or_flag_off(
    opt_in, flag, mock_db, make_user, make_request, monkeypatch
) -> None:
    _personas(mock_db)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", flag)
    user = make_user(opt_in=opt_in)
    with pytest.raises(HTTPException) as exc:
        await _patch(mock_db, user, make_request, email_ad_consent=True)
    assert exc.value.status_code == 409
    assert user.email_ad_consent is False
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_digest_off_and_consent_on_together_refused(
    mock_db, make_user, make_request, monkeypatch
) -> None:
    _personas(mock_db)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    user = make_user(opt_in=True)
    with pytest.raises(HTTPException) as exc:
        await _patch(
            mock_db, user, make_request, email_digest_opt_in=False, email_ad_consent=True
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_settings_digest_off_withdraws_consent(
    mock_db, make_user, make_request
) -> None:
    _personas(mock_db)
    user = make_user(opt_in=True)
    user.email_ad_consent = True
    user.email_ad_consent_version = EMAIL_AD_CONSENT_WORDING_VERSION
    result = await _patch(mock_db, user, make_request, email_digest_opt_in=False)
    assert user.email_ad_consent is False
    assert result["email_ad_consent"] is False
    assert _logged(mock_db)[0].source == "digest_unsubscribe"


@pytest.mark.asyncio
async def test_withdraw_allowed_with_flag_off(mock_db, make_user, make_request, monkeypatch) -> None:
    _personas(mock_db)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    user = make_user(opt_in=True)
    user.email_ad_consent = True
    user.email_ad_consent_version = EMAIL_AD_CONSENT_WORDING_VERSION
    await _patch(mock_db, user, make_request, email_ad_consent=False)
    assert user.email_ad_consent is False

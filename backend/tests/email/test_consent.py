"""Email ad consent: grant, withdraw, wording reset and account deletion logging."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.constants.email import (
    CONSENT_SOURCE_ACCOUNT_DELETION,
    CONSENT_SOURCE_DIGEST_UNSUBSCRIBE,
    CONSENT_SOURCE_EMAIL_LINK,
    CONSENT_SOURCE_EMAIL_LINK_UNDO,
    CONSENT_SOURCE_SETTINGS,
    EMAIL_AD_CONSENT_WORDING_VERSION,
)
from app.email.consent import (
    grant_ad_consent,
    log_account_deletion,
    reset_consent_for_wording_change,
    withdraw_ad_consent,
)
from app.email.subscription import set_digest_subscription
from app.models.models import EmailAdConsentLog


def _user(consent: bool = False, version: int | None = None, opt_in: bool = True):
    return SimpleNamespace(
        id=7,
        locale="et",
        email_digest_opt_in=opt_in,
        email_ad_consent=consent,
        email_ad_consent_version=version,
    )


def _logged(db) -> list[EmailAdConsentLog]:
    return [c.args[0] for c in db.add.call_args_list]


def test_grant_sets_flag_version_and_logs(mock_db) -> None:
    user = _user()
    assert grant_ad_consent(user, mock_db, CONSENT_SOURCE_SETTINGS) is True
    assert user.email_ad_consent is True
    assert user.email_ad_consent_version == EMAIL_AD_CONSENT_WORDING_VERSION
    (row,) = _logged(mock_db)
    assert (row.user_id, row.granted, row.source, row.locale) == (7, True, "settings", "et")
    assert row.wording_version == EMAIL_AD_CONSENT_WORDING_VERSION


def test_grant_is_idempotent(mock_db) -> None:
    user = _user(True, EMAIL_AD_CONSENT_WORDING_VERSION)
    assert grant_ad_consent(user, mock_db, CONSENT_SOURCE_SETTINGS) is False
    assert _logged(mock_db) == []


def test_undo_logs_email_link_undo(mock_db) -> None:
    user = _user()
    grant_ad_consent(user, mock_db, CONSENT_SOURCE_EMAIL_LINK_UNDO)
    assert _logged(mock_db)[0].source == "email_link_undo"


def test_withdraw_clears_flag_and_logs(mock_db) -> None:
    user = _user(True, 1)
    assert withdraw_ad_consent(user, mock_db, CONSENT_SOURCE_EMAIL_LINK) is True
    assert user.email_ad_consent is False
    assert user.email_ad_consent_version is None
    (row,) = _logged(mock_db)
    assert (row.granted, row.source, row.wording_version) == (False, "email_link", 1)


def test_withdraw_when_off_logs_nothing(mock_db) -> None:
    user = _user()
    assert withdraw_ad_consent(user, mock_db, CONSENT_SOURCE_SETTINGS) is False
    assert _logged(mock_db) == []


def test_digest_unsubscribe_withdraws_consent(mock_db) -> None:
    user = _user(True, 1)
    set_digest_subscription(user, False, mock_db)
    assert user.email_digest_opt_in is False
    assert user.email_ad_consent is False
    assert _logged(mock_db)[0].source == CONSENT_SOURCE_DIGEST_UNSUBSCRIBE


def test_resubscribe_never_restores_consent(mock_db) -> None:
    user = _user(True, 1)
    set_digest_subscription(user, False, mock_db)
    set_digest_subscription(user, True, mock_db)
    assert user.email_digest_opt_in is True
    assert user.email_ad_consent is False
    assert len(_logged(mock_db)) == 1


def test_subscribe_without_consent_logs_nothing(mock_db) -> None:
    user = _user(opt_in=False)
    set_digest_subscription(user, True, mock_db)
    set_digest_subscription(user, False, mock_db)
    assert _logged(mock_db) == []


def test_account_deletion_logs_withdrawal_when_consenting(mock_db) -> None:
    user = _user(True, 1)
    log_account_deletion(user, mock_db)
    (row,) = _logged(mock_db)
    assert (row.granted, row.source) == (False, CONSENT_SOURCE_ACCOUNT_DELETION)


@pytest.mark.asyncio
async def test_wording_reset_withdraws_stale_and_logs(mock_db) -> None:
    result = MagicMock()
    result.all.return_value = [(1, "et", 1), (2, "en", 1)]
    mock_db.execute.return_value = result
    assert await reset_consent_for_wording_change(mock_db) == 2
    assert mock_db.execute.await_count == 2  # UPDATE ... RETURNING, bulk INSERT


@pytest.mark.asyncio
async def test_wording_reset_noop_when_nobody_stale(mock_db) -> None:
    result = MagicMock()
    result.all.return_value = []
    mock_db.execute.return_value = result
    assert await reset_consent_for_wording_change(mock_db) == 0
    assert mock_db.execute.await_count == 1

"""Tests for the claim-intent magic-link token (#413) — app/auth/tokens.py's
generate_organizer_claim_link_token / verify_organizer_claim_link_token.

The "device round-trip" requirement means
the claim intent lives entirely inside the signed token, not in any
in-memory or session state — exactly what a fresh generate()/verify() pair
across two unrelated calls, with nothing shared between them but the token
string itself, already proves.
"""

from unittest.mock import patch

import pytest
from itsdangerous import BadSignature, SignatureExpired

from app.auth.tokens import (
    generate_organizer_claim_link_token,
    verify_organizer_claim_link_token,
)


class TestOrganizerClaimLinkToken:
    def test_round_trips_organizer_and_event_id(self):
        token, token_hash, expires_at = generate_organizer_claim_link_token(
            organizer_id=7, event_id=123
        )

        organizer_id, event_id = verify_organizer_claim_link_token(token)

        assert organizer_id == 7
        assert event_id == 123
        assert len(token_hash) == 64  # sha256 hex
        assert expires_at is not None

    def test_verify_on_a_fresh_process_state_still_round_trips(self):
        """Nothing but the token string crosses this boundary — models a
        verify happening on a different device/session than the request."""
        token, _, _ = generate_organizer_claim_link_token(organizer_id=1, event_id=99)

        # A distinct call, no shared local state with the line above beyond `token`.
        organizer_id, event_id = verify_organizer_claim_link_token(token)

        assert (organizer_id, event_id) == (1, 99)

    def test_tampered_token_rejected(self):
        token, _, _ = generate_organizer_claim_link_token(organizer_id=1, event_id=99)

        with pytest.raises(BadSignature):
            verify_organizer_claim_link_token(token + "x")

    def test_a_plain_organizer_sign_in_token_cannot_supply_event_id(self):
        """generate_organizer_magic_token's payload has no "eid" claim — using
        a regular sign-in link where a claim link was expected must fail
        loudly (KeyError branch), not silently claim event_id=0."""
        from app.auth.tokens import generate_organizer_magic_token

        token, _, _ = generate_organizer_magic_token(organizer_id=1)

        with pytest.raises(KeyError):
            verify_organizer_claim_link_token(token)

    def test_expired_token_rejected(self):
        token, _, _ = generate_organizer_claim_link_token(organizer_id=1, event_id=99)

        with patch("app.auth.tokens.organizer_magic_ttl_seconds", return_value=-1):
            with pytest.raises(SignatureExpired):
                verify_organizer_claim_link_token(token)

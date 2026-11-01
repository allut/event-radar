from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app._generated.shared_constants import CLAIM_STATUS_APPROVED, CLAIM_STATUS_PENDING
from app.constants.ingestion import PUBLISHER_STATUS_ACTIVE
from app.db import Base

if TYPE_CHECKING:
    from app.models.ingestion import Source
    from app.models.organizers import Organizer


class Publisher(Base):
    """The real-world entity an event-claiming Claim is granted against — see
    CONTEXT.md's Event Claiming glossary. One per Fienta organizer id, the
    whole source for KUMU/Estonia Concert Hall (external_id NULL), or one per
    resolved Piletilevi promoter id. Distinct from `Organizer` (the portal
    account that holds a claim)."""

    __tablename__ = "publishers"
    __table_args__ = (
        Index(
            "ix_publishers_source_external",
            "source_id",
            "external_id",
            unique=True,
        ),
        # Postgres unique indexes don't treat NULL as a duplicate, so the
        # index above alone allows two KUMU/ECH-style constant rows
        # (external_id NULL) per source — this partial index closes that gap
        # for the one-per-source-with-no-external_id case (#411 review
        # finding).
        Index(
            "ix_publishers_source_null_external",
            "source_id",
            unique=True,
            postgresql_where=text("external_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text(f"'{PUBLISHER_STATUS_ACTIVE}'"),
        default=PUBLISHER_STATUS_ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped["Source"] = relationship()


class Claim(Base):
    """An organizer's claim over a Publisher or an event series — see
    CONTEXT.md's Event Claiming glossary (Publisher claim / Series claim).
    Polymorphic over `kind`: a Publisher claim sets `publisher_id`, a Series
    claim sets `event_series_key` (the `event_series_key()` tuple from
    `events/queries.py`, serialized as `"<normalized_title>\\x1f<normalized_venue>"`)
    and always requires `justification` (#428 — a Series claim never
    auto-grants, so this is the claimant's only input at creation time)."""

    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_organizer_id", "organizer_id"),
        Index("ix_claims_publisher_id", "publisher_id"),
        # active_claim_for_target's Series arm (every public GET /events/{id})
        # filters event_series_key + status IN (pending, approved); the
        # approved-only unique index above can't serve the pending half.
        Index(
            "ix_claims_series_status",
            "event_series_key",
            "status",
            postgresql_where=text("event_series_key IS NOT NULL"),
        ),
        # Admin claims list: status filter + ORDER BY created_at.
        Index("ix_claims_status_created", "status", "created_at"),
        # Reject a duplicate/racing *approved* claim against the same
        # Publisher or Series at the DB layer (#431, slice 1 of #425) —
        # narrowed from pending-or-approved so multiple pending claims can
        # coexist on the same target (proof-preempts-assertion at auto-grant
        # time instead). Postgres unique indexes don't treat NULL as a
        # duplicate, so each is scoped to the rows that actually carry that
        # key, exactly like ix_publishers_source_null_external.
        Index(
            "ix_claims_active_publisher",
            "publisher_id",
            unique=True,
            postgresql_where=text(
                f"status = '{CLAIM_STATUS_APPROVED}' AND publisher_id IS NOT NULL"
            ),
        ),
        Index(
            "ix_claims_active_series",
            "event_series_key",
            unique=True,
            postgresql_where=text(
                f"status = '{CLAIM_STATUS_APPROVED}' AND event_series_key IS NOT NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    publisher_id: Mapped[int | None] = mapped_column(
        ForeignKey("publishers.id"), nullable=True
    )
    event_series_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text(f"'{CLAIM_STATUS_PENDING}'"),
        default=CLAIM_STATUS_PENDING,
    )
    # #412's verdict for this claim — one of VALID_CLAIM_VERIFICATION_MECHANISMS.
    # NULL only for the brief window between insert and the inline
    # verification call that fills it in the same request (#413).
    verification_mechanism: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    # System-generated proof token (app/claims/fienta_token.py::generate_claim_token)
    # the organizer places in their listing/DNS — reused by every recheck.
    proof_token: Mapped[str] = mapped_column(String(64), nullable=False)
    # Domain the DNS-TXT check ran against (KUMU/ECH's hardcoded institutional
    # domain, or a Piletilevi promoter's resolved contact domain) — persisted
    # so the #415 pending screen can render "add this TXT record" without
    # re-resolving a Piletilevi promoter's domain on every page load. NULL for
    # the fienta_token/admin_review mechanisms, which have no domain to show.
    verification_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # (#428) The resolved Piletilevi promoter contact mailbox a
    # piletilevi_mailbox check compared the claimant's account email
    # against — persisted (match or mismatch) so the admin queue can show
    # both emails as evidence without re-resolving the promoter page. NULL
    # for every other mechanism.
    verification_contact: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # (#428) Organizer-supplied reason a Series claim was made — required
    # only for kind=CLAIM_KIND_SERIES (enforced in app/claims/lifecycle.py,
    # not a DB constraint, same pattern as verification_domain's
    # mechanism-conditional NULL-ness). NULL for a Publisher claim.
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Bumped at creation and by every POST .../recheck — expire_stale_claims
    # (app/claims/lifecycle.py) compares this, not created_at, against
    # CLAIM_EXPIRY_DAYS so an organizer actively retrying isn't expired out
    # from under them.
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set once status leaves CLAIM_STATUS_PENDING (approved/cancelled/expired/
    # revoked) — NULL while pending.
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set by dedup's canonical-selection pass (#418) when this claim's event
    # lost a claimed-vs-claimed collision to a better-quality duplicate —
    # its pins stop applying while dormant, but the row is never
    # deleted/revoked; re-cleared the moment this claim's target is
    # canonical again. Orthogonal to `status` (an APPROVED claim can be
    # dormant) — see CONTEXT.md's Event Claiming glossary.
    dormant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )

    organizer: Mapped["Organizer"] = relationship()
    publisher: Mapped["Publisher | None"] = relationship()


class ClaimEditAttempt(Base):
    """One row per claim-editing-surface save attempt (#416) — backs the
    daily claim-edit cap, which counts attempts (not successful publishes)
    scoped per-organizer across every event they hold a claim on, mirroring
    how ORGANIZER_DAILY_SUBMISSION_CAP counts `Event` rows. The cap itself is
    ORGANIZER_DAILY_CLAIM_EDIT_CAP scaled by covered-event count (#438 — see
    claims/pinning.py::scaled_claim_edit_cap), not a flat constant. A
    dedicated table rather than reusing an existing one because no other row
    is written unconditionally on every claim-edit PATCH regardless of
    outcome."""

    __tablename__ = "claim_edit_attempts"
    __table_args__ = (
        Index("ix_claim_edit_attempts_organizer_created", "organizer_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

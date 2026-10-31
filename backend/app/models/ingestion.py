from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.events import EventSource


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    ingestion_runs: Mapped[list["IngestionRun"]] = relationship(back_populates="source")
    raw_events: Mapped[list["RawEvent"]] = relationship(back_populates="source")
    event_sources: Mapped[list["EventSource"]] = relationship(back_populates="source")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_ingestion_runs_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped["Source"] = relationship(back_populates="ingestion_runs")


class RawEvent(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        Index("ix_raw_events_fetched_at", "fetched_at"),
        # Composite serves ingest_skip_ids' (source_id, fetched_at >= cutoff)
        # predicate directly instead of a bitmap-AND over two single-column
        # indexes; also covers source_id-only lookups (leftmost prefix).
        Index("ix_raw_events_source_fetched", "source_id", "fetched_at"),
        # admin.py's event-inspector RawEvent↔EventSource join matches on
        # (source_id, external_id) — only (source_id, fetched_at) existed, so
        # external_id was a heap filter over the source's whole raw history
        # (Big-O audit #5, item 2.9).
        Index("ix_raw_events_source_external", "source_id", "external_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped["Source"] = relationship(back_populates="raw_events")


class RawInboundEmail(Base):
    __tablename__ = "raw_inbound_emails"
    __table_args__ = (Index("ix_raw_inbound_emails_received_at", "received_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    from_addr: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    to_addr: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    subject: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

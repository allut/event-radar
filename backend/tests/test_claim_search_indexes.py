"""Drift guard for M9: the claimable-event search expressions must match the
trigram GIN expression indexes (model + migration 0051) textually, or the
planner silently falls back to a seq scan of events."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy.dialects import postgresql

from app.constants.events import EVENT_SEARCH_TEXT_SQL
from app.models.events import Event
from app.routers.organizer_claim_search import claim_search_text, claim_url_text

MIGRATION = (
    Path(__file__).parent.parent
    / "alembic"
    / "versions"
    / "0051_claim_search_trgm_indexes.py"
)


def _sql(expr) -> str:
    return str(expr.compile(dialect=postgresql.dialect()))


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0051", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_search_expression_has_no_bind_params() -> None:
    assert "%(" not in _sql(claim_search_text())
    assert _sql(claim_search_text()) == EVENT_SEARCH_TEXT_SQL


def test_url_expression_is_bare_column() -> None:
    assert _sql(claim_url_text()) == "events.url"


def test_model_declares_both_indexes() -> None:
    names = {ix.name for ix in Event.__table__.indexes}
    assert {"ix_events_search_text_trgm", "ix_events_url_trgm"} <= names


def test_migration_uses_same_expression() -> None:
    module = _load_migration()
    assert module.SEARCH_TEXT_SQL == EVENT_SEARCH_TEXT_SQL

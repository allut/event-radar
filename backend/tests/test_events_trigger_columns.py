"""Drift guard: the events.updated_at trigger's frozen column list (migration
0050) must cover every events column except the sync-bookkeeping ones.

If this fails after adding an events column, add a migration that re-issues
trg_events_set_updated_at with the new column and update the list there.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.models.models import Event

MIGRATION = (
    Path(__file__).parent.parent
    / "alembic"
    / "versions"
    / "0050_events_trigger_row_compare.py"
)
UNTRACKED = {
    "updated_at",
    "detail_refetched_at",
    "detail_refetch_count",
    "geocode_attempted_at",
}


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0050", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trigger_columns_match_event_model() -> None:
    model_cols = {c.name for c in Event.__table__.columns} - UNTRACKED
    assert set(_load_migration().TRACKED_COLUMNS) == model_cols


def test_row_expression_lists_every_column_once() -> None:
    module = _load_migration()
    expr = module._row("NEW")
    assert expr.count("NEW.") == len(module.TRACKED_COLUMNS)

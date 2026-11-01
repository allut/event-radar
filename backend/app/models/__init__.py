"""Importing this package registers every model with Base.metadata."""

# ruff: noqa: F401
from app.models import (
    audit,
    claims,
    events,
    feeds,
    ingestion,
    llm,
    organizers,
    promotions,
    types,
    users,
)

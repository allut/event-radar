import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.i18n_data import PERSONAS as _PERSONAS_DATA
from app.config import settings
from app._generated.shared_constants import VALID_CATEGORIES, VALID_VIBES
from app.constants.ingestion import (
    PUBLISHER_STATUS_ACTIVE,
    SINGLE_INSTITUTION_SOURCES,
    SOURCE_KIND_API,
    SOURCE_SLUG_FIENTA,
)
from app.constants.ranking import VALID_TIMES
from app.ingestion.registry import SOURCE_CATALOG, SourceDef
from app.models.ingestion import Source
from app.models.claims import Publisher
from app.models.users import Persona

log = logging.getLogger(__name__)


def _persona_affinity(slug: str) -> dict:
    attr = f"PERSONA_{slug.upper()}_AFFINITY"
    try:
        return getattr(settings, attr)
    except AttributeError:
        raise KeyError(
            f"No affinity configured for persona {slug!r} — "
            f"add {attr} to config.py"
        ) from None


def _persona_seeds() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "slug": p["slug"],
            "display_name_en": p["names"]["en"],
            "display_name_et": p["names"]["et"],
            "display_name_ru": p["names"]["ru"],
            "affinity_vector": _persona_affinity(p["slug"]),
        }
        for p in _PERSONAS_DATA
    )


def _simple_source_def(sdef: SourceDef) -> dict[str, Any]:
    if sdef.url_attr:
        url = getattr(settings, sdef.url_attr, None)
        if url is None:
            raise KeyError(
                f"Source {sdef.slug!r} requires settings.{sdef.url_attr} "
                f"(set in registry.py SourceDef.url_attr) but it is not configured"
            )
        config: dict[str, Any] = {"url": url}
    else:
        config = {}
    return {"slug": sdef.slug, "kind": sdef.kind, "enabled": sdef.enabled, "config": config}


def _fienta_source() -> dict[str, Any]:
    return {
        "slug": SOURCE_SLUG_FIENTA,
        "kind": SOURCE_KIND_API,
        "enabled": True,
        "config": {
            "base_url": settings.FIENTA_BASE_URL,
            "organizer_ids": settings.FIENTA_ORGANIZER_IDS,
            "organizer_names": settings.FIENTA_ORGANIZER_NAMES,
        },
    }


async def seed_sources(db: AsyncSession) -> None:
    # Bulk-prefetch existing rows once rather than one SELECT per source
    # (Big-O audit #5, item 2.10) — mirrors seed_personas' bulk form below.
    slugs = [sdef.slug for sdef in SOURCE_CATALOG]
    existing_by_slug = {
        source.slug: source
        for source in (
            await db.scalars(select(Source).where(Source.slug.in_(slugs)))
        ).all()
    }
    for sdef in SOURCE_CATALOG:
        existing = existing_by_slug.get(sdef.slug)
        if sdef.slug == SOURCE_SLUG_FIENTA:
            await _upsert_fienta(db, existing)
        else:
            await _upsert_simple(db, _simple_source_def(sdef), existing)


async def seed_publishers(db: AsyncSession) -> None:
    """Idempotently insert the KUMU/Estonia Concert Hall constant Publisher rows."""
    slugs = list(SINGLE_INSTITUTION_SOURCES)
    sources_by_slug = {
        source.slug: source
        for source in (
            await db.scalars(select(Source).where(Source.slug.in_(slugs)))
        ).all()
    }
    source_ids = [s.id for s in sources_by_slug.values()]
    if not source_ids:
        return
    existing_source_ids = {
        p.source_id
        for p in (
            await db.scalars(
                select(Publisher).where(
                    Publisher.source_id.in_(source_ids),
                    Publisher.external_id.is_(None),
                )
            )
        ).all()
    }
    for slug, institution in SINGLE_INSTITUTION_SOURCES.items():
        name = institution.publisher_name
        source = sources_by_slug.get(slug)
        if source is None or source.id in existing_source_ids:
            continue
        try:
            async with db.begin_nested():
                db.add(
                    Publisher(
                        source_id=source.id,
                        external_id=None,
                        name=name,
                        status=PUBLISHER_STATUS_ACTIVE,
                    )
                )
                await db.flush()
        except IntegrityError:
            # ix_publishers_source_null_external (migration 0042): a
            # concurrent startup (e.g. an overlapping rolling deploy) already
            # inserted this source's constant row — not an error, just lost
            # the race. The savepoint rolls back only this insert.
            log.info(
                "seed_publishers: constant Publisher for source=%s already "
                "exists (race with a concurrent seed) — skipped",
                slug,
            )


def _validate_affinity_vector(slug: str, vector: dict) -> None:
    """Warn at startup if any persona affinity key is not in the taxonomy frozensets."""
    unknown_cats = set(vector.get("categories", {}).keys()) - VALID_CATEGORIES
    unknown_vibes = set(vector.get("vibes", {}).keys()) - VALID_VIBES
    unknown_times = set(vector.get("times", {}).keys()) - VALID_TIMES
    if unknown_cats:
        log.warning(
            "Persona %s: unknown category keys in affinity vector: %s",
            slug,
            unknown_cats,
        )
    if unknown_vibes:
        log.warning(
            "Persona %s: unknown vibe keys in affinity vector: %s", slug, unknown_vibes
        )
    if unknown_times:
        log.warning(
            "Persona %s: unknown time keys in affinity vector: %s", slug, unknown_times
        )


async def seed_personas(db: AsyncSession) -> None:
    """Idempotently insert the 9 personas. Updates display names and affinity vectors if changed."""
    seeds = _persona_seeds()
    for p in seeds:
        _validate_affinity_vector(p["slug"], p["affinity_vector"])
    slugs = [p["slug"] for p in seeds]
    existing_by_slug = {
        persona.slug: persona
        for persona in (
            await db.scalars(select(Persona).where(Persona.slug.in_(slugs)))
        ).all()
    }
    for p in seeds:
        existing = existing_by_slug.get(p["slug"])
        if existing:
            existing.display_name_en = p["display_name_en"]
            existing.display_name_et = p["display_name_et"]
            existing.display_name_ru = p["display_name_ru"]
            existing.affinity_vector = p["affinity_vector"]
        else:
            db.add(Persona(**p))
    await db.flush()


async def _upsert_fienta(db: AsyncSession, existing: Source | None) -> None:
    source = _fienta_source()
    if existing:
        desired = source["config"]
        db_cfg = existing.config or {}
        # Union organizer IDs so auto-discovered IDs from organizer_sync are preserved.
        # DB names take precedence — organizer_sync may have refreshed them.
        # Subtract retired_organizer_ids so a hardcoded seed ID that organizer_sync
        # has since retired (dead for STALE_ORGANIZER_RETIRE_DAYS) is not resurrected
        # by this union on the next startup.
        retired_ids = set(db_cfg.get("retired_organizer_ids", []))
        merged_ids = sorted(
            (set(desired["organizer_ids"]) | set(db_cfg.get("organizer_ids", [])))
            - retired_ids
        )
        merged_names = {
            **desired["organizer_names"],
            **db_cfg.get("organizer_names", {}),
        }
        merged = {
            **db_cfg,
            "base_url": desired["base_url"],
            "organizer_ids": merged_ids,
            "organizer_names": merged_names,
        }
        if merged != db_cfg:
            existing.config = merged
            await db.flush()
        return
    db.add(Source(**source))
    await db.flush()


async def _upsert_simple(
    db: AsyncSession, source_def: dict[str, Any], existing: Source | None
) -> None:
    """Insert source if absent; reconcile config['url'] and enabled (e.g. env override,
    or a source disabled in registry.py after already being seeded)."""
    if existing:
        changed = False
        new_url = source_def.get("config", {}).get("url")
        if new_url and (existing.config or {}).get("url") != new_url:
            existing.config = {**(existing.config or {}), "url": new_url}
            changed = True
        if existing.enabled != source_def["enabled"]:
            existing.enabled = source_def["enabled"]
            changed = True
        if changed:
            await db.flush()
        return
    db.add(Source(**source_def))
    await db.flush()

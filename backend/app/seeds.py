import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.i18n_data import PERSONAS as _PERSONAS_DATA
from app.config import settings
from app.constants import NEWSLETTER_SOURCE_SLUG, PILETILEVI_SOURCE_SLUG, VALID_TIMES
from app.llm.taxonomy import VALID_CATEGORIES, VALID_VIBES
from app.models.models import Persona, Source

log = logging.getLogger(__name__)


def _jsonld_sources() -> list[dict[str, Any]]:
    return [
        {
            "slug": "telliskivi",
            "kind": "html_jsonld",
            "enabled": True,
            "config": {"url": settings.TELLISKIVI_URL},
        },
        {
            "slug": "kultuurikatel",
            "kind": "html_jsonld",
            "enabled": True,
            "config": {"url": settings.KULTUURIKATEL_URL},
        },
        {
            "slug": "fotografiska",
            "kind": "html_jsonld",
            "enabled": True,
            "config": {"url": settings.FOTOGRAFISKA_URL},
        },
        {
            "slug": "kumu",
            "kind": "html_jsonld",
            "enabled": True,
            "config": {"url": settings.KUMU_URL},
        },
        {
            "slug": "estonia_concert_hall",
            "kind": "html_jsonld",
            "enabled": True,
            "config": {"url": settings.ESTONIA_CONCERT_HALL_URL},
        },
    ]


_AFFINITY_BY_SLUG = {
    "underground_clubber": lambda: settings.PERSONA_UNDERGROUND_CLUBBER_AFFINITY,
    "networking_pro": lambda: settings.PERSONA_NETWORKING_PRO_AFFINITY,
    "weekend_hobbyist": lambda: settings.PERSONA_WEEKEND_HOBBYIST_AFFINITY,
    "culture_buff": lambda: settings.PERSONA_CULTURE_BUFF_AFFINITY,
    "family_explorer": lambda: settings.PERSONA_FAMILY_EXPLORER_AFFINITY,
}


def _persona_seeds() -> tuple[dict[str, Any], ...]:
    seeds = []
    for p in _PERSONAS_DATA:
        affinity_fn = _AFFINITY_BY_SLUG.get(p["slug"])
        if affinity_fn is None:
            raise KeyError(
                f"No affinity configured for persona {p['slug']!r} — "
                "add it to _AFFINITY_BY_SLUG in seeds.py and PERSONA_*_AFFINITY in config.py"
            )
        seeds.append(
            {
                "slug": p["slug"],
                "display_name_en": p["names"]["en"],
                "display_name_et": p["names"]["et"],
                "display_name_ru": p["names"]["ru"],
                "affinity_vector": affinity_fn(),
            }
        )
    return tuple(seeds)


def _fienta_source() -> dict[str, Any]:
    return {
        "slug": "fienta",
        "kind": "api",
        "enabled": True,
        "config": {
            "base_url": settings.FIENTA_BASE_URL,
            "organizer_ids": settings.FIENTA_ORGANIZER_IDS,
            "organizer_names": settings.FIENTA_ORGANIZER_NAMES,
        },
    }


async def seed_sources(db: AsyncSession) -> None:
    await _upsert_fienta(db)
    for source_def in _jsonld_sources():
        await _upsert_simple(db, source_def)
    await _upsert_simple(
        db,
        {
            "slug": NEWSLETTER_SOURCE_SLUG,
            "kind": "inbound_email",
            "enabled": True,
            "config": {},
        },
    )
    await _upsert_simple(
        db,
        {
            "slug": PILETILEVI_SOURCE_SLUG,
            "kind": "html_scrape",
            "enabled": True,
            "config": {},
        },
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
    """Idempotently insert the 5 v0 personas. Updates display names and affinity vectors if changed."""
    for p in _persona_seeds():
        _validate_affinity_vector(p["slug"], p["affinity_vector"])
        existing = await db.scalar(select(Persona).where(Persona.slug == p["slug"]))
        if existing:
            existing.display_name_en = p["display_name_en"]
            existing.display_name_et = p["display_name_et"]
            existing.display_name_ru = p["display_name_ru"]
            existing.affinity_vector = p["affinity_vector"]
            await db.flush()
        else:
            db.add(Persona(**p))
            await db.flush()


async def _upsert_fienta(db: AsyncSession) -> None:
    source = _fienta_source()
    existing = await db.scalar(select(Source).where(Source.slug == source["slug"]))
    if existing:
        desired = source["config"]
        db_cfg = existing.config or {}
        # Union organizer IDs so auto-discovered IDs from organizer_sync are preserved.
        # DB names take precedence — organizer_sync may have refreshed them.
        merged_ids = sorted(
            set(desired["organizer_ids"]) | set(db_cfg.get("organizer_ids", []))
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


async def _upsert_simple(db: AsyncSession, source_def: dict[str, Any]) -> None:
    """Insert source if absent; update config['url'] if it changed (e.g. env override)."""
    existing = await db.scalar(select(Source).where(Source.slug == source_def["slug"]))
    if existing:
        new_url = source_def.get("config", {}).get("url")
        if new_url and (existing.config or {}).get("url") != new_url:
            existing.config = {**(existing.config or {}), "url": new_url}
            await db.flush()
        return
    db.add(Source(**source_def))
    await db.flush()

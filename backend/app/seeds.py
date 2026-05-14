import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import NEWSLETTER_SOURCE_SLUG, VALID_TIMES
from app.llm.taxonomy import VALID_CATEGORIES, VALID_VIBES
from app.models.models import Persona, Source

log = logging.getLogger(__name__)


def _jsonld_sources() -> list[dict]:
    return [
        {"slug": "telliskivi",             "kind": "html_jsonld", "enabled": True, "config": {"url": settings.TELLISKIVI_URL}},
        {"slug": "kultuurikatel",          "kind": "html_jsonld", "enabled": True, "config": {"url": settings.KULTUURIKATEL_URL}},
        {"slug": "fotografiska",           "kind": "html_jsonld", "enabled": True, "config": {"url": settings.FOTOGRAFISKA_URL}},
        {"slug": "kumu",                   "kind": "html_jsonld", "enabled": True, "config": {"url": settings.KUMU_URL}},
        {"slug": "estonia_concert_hall",   "kind": "html_jsonld", "enabled": True, "config": {"url": settings.ESTONIA_CONCERT_HALL_URL}},
    ]


def _persona_seeds() -> tuple[dict, ...]:
    return (
        {
            "slug": "underground_clubber",
            "display_name_en": "Underground Clubber",
            "display_name_et": "Klubi fänn",
            "display_name_ru": "Клубный завсегдатай",
            "affinity_vector": settings.PERSONA_UNDERGROUND_CLUBBER_AFFINITY,
        },
        {
            "slug": "networking_pro",
            "display_name_en": "Networking Pro",
            "display_name_et": "Võrgustiku professionaal",
            "display_name_ru": "Нетворкинг-профессионал",
            "affinity_vector": settings.PERSONA_NETWORKING_PRO_AFFINITY,
        },
        {
            "slug": "weekend_hobbyist",
            "display_name_en": "Weekend Hobbyist",
            "display_name_et": "Nädalavahetuse hobifänn",
            "display_name_ru": "Любитель выходного дня",
            "affinity_vector": settings.PERSONA_WEEKEND_HOBBYIST_AFFINITY,
        },
        {
            "slug": "culture_buff",
            "display_name_en": "Culture Buff",
            "display_name_et": "Kultuurihuviline",
            "display_name_ru": "Культурный энтузиаст",
            "affinity_vector": settings.PERSONA_CULTURE_BUFF_AFFINITY,
        },
        {
            "slug": "family_explorer",
            "display_name_en": "Family Explorer",
            "display_name_et": "Perefänn",
            "display_name_ru": "Семейный искатель приключений",
            "affinity_vector": settings.PERSONA_FAMILY_EXPLORER_AFFINITY,
        },
    )


def _fienta_source() -> dict:
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
    await _upsert_simple(db, {
        "slug": NEWSLETTER_SOURCE_SLUG,
        "kind": "inbound_email",
        "enabled": True,
        "config": {},
    })


def _validate_affinity_vector(slug: str, vector: dict) -> None:
    """Warn at startup if any persona affinity key is not in the taxonomy frozensets."""
    unknown_cats = set(vector.get("categories", {}).keys()) - VALID_CATEGORIES
    unknown_vibes = set(vector.get("vibes", {}).keys()) - VALID_VIBES
    unknown_times = set(vector.get("times", {}).keys()) - VALID_TIMES
    if unknown_cats:
        log.warning("Persona %s: unknown category keys in affinity vector: %s", slug, unknown_cats)
    if unknown_vibes:
        log.warning("Persona %s: unknown vibe keys in affinity vector: %s", slug, unknown_vibes)
    if unknown_times:
        log.warning("Persona %s: unknown time keys in affinity vector: %s", slug, unknown_times)


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
    existing = await db.scalar(
        select(Source).where(Source.slug == source["slug"])
    )
    if existing:
        desired = source["config"]
        db_cfg = existing.config or {}
        # Union organizer IDs so auto-discovered IDs from organizer_sync are preserved.
        # DB names take precedence — organizer_sync may have refreshed them.
        merged_ids = sorted(set(desired["organizer_ids"]) | set(db_cfg.get("organizer_ids", [])))
        merged_names = {**desired["organizer_names"], **db_cfg.get("organizer_names", {})}
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




async def _upsert_simple(db: AsyncSession, source_def: dict) -> None:
    """Insert source if absent; update config['url'] if it changed (e.g. env override)."""
    existing = await db.scalar(
        select(Source).where(Source.slug == source_def["slug"])
    )
    if existing:
        new_url = source_def.get("config", {}).get("url")
        if new_url and (existing.config or {}).get("url") != new_url:
            existing.config = {**(existing.config or {}), "url": new_url}
            await db.flush()
        return
    db.add(Source(**source_def))
    await db.flush()

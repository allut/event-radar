"""Single wiring table: slug + kind + adapter + optional URL attr."""

from dataclasses import dataclass

from app.constants import (
    NEWSLETTER_SOURCE_SLUG,
    PILETILEVI_SOURCE_SLUG,
    SOURCE_KIND_API,
    SOURCE_KIND_HTML_JSONLD,
    SOURCE_KIND_HTML_SCRAPE,
    SOURCE_KIND_INBOUND_EMAIL,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_FOTOGRAFISKA,
    SOURCE_SLUG_KUMU,
    SOURCE_SLUG_KULTUURIKATEL,
    SOURCE_SLUG_TELLISKIVI,
)
from app.ingestion.sources.fienta import FientaAdapter
from app.ingestion.sources.jsonld import (
    EstoniaConcertHallAdapter,
    FotografiskaAdapter,
    KumuAdapter,
    KultuurikateldAdapter,
    TelliskiviAdapter,
)
from app.ingestion.sources.piletilevi import PiletileviAdapter


@dataclass(frozen=True)
class SourceDef:
    slug: str
    kind: str
    adapter: type | None  # None = webhook-only (newsletter), not in registry
    url_attr: str | None = None  # settings attr holding the listing URL (jsonld sources)


SOURCE_CATALOG: tuple[SourceDef, ...] = (
    SourceDef(SOURCE_SLUG_FIENTA, SOURCE_KIND_API, FientaAdapter),
    SourceDef(SOURCE_SLUG_TELLISKIVI, SOURCE_KIND_HTML_JSONLD, TelliskiviAdapter, "TELLISKIVI_URL"),
    SourceDef(SOURCE_SLUG_KULTUURIKATEL, SOURCE_KIND_HTML_JSONLD, KultuurikateldAdapter, "KULTUURIKATEL_URL"),
    SourceDef(SOURCE_SLUG_FOTOGRAFISKA, SOURCE_KIND_HTML_JSONLD, FotografiskaAdapter, "FOTOGRAFISKA_URL"),
    SourceDef(SOURCE_SLUG_KUMU, SOURCE_KIND_HTML_JSONLD, KumuAdapter, "KUMU_URL"),
    SourceDef(SOURCE_SLUG_ESTONIA_CONCERT_HALL, SOURCE_KIND_HTML_JSONLD, EstoniaConcertHallAdapter, "ESTONIA_CONCERT_HALL_URL"),
    SourceDef(PILETILEVI_SOURCE_SLUG, SOURCE_KIND_HTML_SCRAPE, PiletileviAdapter),
    SourceDef(NEWSLETTER_SOURCE_SLUG, SOURCE_KIND_INBOUND_EMAIL, None),
)

ADAPTER_REGISTRY: dict[str, type] = {
    s.slug: s.adapter for s in SOURCE_CATALOG if s.adapter is not None
}

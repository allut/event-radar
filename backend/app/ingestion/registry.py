"""Single wiring table: slug + kind + adapter + optional URL attr."""

from dataclasses import dataclass

from app.constants import (
    SOURCE_SLUG_NEWSLETTER,
    SOURCE_SLUG_PILETILEVI,
    SOURCE_KIND_API,
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
from app.ingestion.sources.html_listing import (
    EstoniaConcertHallAdapter,
    KumuAdapter,
    PiletileviAdapter,
    TelliskiviAdapter,
)


@dataclass(frozen=True)
class SourceDef:
    slug: str
    kind: str
    adapter: type | None  # None = no adapter (newsletter webhook, or disabled)
    url_attr: str | None = None  # settings attr holding the listing URL
    enabled: bool = True


SOURCE_CATALOG: tuple[SourceDef, ...] = (
    SourceDef(SOURCE_SLUG_FIENTA, SOURCE_KIND_API, FientaAdapter),
    SourceDef(SOURCE_SLUG_TELLISKIVI, SOURCE_KIND_HTML_SCRAPE, TelliskiviAdapter, "TELLISKIVI_URL"),
    SourceDef(SOURCE_SLUG_KUMU, SOURCE_KIND_HTML_SCRAPE, KumuAdapter, "KUMU_URL"),
    SourceDef(SOURCE_SLUG_ESTONIA_CONCERT_HALL, SOURCE_KIND_HTML_SCRAPE, EstoniaConcertHallAdapter, "ESTONIA_CONCERT_HALL_URL"),
    SourceDef(SOURCE_SLUG_PILETILEVI, SOURCE_KIND_HTML_SCRAPE, PiletileviAdapter),
    SourceDef(SOURCE_SLUG_KULTUURIKATEL, SOURCE_KIND_HTML_SCRAPE, None, None, enabled=False),
    SourceDef(SOURCE_SLUG_FOTOGRAFISKA, SOURCE_KIND_HTML_SCRAPE, None, None, enabled=False),
    SourceDef(SOURCE_SLUG_NEWSLETTER, SOURCE_KIND_INBOUND_EMAIL, None),
)

ADAPTER_REGISTRY: dict[str, type] = {
    s.slug: s.adapter for s in SOURCE_CATALOG if s.adapter is not None
}

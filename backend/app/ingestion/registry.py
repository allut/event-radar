"""Maps source slugs to their adapter classes."""
from app.ingestion.sources.fienta import FientaAdapter
from app.ingestion.sources.jsonld import (
    EstoniaConcertHallAdapter,
    FotografiskaAdapter,
    KumuAdapter,
    KultuurikateldAdapter,
    TelliskiviAdapter,
)

ADAPTER_REGISTRY: dict[str, type] = {
    "fienta": FientaAdapter,
    "telliskivi": TelliskiviAdapter,
    "kultuurikatel": KultuurikateldAdapter,
    "fotografiska": FotografiskaAdapter,
    "kumu": KumuAdapter,
    "estonia_concert_hall": EstoniaConcertHallAdapter,
}

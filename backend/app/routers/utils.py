"""Shared serialization helpers for event routers."""
from app.models.models import Event


def serialize_event(event: Event) -> dict:
    cl = event.classification
    return {
        "id": event.id,
        "slug": event.slug,
        "title": event.title_orig,
        "description": event.description_orig,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "venue_name": event.venue_name,
        "venue_address": event.venue_address,
        "lat": event.lat,
        "lng": event.lng,
        "url": event.url,
        "image_url": event.image_url,
        "price_min": float(event.price_min) if event.price_min is not None else None,
        "price_max": float(event.price_max) if event.price_max is not None else None,
        "currency": event.currency,
        "categories": cl.categories if cl else [],
        "vibes": cl.vibes if cl else [],
        "why_go": cl.why_go_bullets if cl else [],
        "quality_score": cl.quality_score if cl else None,
        "language": cl.language_detected if cl else None,
    }

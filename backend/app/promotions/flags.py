"""Launch flags for the Promotion offer and card checkout."""

from app.config import settings


def offer_enabled() -> bool:
    return settings.PROMOTIONS_OFFER_ENABLED


def checkout_enabled() -> bool:
    """Card checkout takes effect only while the offer flag is on."""
    return settings.PROMOTIONS_OFFER_ENABLED and settings.PROMOTIONS_CHECKOUT_ENABLED

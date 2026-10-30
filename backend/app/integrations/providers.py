"""The process-wide adapters. Routers take them through ``Depends`` so tests
override them with fakes."""

from app.integrations.payments import PaymentGateway, StripeGateway
from app.integrations.registry import AriregisterLookup, CachedRegistryLookup, RegistryLookup

_registry = CachedRegistryLookup(AriregisterLookup())
_payments = StripeGateway()


def get_registry_lookup() -> RegistryLookup:
    return _registry


def get_payment_gateway() -> PaymentGateway:
    return _payments


def clear_registry_cache() -> None:
    _registry.clear()

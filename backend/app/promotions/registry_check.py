"""Turn a registry lookup into the legal name or a coded refusal. Fails closed:
an outage is a refusal, never a pass."""

from app.constants.promotions import (
    PROMOTION_ERROR_REGISTRY_DELETED,
    PROMOTION_ERROR_REGISTRY_INVALID_CODE,
    PROMOTION_ERROR_REGISTRY_NOT_FOUND,
    PROMOTION_ERROR_REGISTRY_UNAVAILABLE,
    PROMOTION_REGISTRY_CODE_RE,
    PROMOTION_REGISTRY_ERROR_MESSAGES,
    REGISTRY_LOOKUP_DELETED,
    REGISTRY_LOOKUP_FOUND,
)
from app.integrations.registry import RegistryLookup, RegistryUnavailable


class RegistryRefused(Exception):
    """The register could not confirm this business."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def message(self) -> str:
        return PROMOTION_REGISTRY_ERROR_MESSAGES[self.code]


async def verified_legal_name(registry: RegistryLookup, registry_code: str) -> str:
    """The register's legal name for an active company, or `RegistryRefused`."""
    code = registry_code.strip()
    if not PROMOTION_REGISTRY_CODE_RE.match(code):
        raise RegistryRefused(PROMOTION_ERROR_REGISTRY_INVALID_CODE)
    try:
        result = await registry.lookup(code)
    except RegistryUnavailable:
        raise RegistryRefused(PROMOTION_ERROR_REGISTRY_UNAVAILABLE) from None
    if result.status == REGISTRY_LOOKUP_DELETED:
        raise RegistryRefused(PROMOTION_ERROR_REGISTRY_DELETED)
    if result.status != REGISTRY_LOOKUP_FOUND or not result.legal_name:
        raise RegistryRefused(PROMOTION_ERROR_REGISTRY_NOT_FOUND)
    return result.legal_name

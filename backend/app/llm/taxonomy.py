from app.constants import VALID_CATEGORIES, VALID_VIBES

__all__ = ["VALID_CATEGORIES", "VALID_VIBES", "validate_categories", "validate_vibes"]


def validate_categories(cats: list[str]) -> tuple[bool, list[str]]:
    invalid = sorted(set(cats) - VALID_CATEGORIES)
    return len(invalid) == 0, invalid


def validate_vibes(vibes: list[str]) -> tuple[bool, list[str]]:
    invalid = sorted(set(vibes) - VALID_VIBES)
    return len(invalid) == 0, invalid

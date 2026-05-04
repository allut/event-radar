VALID_CATEGORIES: frozenset[str] = frozenset({
    "music", "theater", "exhibitions", "workshops", "sports",
    "food_drink", "networking", "literature", "family", "cinema",
    "alternative", "nightlife",
})

VALID_VIBES: frozenset[str] = frozenset({
    "trendy", "casual", "intimate", "high_energy", "educational",
    "indie", "underground", "mainstream", "accessible", "niche",
})


def validate_categories(cats: list[str]) -> tuple[bool, list[str]]:
    invalid = sorted(set(cats) - VALID_CATEGORIES)
    return len(invalid) == 0, invalid


def validate_vibes(vibes: list[str]) -> tuple[bool, list[str]]:
    invalid = sorted(set(vibes) - VALID_VIBES)
    return len(invalid) == 0, invalid

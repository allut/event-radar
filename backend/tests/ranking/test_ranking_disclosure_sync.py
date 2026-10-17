"""Sync guard for the public Ranking disclosure page (issue #588).

shared/app-config.json lists the signal tiers the /ranking page names. The
SCORE_WEIGHT_* constants must sort into exactly those tiers, so a reweight that
changes the order fails here until the page (and its lastUpdated) is edited.
"""

from __future__ import annotations

from itertools import groupby

from app._generated import shared_constants as shared
from app.constants import ranking

def _weights(prefix: str, *, anon: bool) -> dict[str, float]:
    """Every SCORE_WEIGHT_* constant in the module, keyed by signal name.

    Enumerated, not listed, so a newly added term fails the tier comparison
    until the page names it.
    """
    out: dict[str, float] = {}
    for name in dir(ranking):
        if not name.startswith(prefix) or name.startswith("SCORE_WEIGHT_ANON_") != anon:
            continue
        out[name.removeprefix(prefix).lower()] = getattr(ranking, name)
    return out


SIGNED_IN_WEIGHTS = _weights("SCORE_WEIGHT_", anon=False)

# Signed-out reads drop feedback and score affinity as a neutral constant, so
# affinity never differentiates results and is not a named signal.
SIGNED_OUT_WEIGHTS = _weights("SCORE_WEIGHT_ANON_", anon=True)


def _tiers(weights: dict[str, float]) -> list[frozenset[str]]:
    """Signals grouped by equal weight, heaviest tier first."""
    ordered = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    return [frozenset(name for name, _ in grp) for _, grp in groupby(ordered, key=lambda kv: kv[1])]


def _declared(tiers: tuple[tuple[str, ...], ...]) -> list[frozenset[str]]:
    return [frozenset(tier) for tier in tiers]


def test_signed_in_weights_match_declared_tiers() -> None:
    assert _tiers(SIGNED_IN_WEIGHTS) == _declared(shared.RANKING_TIERS_SIGNED_IN)


def test_signed_out_weights_match_declared_tiers() -> None:
    assert _tiers(SIGNED_OUT_WEIGHTS) == _declared(shared.RANKING_TIERS_SIGNED_OUT)

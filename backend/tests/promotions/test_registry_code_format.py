"""The registry-code format check agrees with the frontend's on every shared case
(shared/fixtures/promotion_registry_codes.json, also run by the frontend suite)."""

import json
from pathlib import Path

import pytest

from app.constants.promotions import PROMOTION_REGISTRY_CODE_RE

CASES = json.loads(
    (Path(__file__).parents[3] / "shared" / "fixtures" / "promotion_registry_codes.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["why"] for c in CASES])
def test_registry_code_format(case: dict) -> None:
    assert bool(PROMOTION_REGISTRY_CODE_RE.fullmatch(case["code"])) is case["valid"]

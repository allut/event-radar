"""scripts/generate_shared.py: what each `scalars` value type emits to both stacks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "generate_shared", REPO / "scripts" / "generate_shared.py"
)
assert _spec is not None and _spec.loader is not None
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _cfg_with_scalars(scalars: dict) -> dict:
    cfg = json.loads((REPO / "shared" / "app-config.json").read_text(encoding="utf-8"))
    cfg["scalars"] = scalars
    return cfg


def _emit(scalars: dict) -> tuple[str, str]:
    cfg = _cfg_with_scalars(scalars)
    return (
        gen.write_backend_shared_constants(cfg, "1.0.0"),
        gen.write_frontend_shared_constants(cfg, "1.0.0"),
    )


def test_int_and_str_scalars_keep_their_shape() -> None:
    py, ts = _emit({"PAGE_SIZE": 20, "PARAM": "google_error"})

    assert "PAGE_SIZE: int = 20" in py
    assert 'PARAM: str = "google_error"' in py
    assert "export const PAGE_SIZE = 20;" in ts
    assert "export const PARAM = 'google_error';" in ts


def test_string_list_is_an_ordered_tuple_and_a_readonly_literal_array() -> None:
    py, ts = _emit({"REASONS": ["spam", "other"]})

    assert 'REASONS: tuple[str, ...] = ("spam", "other")' in py
    assert "export const REASONS = ['spam', 'other'] as const;" in ts


def test_single_item_list_is_still_a_tuple() -> None:
    py, _ts = _emit({"ONE": ["only"]})

    namespace: dict = {}
    exec(next(line for line in py.splitlines() if line.startswith("ONE:")), namespace)
    assert namespace["ONE"] == ("only",)


@pytest.mark.parametrize(
    "value",
    [True, 1.5, None, {"k": "v"}, [1, 2], [["nested"]], []],
    ids=["bool", "float", "null", "object", "int-list", "nested-list", "empty-list"],
)
def test_unsupported_values_are_refused_with_the_scalar_named(value: object) -> None:
    with pytest.raises(ValueError, match=r"scalars\.BAD:"):
        _emit({"BAD": value})

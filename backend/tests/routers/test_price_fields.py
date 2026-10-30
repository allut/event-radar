"""Every request-body price_* field is a bounded PriceField (routers/utils.py).

events.price_* and venues.price_* are Numeric(10,2): an unbounded float, or the
Infinity that json.loads accepts, reaches the database and fails as a DataError
500. The scan finds every BaseModel in app/routers, so a new body with a bare
`float` price fails here. Needs no database.
"""

import importlib
import inspect
import math
import pkgutil

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

import app.routers
from app.constants.events import PRICE_MAX_VALUE


def _price_fields() -> list[tuple[str, TypeAdapter]]:
    fields = []
    for info in pkgutil.iter_modules(app.routers.__path__):
        module = importlib.import_module(f"app.routers.{info.name}")
        for name, model in inspect.getmembers(module, inspect.isclass):
            if not issubclass(model, BaseModel) or model.__module__ != module.__name__:
                continue
            for field_name, field in model.model_fields.items():
                if field_name.startswith("price_"):
                    adapter: TypeAdapter = TypeAdapter(field.rebuild_annotation())
                    fields.append((f"{module.__name__}.{name}.{field_name}", adapter))
    return fields


PRICE_FIELDS = _price_fields()


def test_price_fields_found() -> None:
    # Guards the scan itself: 5 bodies x price_min/price_max today.
    assert len(PRICE_FIELDS) >= 10


@pytest.mark.parametrize(
    "bad", [PRICE_MAX_VALUE, 1e12, math.inf, math.nan, -1], ids=["max", "1e12", "inf", "nan", "negative"]
)
@pytest.mark.parametrize("label,adapter", PRICE_FIELDS, ids=[label for label, _ in PRICE_FIELDS])
def test_price_field_rejects_out_of_range(label: str, adapter: TypeAdapter, bad: float) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(bad)


@pytest.mark.parametrize("label,adapter", PRICE_FIELDS, ids=[label for label, _ in PRICE_FIELDS])
def test_price_field_accepts_real_prices(label: str, adapter: TypeAdapter) -> None:
    assert adapter.validate_python(0) == 0
    assert adapter.validate_python(PRICE_MAX_VALUE - 0.01) == PRICE_MAX_VALUE - 0.01
    assert adapter.validate_python(None) is None

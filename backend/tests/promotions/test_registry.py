"""The Äriregister adapter, its 24 h cache and the fail-closed legal-name check
(#617). No database: the shared HTTP call is replaced."""

import httpx
import pytest

from app.config import settings
from app.integrations import registry as registry_module
from app.integrations.registry import (
    AriregisterLookup,
    CachedRegistryLookup,
    RegistryUnavailable,
)
from app.promotions.registry_check import RegistryRefused, verified_legal_name
from tests.promotions.fakes import FakeRegistry


def response(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("GET", "https://ari.test/x"))


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "ARIREGISTER_BASE_URL", "https://ari.test/companies")
    monkeypatch.setattr(settings, "ARIREGISTER_USERNAME", "user")
    monkeypatch.setattr(settings, "ARIREGISTER_PASSWORD", "pass")


def script_http(monkeypatch, outcome):
    calls: list[str] = []

    async def fake_http_get(client, url, **kwargs):
        calls.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(registry_module, "http_get", fake_http_get)
    return calls


@pytest.mark.asyncio
async def test_found_company_returns_its_legal_name(configured, monkeypatch) -> None:
    calls = script_http(monkeypatch, response(200, {"name": "Acme OÜ", "status": "R"}))
    result = await AriregisterLookup().lookup("12345678")
    assert (result.status, result.legal_name) == ("found", "Acme OÜ")
    assert calls == ["https://ari.test/companies/12345678"]


@pytest.mark.asyncio
async def test_deleted_company_is_reported_deleted(configured, monkeypatch) -> None:
    script_http(monkeypatch, response(200, {"name": "Old OÜ", "status": "K"}))
    assert (await AriregisterLookup().lookup("12345678")).status == "deleted"


@pytest.mark.asyncio
async def test_a_404_is_not_found(configured, monkeypatch) -> None:
    err = httpx.HTTPStatusError("nf", request=httpx.Request("GET", "x"), response=response(404))
    script_http(monkeypatch, err)
    assert (await AriregisterLookup().lookup("12345678")).status == "not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectError("down"),
        httpx.HTTPStatusError("boom", request=httpx.Request("GET", "x"), response=response(503)),
        response(200, {"unexpected": True}),
    ],
)
async def test_outage_or_garbage_is_unavailable(configured, monkeypatch, outcome) -> None:
    script_http(monkeypatch, outcome)
    with pytest.raises(RegistryUnavailable):
        await AriregisterLookup().lookup("12345678")


@pytest.mark.asyncio
async def test_unconfigured_credentials_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ARIREGISTER_BASE_URL", "")
    with pytest.raises(RegistryUnavailable):
        await AriregisterLookup().lookup("12345678")


@pytest.mark.asyncio
async def test_repeat_lookups_within_ttl_hit_the_cache(monkeypatch) -> None:
    inner = FakeRegistry()
    inner.found("12345678", "Acme OÜ")
    now = [1000.0]
    monkeypatch.setattr(registry_module.time, "monotonic", lambda: now[0])
    cached = CachedRegistryLookup(inner)
    await cached.lookup("12345678")
    now[0] += 23 * 3600
    await cached.lookup("12345678")
    assert inner.calls == ["12345678"]
    now[0] += 2 * 3600  # 25 h after the first answer
    await cached.lookup("12345678")
    assert inner.calls == ["12345678", "12345678"]


@pytest.mark.asyncio
async def test_an_outage_is_never_cached() -> None:
    inner = FakeRegistry()
    inner.outage = True
    cached = CachedRegistryLookup(inner)
    with pytest.raises(RegistryUnavailable):
        await cached.lookup("12345678")
    inner.outage = False
    inner.found("12345678", "Acme OÜ")
    assert (await cached.lookup("12345678")).legal_name == "Acme OÜ"


@pytest.mark.asyncio
async def test_verified_legal_name_refusals_are_coded() -> None:
    fake = FakeRegistry()
    fake.found("11111111", "Live OÜ")
    fake.deleted("22222222", "Gone OÜ")
    assert await verified_legal_name(fake, " 11111111 ") == "Live OÜ"
    for code, expected in [
        ("abc", "registry_invalid_code"),
        ("22222222", "registry_company_deleted"),
        ("33333333", "registry_company_not_found"),
    ]:
        with pytest.raises(RegistryRefused) as exc:
            await verified_legal_name(fake, code)
        assert exc.value.code == expected
    fake.outage = True
    with pytest.raises(RegistryRefused) as exc:
        await verified_legal_name(fake, "11111111")
    assert exc.value.code == "registry_unavailable"


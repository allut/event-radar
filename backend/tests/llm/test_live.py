"""Live LLM provider integration tests — hit real APIs, skip if key absent.

Run with:
    cd backend
    pytest tests/llm/test_live.py -v -s -m live
"""
import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.llm.router import llm_json
from app.llm.taxonomy import validate_categories, validate_vibes

pytestmark = pytest.mark.live

# A realistic classify prompt so providers return meaningful JSON
_CLASSIFY_PROMPT = """\
Classify this Tallinn event. Respond with JSON only.

Allowed categories (pick 1-3): music, theater, exhibitions, workshops, sports, \
food_drink, networking, literature, family, cinema, alternative, nightlife
Allowed vibes (pick 1-3): trendy, casual, intimate, high_energy, educational, \
indie, underground, mainstream, accessible, niche

Event title: Jazz Evening at Telliskivi
Venue: Telliskivi Creative City
Description: An intimate jazz evening featuring local Estonian musicians performing \
classic and contemporary jazz standards. Free entry, limited seating.

JSON format:
{"categories": ["music"], "vibes": ["underground", "intimate"], \
"why_go": ["reason 1", "reason 2", "reason 3"], "quality": 0.8, "language": "en"}

Rules:
- "language" must be the ISO 639-1 code of the event's original language.
- "quality" is 0.0-1.0 indicating how compelling the event is.
- "why_go" must have exactly 3 short bullets (max 15 words each).
- Only use values from the allowed lists for categories and vibes."""


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # cache miss every time
    db.add = MagicMock()
    return db


def _assert_valid_classify(result: dict, model_label: str) -> None:
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    assert isinstance(result.get("categories"), list), "categories must be a list"
    assert isinstance(result.get("vibes"), list), "vibes must be a list"
    assert len(result["categories"]) >= 1, "at least one category required"
    assert len(result["vibes"]) >= 1, "at least one vibe required"
    _, bad_cats = validate_categories(result["categories"])
    assert not bad_cats, f"unknown categories from {model_label}: {bad_cats}"
    _, bad_vibs = validate_vibes(result["vibes"])
    assert not bad_vibs, f"unknown vibes from {model_label}: {bad_vibs}"
    if result.get("quality") is not None:
        assert 0.0 <= float(result["quality"]) <= 1.0, "quality out of [0,1]"
    assert "/" in model_label, f"unexpected model_label: {model_label}"


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_groq_live():
    result, model_label = await llm_json("classify", _CLASSIFY_PROMPT, _mock_db())
    assert model_label.startswith("groq/"), f"expected groq provider, got {model_label}"
    _assert_valid_classify(result, model_label)


@pytest.mark.skipif(not settings.CEREBRAS_API_KEY, reason="CEREBRAS_API_KEY not set")
async def test_cerebras_live():
    """Verify the Cerebras key and endpoint are reachable.

    Cerebras allows only 1 req/min (Preview tier), so a 429 is an expected
    response that proves the key is valid and the endpoint is up. Only 401/403
    should fail this test.
    """
    import httpx
    from app.constants import LLM_MAX_TOKENS, LLM_PROVIDERS, LLM_REQUEST_TIMEOUT_SECONDS

    provider = next((p for p in LLM_PROVIDERS if p["name"] == "cerebras"), None)
    if provider is None:
        pytest.skip("cerebras not in LLM_PROVIDERS")
    async with httpx.AsyncClient(timeout=LLM_REQUEST_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{provider['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {settings.CEREBRAS_API_KEY}"},
            json={
                "model": provider["model"],
                "messages": [{"role": "user", "content": _CLASSIFY_PROMPT}],
                "response_format": {"type": "json_object"},
                "max_tokens": LLM_MAX_TOKENS,
            },
        )

    assert resp.status_code != http.HTTPStatus.UNAUTHORIZED, "Cerebras: unauthorized — check CEREBRAS_API_KEY"
    assert resp.status_code != http.HTTPStatus.FORBIDDEN, "Cerebras: forbidden — check CEREBRAS_API_KEY"
    # 200 = success, 429 = rate-limited (key valid, endpoint reachable — acceptable)
    assert resp.status_code in {http.HTTPStatus.OK, http.HTTPStatus.TOO_MANY_REQUESTS}, (
        f"Cerebras: unexpected status {resp.status_code}: {resp.text[:200]}"
    )
    if resp.status_code == http.HTTPStatus.OK:
        import json as _json
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        try:
            result = _json.loads(content)
        except _json.JSONDecodeError:
            pytest.fail(f"Cerebras 200 but response is not valid JSON: {content!r}")
        _assert_valid_classify(result, f"cerebras/{provider['model']}")


@pytest.mark.skipif(not settings.MISTRAL_API_KEY, reason="MISTRAL_API_KEY not set")
async def test_mistral_live():
    with patch.object(settings, "GROQ_API_KEY", ""), patch.object(settings, "CEREBRAS_API_KEY", ""):
        result, model_label = await llm_json("classify", _CLASSIFY_PROMPT, _mock_db())
    assert model_label.startswith("mistral/"), f"expected mistral provider, got {model_label}"
    _assert_valid_classify(result, model_label)


@pytest.mark.skipif(not settings.GROQ_API_KEY, reason="GROQ_API_KEY not set")
async def test_router_uses_cache_on_second_call():
    """Second call with same prompt hits the cache (no new HTTP call)."""
    from app.models.models import LlmCall

    cached = MagicMock(spec=LlmCall)
    cached.response_json = {"categories": ["music"], "vibes": ["indie"]}
    cached.provider = "groq"
    cached.model = "llama-3.3-70b-versatile"

    db = _mock_db()
    db.scalar = AsyncMock(return_value=cached)

    result, model_label = await llm_json("classify", _CLASSIFY_PROMPT, db)
    assert result == {"categories": ["music"], "vibes": ["indie"]}
    assert model_label == "groq/llama-3.3-70b-versatile"
    # No HTTP call made — db.add never called
    db.add.assert_not_called()

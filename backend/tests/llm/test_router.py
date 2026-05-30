"""Unit tests for app.llm.router — all LLM HTTP calls are mocked."""
import http
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.router import LLMError, _content_hash, llm_json


def _make_openai_response(content: dict, provider_name: str = "groq") -> MagicMock:
    """Build a mock httpx.Response that looks like an OpenAI JSON response."""
    body = {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 30},
    }
    mock_resp = MagicMock()
    mock_resp.status_code = http.HTTPStatus.OK
    mock_resp.json.return_value = body
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestContentHash:
    def test_deterministic(self):
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_inputs_differ(self):
        assert _content_hash("hello") != _content_hash("world")


class TestLlmJsonCacheHit:
    async def test_returns_cached_response(self, mock_db):
        cached_record = MagicMock()
        cached_record.response_json = {"same": True, "confidence": 0.9}
        cached_record.provider = "groq"
        cached_record.model = "llama-3.3-70b-versatile"
        mock_db.scalar = AsyncMock(return_value=cached_record)

        result, model_label = await llm_json("dedup", "some prompt", mock_db)
        assert result == {"same": True, "confidence": 0.9}
        assert model_label == "groq/llama-3.3-70b-versatile"


class TestLlmJsonProviderFallback:
    @pytest.fixture(autouse=True)
    def _cache_miss(self, mock_db):
        # Ensure cache lookup returns None (cache miss) so llm_json makes real provider calls.
        # Any new test class that exercises provider fallback must include this autouse fixture.
        mock_db.scalar.return_value = None

    async def test_uses_groq_when_configured(self, mock_db):
        mock_resp = _make_openai_response({"same": False, "confidence": 0.1})

        with (
            patch("app.llm.router.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.GROQ_API_KEY = "gsk_test"
            mock_settings.CEREBRAS_API_KEY = ""
            mock_settings.MISTRAL_API_KEY = ""

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result, model_label = await llm_json("dedup", "test prompt", mock_db)

        assert result == {"same": False, "confidence": 0.1}
        assert model_label.startswith("groq/")

    async def test_falls_back_to_cerebras_on_429(self, mock_db):
        groq_resp = MagicMock()
        groq_resp.status_code = http.HTTPStatus.TOO_MANY_REQUESTS
        groq_resp.raise_for_status = MagicMock()

        cerebras_resp = _make_openai_response({"categories": ["music"], "vibes": ["indie"]})
        cerebras_resp.status_code = http.HTTPStatus.OK

        call_count = {"n": 0}

        async def mock_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return groq_resp
            return cerebras_resp

        with (
            patch("app.llm.router.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.GROQ_API_KEY = "gsk_test"
            mock_settings.CEREBRAS_API_KEY = "csk_test"
            mock_settings.MISTRAL_API_KEY = ""

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = mock_post
            mock_client_cls.return_value = mock_client

            result, model_label = await llm_json("classify", "test prompt", mock_db)

        assert result == {"categories": ["music"], "vibes": ["indie"]}
        assert model_label.startswith("cerebras/")
        assert call_count["n"] == 2

    async def test_raises_llm_error_when_no_providers(self, mock_db):
        with patch("app.llm.router.settings") as mock_settings:
            mock_settings.GROQ_API_KEY = ""
            mock_settings.CEREBRAS_API_KEY = ""
            mock_settings.MISTRAL_API_KEY = ""

            with pytest.raises(LLMError):
                await llm_json("dedup", "test prompt", mock_db)

    async def test_raises_llm_error_when_all_providers_fail(self, mock_db):
        import httpx

        with (
            patch("app.llm.router.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.GROQ_API_KEY = "gsk_test"
            mock_settings.CEREBRAS_API_KEY = ""
            mock_settings.MISTRAL_API_KEY = ""

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(LLMError):
                await llm_json("classify", "test prompt", mock_db)

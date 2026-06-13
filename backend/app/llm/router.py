"""LLM provider chain: Groq → Cerebras → Mistral.

Entry point: ``llm_json(task, prompt, db)``

- Tries providers in priority order; skips any whose API key is empty.
- Falls through on 429 (rate limit) and network/parse errors.
- Caches successful responses by content_hash in ``llm_calls`` so identical
  prompts are never re-sent to the LLM.
- Records every attempt (success and failure) for audit.
- Raises ``LLMError`` if all available providers fail.
"""

import hashlib
import http
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import LLM_MAX_TOKENS, LLM_PROVIDERS, LLM_REQUEST_TIMEOUT_SECONDS

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when all configured LLM providers fail."""


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def content_hash(text: str) -> str:
    """Public delegate for ``_content_hash`` — lets other modules derive the
    identical cache key ``llm_json`` stores in ``llm_calls.content_hash``."""
    return _content_hash(text)


def llm_available() -> bool:
    """True if at least one provider in the chain has an API key configured.

    Lets callers degrade to a non-LLM path (e.g. the dedup pass falling back to
    rule-only clustering) instead of issuing calls that would all fail when no
    key is set — local dev, or lapsed keys in production.
    """
    return any(getattr(settings, p["key_attr"], "") for p in LLM_PROVIDERS)


async def llm_json(
    task: str,
    prompt: str,
    db: AsyncSession,
    *,
    event_id: int | None = None,
) -> tuple[dict[str, Any], str]:
    """Call the LLM provider chain and return ``(result_dict, model_label)``.

    ``model_label`` is ``"{provider}/{model}"`` (e.g. ``"groq/llama-3.3-70b-versatile"``).
    On a cache hit the label reflects the provider that originally answered.

    Checks the ``llm_calls`` cache first. On a cache miss, tries each provider
    in order, records the attempt, and returns the first successful result.

    Args:
        task: Short label stored in ``llm_calls.task`` (``"dedup"`` or ``"classify"``).
        prompt: Full prompt text (keep ≤600 tokens per project constraints).
        db: Active async DB session. Caller is responsible for committing.
        event_id: Optional event FK for audit traceability.

    Returns:
        Tuple of (parsed JSON dict, model_label string).

    Raises:
        LLMError: If every available provider fails.
    """
    from app.models.models import LlmCall

    content_hash = _content_hash(prompt)

    # Cache lookup — only consider rows with a successful response; newest first
    cached: LlmCall | None = await db.scalar(
        select(LlmCall)
        .where(
            LlmCall.content_hash == content_hash,
            LlmCall.response_json.is_not(None),
        )
        .order_by(LlmCall.created_at.desc())
        .limit(1)
    )
    if cached is not None:
        log.debug("llm cache hit: task=%s hash=%.8s", task, content_hash)
        model_label = f"{cached.provider}/{cached.model}"
        return cached.response_json, model_label  # type: ignore[return-value]

    errors: list[str] = []
    for provider in LLM_PROVIDERS:
        api_key: str = getattr(settings, provider["key_attr"], "")
        if not api_key:
            continue

        record = LlmCall(
            task=task,
            event_id=event_id,
            content_hash=content_hash,
            provider=provider["name"],
            model=provider["model"],
        )

        try:
            async with httpx.AsyncClient(timeout=LLM_REQUEST_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{provider['base_url']}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": provider["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                        "max_tokens": LLM_MAX_TOKENS,
                    },
                )

            if resp.status_code == http.HTTPStatus.TOO_MANY_REQUESTS:
                log.warning(
                    "llm rate-limited: provider=%s task=%s", provider["name"], task
                )
                db.add(record)
                errors.append(f"{provider['name']}: 429 rate-limited")
                continue

            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            content = data["choices"][0]["message"]["content"]
            result: dict[str, Any] = json.loads(content)

            record.prompt_tokens = usage.get("prompt_tokens")
            record.completion_tokens = usage.get("completion_tokens")
            record.response_json = result
            db.add(record)
            model_label = f"{provider['name']}/{provider['model']}"
            log.debug(
                "llm success: provider=%s task=%s tokens=%s+%s",
                provider["name"],
                task,
                record.prompt_tokens,
                record.completion_tokens,
            )
            return result, model_label

        except json.JSONDecodeError as exc:
            msg = f"{provider['name']}: JSON parse error — {exc}"
            log.warning(
                "llm response parse failed: provider=%s error=%s", provider["name"], exc
            )
            db.add(record)
            errors.append(msg)
        except httpx.HTTPStatusError as exc:
            msg = f"{provider['name']}: HTTP {exc.response.status_code}"
            log.warning(
                "llm HTTP error: provider=%s status=%s",
                provider["name"],
                exc.response.status_code,
            )
            db.add(record)
            errors.append(msg)
        except httpx.HTTPError as exc:
            msg = f"{provider['name']}: network error — {exc}"
            log.warning(
                "llm network error: provider=%s error=%s", provider["name"], exc
            )
            db.add(record)
            errors.append(msg)
        except (KeyError, IndexError) as exc:
            msg = f"{provider['name']}: unexpected response shape — {exc}"
            log.warning(
                "llm response shape error: provider=%s error=%s", provider["name"], exc
            )
            db.add(record)
            errors.append(msg)

    raise LLMError(
        f"All LLM providers failed for task={task!r}: {'; '.join(errors) or 'no providers configured'}"
    )

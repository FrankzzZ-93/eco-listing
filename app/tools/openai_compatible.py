"""OpenAI-compatible chat backend.

Single source of truth for talking to any OpenAI-compatible chat-completions
endpoint (e.g. a relay station / 中转站 serving Opus/Claude/other models). Both
the live generation path (``LLMTool``) and the settings connectivity test
(``/settings/llm/test``) go through here, so request shape, URL normalization
and auth live in exactly one place.

``cfg`` is the dict shape from ``app.llm_settings`` and must carry
``base_url`` ("request path"), ``api_key`` and ``model``.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 0.7


def build_chat_url(base_url: str) -> str:
    """Normalize a user-provided base URL to the chat-completions endpoint.

    Accepts ``https://host``, ``https://host/v1`` or a full
    ``https://host/v1/chat/completions`` and always returns the endpoint.
    """
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def chat(cfg: dict, prompt: str, *, retries: int | None = None) -> str:
    """Run a single chat completion and return the assistant message content.

    Retries on any transport/parse error with exponential backoff. Parsing the
    content into JSON (if needed) is the caller's responsibility.
    """
    url = build_chat_url(cfg["base_url"])
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": DEFAULT_TEMPERATURE,
    }

    attempts = max(1, int(settings.llm_retry_max if retries is None else retries))
    backoff = float(settings.llm_retry_backoff_base)
    last_err: Exception | None = None

    for attempt in range(attempts):
        try:
            content = await _post_and_extract(url, cfg["api_key"], payload, timeout=settings.codex_timeout)
            logger.info(
                "openai_compatible chat ok (model=%s, attempt=%d, chars=%d)",
                cfg["model"], attempt + 1, len(content),
            )
            return content
        except Exception as e:  # noqa: BLE001 - retry on any transport/parse error
            last_err = e
            logger.warning(
                "openai_compatible chat failed (attempt %d/%d): %s",
                attempt + 1, attempts, e,
            )
            if attempt < attempts - 1:
                await asyncio.sleep(backoff ** attempt)

    raise RuntimeError(
        f"OpenAI-compatible API call failed after {attempts} attempts: {last_err}"
    )


async def probe(cfg: dict) -> tuple[bool, str]:
    """Cheaply verify connectivity/credentials with a tiny request.

    Returns ``(ok, message)`` and never raises — intended for the settings
    "test connection" action.
    """
    url = build_chat_url(cfg["base_url"])
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }
    try:
        await _post_and_extract(url, cfg["api_key"], payload, timeout=30)
        return True, "连接成功，模型可用"
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response is not None else ""
        return False, f"HTTP {e.response.status_code if e.response is not None else '?'}: {body}"
    except Exception as e:  # noqa: BLE001
        return False, f"连接失败: {e}"


async def _post_and_extract(url: str, api_key: str, payload: dict, *, timeout: float) -> str:
    """POST to the endpoint and return the assistant message content string."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=_headers(api_key), json=payload)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        content = str(content)
    return content.strip()

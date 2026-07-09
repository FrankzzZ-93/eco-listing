"""Amazon Listing image *planning* via the codex CLI (text generation, no key).

The ported studio (amazon-image-studio) builds the planner system/user prompts
and a JSON Schema client-side, then normally POSTs them to OpenAI. We keep all
that logic client-side and only swap the transport: the frontend sends the
prompts + schema here, and we run codex to produce the JSON plan.
"""

from __future__ import annotations

import json
import logging

from app.config import settings
from app.tools.codex_exec import codex_exec

logger = logging.getLogger(__name__)

# Planning emits a large structured JSON (7-12 image slots × localized copy), so
# it must not be capped by a short scrape-oriented codex timeout. Give it a
# generous floor while still honoring a higher configured value.
_PLAN_MIN_TIMEOUT_SECONDS = 1800


def _plan_timeout() -> int:
    from app import app_settings

    configured = app_settings.get_scrape_param("codex_timeout", settings.codex_timeout)
    return max(int(configured), _PLAN_MIN_TIMEOUT_SECONDS)


def _extract_json_text(raw: str) -> str:
    """Pull the final JSON object out of codex `--json` JSONL output.

    The agent's answer is the last ``item.completed`` event whose item type is
    ``agent_message``. Strips markdown fences if present.
    """
    lines = [l for l in raw.splitlines() if l.strip()]
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "item.completed":
            continue
        item = obj.get("item") or {}
        if item.get("type") not in ("agent_message", "message"):
            continue
        text = (item.get("text") or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return text
    # Fallback: maybe the whole thing is already JSON.
    return raw.strip()


async def plan_listing_images(system: str, user: str, schema: dict | None) -> str:
    """Run codex to produce the planner JSON. Returns the JSON *string*.

    Raises:
        ValueError: codex returned something that isn't valid JSON.
        CodexExecError: the codex subprocess failed.
    """
    parts = [
        system.strip(),
        "",
        user.strip(),
        "",
        "You MUST respond with ONLY a single JSON object. No markdown fences, no"
        " explanation, no extra text before or after the JSON.",
    ]
    if schema:
        parts += [
            "The JSON object MUST strictly conform to this JSON Schema:",
            json.dumps(schema, ensure_ascii=False),
        ]
    prompt = "\n".join(parts)

    timeout = _plan_timeout()
    logger.info("image_plan start (prompt=%d bytes, timeout=%ds)", len(prompt), timeout)
    raw = await codex_exec(prompt, timeout=timeout)
    text = _extract_json_text(raw)

    # Validate it parses; re-serialize compactly so the frontend gets clean JSON.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("image_plan: codex did not return valid JSON; tail=%s", text[-500:])
        raise ValueError("AI 策划未返回有效 JSON，请重试") from e
    return json.dumps(parsed, ensure_ascii=False)

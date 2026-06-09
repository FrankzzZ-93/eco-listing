"""LLM tool.

By default every call is backed by the Codex CLI (uses the locally logged-in
account). Callers may pass an ``llm_config`` (see ``app.llm_settings``) to route
a specific call to an OpenAI-compatible HTTP endpoint instead — used by the
listing copywriter so users can run it on Opus/Claude/other models via a relay
station, while all other agents stay on Codex.
"""
from __future__ import annotations

import json
import logging

from app.llm_settings import PROVIDER_OPENAI_COMPATIBLE, is_configured
from app.tools import openai_compatible
from app.tools.codex_exec import codex_exec

logger = logging.getLogger(__name__)


class LLMTool:
    def __init__(self):
        self.total_tokens = 0

    async def call(
        self,
        model: str,
        prompt: str,
        attachments: list[str] | None = None,
        response_format: str = "json",
        llm_config: dict | None = None,
    ) -> dict:
        if attachments:
            prompt = self._append_attachment_note(prompt, attachments)

        if response_format == "json":
            prompt += (
                "\n\n⚠️ CRITICAL: Output ONLY a single valid JSON object. "
                "No markdown fences, no explanation, no text before or after the JSON."
            )

        # Route to an OpenAI-compatible API backend only when explicitly
        # configured for this call; otherwise fall back to the Codex CLI.
        if (
            llm_config
            and llm_config.get("provider") == PROVIDER_OPENAI_COMPATIBLE
            and is_configured(llm_config)
        ):
            content = await openai_compatible.chat(llm_config, prompt)
            return self._parse_api_content(content, response_format)

        raw = await self._codex_exec(prompt)
        return self._parse_response(raw, response_format)

    def _parse_api_content(self, content: str, response_format: str) -> dict:
        """Parse assistant content from the API into the expected shape."""
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if response_format == "json":
            return self._extract_json(text)
        return {"text": text}

    async def _codex_exec(self, prompt: str) -> str:
        """Delegates to the shared `codex_exec` runner.

        Timeout is governed exclusively by ``settings.codex_timeout``; this
        method intentionally does not accept or read a per-tool timeout.
        """
        logger.warning("LLMTool codex exec: %s...", prompt[:150])
        return await codex_exec(prompt)

    def _parse_response(self, raw: str, response_format: str) -> dict:
        lines = [l for l in raw.splitlines() if l.strip()]

        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("type") == "item.completed":
                item = obj.get("item") or {}
                if item.get("type") not in ("agent_message", "message"):
                    continue
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                if response_format == "json":
                    return self._extract_json(text)
                return {"text": text}

        if response_format == "json":
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

        logger.warning("LLMTool: no parseable response in %d lines, returning raw", len(lines))
        return {"text": raw}

    @staticmethod
    def _extract_json(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object boundaries
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break

        return {"text": text}

    @staticmethod
    def _append_attachment_note(prompt: str, attachments: list[str]) -> str:
        note = "\n\n[Note: This task references image files that cannot be included in text mode. "
        note += f"Files: {', '.join(attachments)}. "
        note += "Please proceed based on the text information provided.]"
        return prompt + note

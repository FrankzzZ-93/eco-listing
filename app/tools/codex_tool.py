"""Codex CLI wrapper for browser automation with LLM-driven interactions."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.codex_exec import CodexExecError, codex_exec

logger = logging.getLogger(__name__)


class CodexToolError(CodexExecError):
    """Backwards-compatible alias for callers catching tool-level errors."""


class CodexTool:
    """Wraps `codex exec` for non-interactive browser tasks.

    Uses the CLI in JSON-lines mode so that the output is machine-parseable.
    Falls back to raw text parsing when JSON output is unavailable.

    Timeout is controlled globally via ``settings.codex_timeout`` (see
    ``app/tools/codex_exec.py``); there is no per-instance override on purpose
    so that the configuration stays in one place.
    """

    async def browse_and_extract(
        self,
        url: str,
        instruction: str,
        *,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Open a URL in Codex's browser environment and extract data.

        Args:
            url: The target webpage URL.
            instruction: Natural language instruction for what to extract.
            response_schema: Optional JSON schema hint appended to the prompt.

        Returns:
            Extracted data as a dict.
        """
        schema_hint = ""
        if response_schema:
            schema_hint = (
                f"\n\nReturn the result strictly as JSON matching this schema:\n"
                f"```json\n{json.dumps(response_schema, ensure_ascii=False)}\n```"
            )

        prompt = (
            f"Open the webpage at {url} using a browser. "
            f"{instruction}"
            f"{schema_hint}\n\n"
            f"Output ONLY valid JSON, no markdown fences, no explanation."
        )

        raw = await self._exec(prompt)
        logger.warning("Codex browse_and_extract raw (%d bytes): %s", len(raw), raw[:500])
        result = self._parse_json(raw)
        logger.warning("Codex browse_and_extract parsed keys=%s, preview=%s", list(result.keys()) if isinstance(result, dict) else type(result), str(result)[:300])
        return result

    async def interact_and_extract(
        self,
        url: str,
        steps: list[str],
        extract_instruction: str,
    ) -> dict[str, Any]:
        """Multi-step browser interaction followed by extraction.

        Args:
            url: Starting URL.
            steps: Ordered list of interaction steps (click, scroll, etc.).
            extract_instruction: What to extract after interactions complete.

        Returns:
            Extracted data as a dict.
        """
        steps_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
        prompt = (
            f"Open the webpage at {url} using a browser.\n"
            f"Perform these steps in order:\n{steps_text}\n\n"
            f"After completing the steps: {extract_instruction}\n\n"
            f"Output ONLY valid JSON, no markdown fences, no explanation."
        )

        raw = await self._exec(prompt)
        return self._parse_json(raw)

    async def _exec(self, prompt: str) -> str:
        """Run `codex exec` and return stdout. Delegates to the shared runner.

        Re-raises low-level errors as ``CodexToolError`` so existing
        ``except CodexToolError`` callers still catch them.
        """
        try:
            return await codex_exec(prompt)
        except CodexExecError as e:
            raise CodexToolError(str(e)) from e

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Parse JSON from Codex --json JSONL output.

        Codex exec --json emits JSONL events. The agent's final answer lives in
        the last `item.completed` event where `item.type == "agent_message"`.
        Other item types (web_search, command_execution, mcp_tool_call) are tool
        invocations and should be skipped.
        """
        lines = [l for l in raw.splitlines() if l.strip()]

        # 1) Look for agent_message item.completed events (the LLM's final answer)
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("type") == "item.completed":
                item = obj.get("item") or {}
                item_type = item.get("type", "")
                if item_type not in ("agent_message", "message"):
                    continue
                text = item.get("text", "")
                if text:
                    text = text.strip()
                    if text.startswith("```"):
                        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        logger.warning("item.completed text is not valid JSON: %s", text[:300])
                        return {"text": text}

        # 2) Fallback: try parsing full output as a single JSON object
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 3) Fallback: try each line from end, skip non-data events
        skip_types = {
            "turn.started", "turn.completed", "thread.started",
            "item.started", "item.completed",
        }
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                if obj.get("type") in skip_types:
                    continue
                if "message" in obj:
                    content = obj["message"]
                    if isinstance(content, str):
                        try:
                            return json.loads(content)
                        except json.JSONDecodeError:
                            return {"text": content}
                    return content
                return obj

        logger.warning("_parse_json: no parseable data found in %d lines", len(lines))
        return {"text": raw}

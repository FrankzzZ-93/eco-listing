"""Codex CLI wrapper for browser automation with LLM-driven interactions."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import shutil
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

CODEX_BIN = shutil.which("codex") or "codex"


class CodexToolError(Exception):
    pass


class CodexTool:
    """Wraps `codex exec` for non-interactive browser tasks.

    Uses the CLI in JSON-lines mode so that the output is machine-parseable.
    Falls back to raw text parsing when JSON output is unavailable.
    """

    def __init__(self, timeout: int | None = None):
        self.timeout = timeout or settings.codex_timeout

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
        return self._parse_json(raw)

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
        """Run `codex exec` as a subprocess and return stdout."""
        cmd = [
            CODEX_BIN,
            "exec",
            "--json",
            prompt,
        ]

        logger.info("CodexTool exec: %s...", prompt[:120])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=None,  # inherit parent env (OPENAI_API_KEY etc.)
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise CodexToolError(
                f"Codex exec timed out after {self.timeout}s"
            )
        except FileNotFoundError:
            raise CodexToolError(
                "Codex CLI binary not found. Install with: npm install -g @openai/codex"
            )

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            raise CodexToolError(f"Codex exec failed (rc={proc.returncode}): {err_msg}")

        return stdout.decode(errors="replace").strip()

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Parse JSON from Codex output, handling JSONL format."""
        # codex exec --json outputs JSON Lines; take the last meaningful line
        lines = [l for l in raw.splitlines() if l.strip()]

        # Try parsing the full output as a single JSON object first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try each line from the end (last line is usually the final response)
        for line in reversed(lines):
            try:
                obj = json.loads(line)
                # Look for the response content in known structures
                if isinstance(obj, dict):
                    if "message" in obj:
                        content = obj["message"]
                        if isinstance(content, str):
                            try:
                                return json.loads(content)
                            except json.JSONDecodeError:
                                return {"text": content}
                        return content
                    return obj
            except json.JSONDecodeError:
                continue

        # Last resort: return raw text
        return {"text": raw}

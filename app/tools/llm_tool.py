from __future__ import annotations

import base64
import json

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

MODEL_MAP = {
    "gemini-pro": "gemini/gemini-1.5-pro",
    "claude-sonnet": "anthropic/claude-sonnet-4-20250514",
    "gpt-4o": "gpt-4o",
}

FALLBACK = {
    "gemini-pro": "gpt-4o",
    "claude-sonnet": "gpt-4o",
}


class LLMTool:
    def __init__(self):
        self.total_tokens = 0

    async def call(
        self,
        model: str,
        prompt: str,
        attachments: list[str] | None = None,
        response_format: str = "json",
    ) -> dict:
        try:
            return await self._invoke(model, prompt, attachments, response_format)
        except Exception:
            fallback = FALLBACK.get(model)
            if fallback:
                return await self._invoke(
                    fallback, prompt, attachments, response_format
                )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _invoke(self, model, prompt, attachments, response_format) -> dict:
        messages = self._build_messages(prompt, attachments)
        response = await litellm.acompletion(
            model=MODEL_MAP[model],
            messages=messages,
            timeout=settings.llm_timeout,
            response_format=(
                {"type": "json_object"} if response_format == "json" else None
            ),
        )
        content = response.choices[0].message.content
        self.total_tokens += response.usage.total_tokens

        if response_format == "json":
            return json.loads(content)
        return {"text": content}

    def _build_messages(self, prompt, attachments):
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for path in attachments or []:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._encode_image(path)},
                }
            )
        return [{"role": "user", "content": parts}]

    @staticmethod
    def _encode_image(path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = path.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(
            ext, "image/png"
        )
        return f"data:{mime};base64,{b64}"

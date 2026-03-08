"""OpenAI narrator backend (chat completions HTTP)."""

from __future__ import annotations

import os
from typing import Any

from chronicle_weaver_ai.narration.models import NarrationRequest, NarrationResponse
from chronicle_weaver_ai.narration.narrator import (
    build_prompt_parts,
    post_json,
    postprocess_narration_text,
)


class OpenAINarrator:
    """Narration adapter backed by OpenAI chat completions."""

    provider = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 10.0,
        http_post_json: Any | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI narrator")
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com"
        ).rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        self.timeout_seconds = timeout_seconds
        self.debug = os.environ.get("NARRATOR_DEBUG", "").strip().lower() in {
            "1",
            "true",
        }
        self._http_post_json = http_post_json or post_json

    def narrate(self, request: NarrationRequest) -> NarrationResponse:
        system_text, user_prompt = build_prompt_parts(request)

        response = self._http_post_json(
            url=f"{self.base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
            },
            timeout_seconds=self.timeout_seconds,
        )

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenAI response missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError("OpenAI response choice is invalid")
        message = first.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("OpenAI response missing message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenAI response missing message content")
        cleaned_text = postprocess_narration_text(content, debug=self.debug)
        return NarrationResponse(
            text=cleaned_text, provider=self.provider, model=self.model
        )

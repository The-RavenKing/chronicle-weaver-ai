"""Ollama narrator backend (local HTTP)."""

from __future__ import annotations

import json
import os
import socket
from typing import Any
from urllib import error, request

from chronicle_weaver_ai.narration.models import NarrationRequest, NarrationResponse
from chronicle_weaver_ai.narration.narrator import (
    DEFAULT_NARRATOR_TIMEOUT_SECONDS,
    build_prompt_parts,
    postprocess_narration_text,
)
from chronicle_weaver_ai.models import JSONValue, _to_json_value


class OllamaNarrator:
    """Narration adapter backed by local Ollama `/api/generate`."""

    provider = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = float(DEFAULT_NARRATOR_TIMEOUT_SECONDS),
        http_post_json: Any | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
        ).rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL") or "llama3"
        self.timeout_seconds = timeout_seconds
        self.debug = os.environ.get("NARRATOR_DEBUG", "").strip().lower() in {
            "1",
            "true",
        }
        self._http_post_json = http_post_json or _ollama_post_json

    def narrate(self, request: NarrationRequest) -> NarrationResponse:
        system_text, user_prompt = build_prompt_parts(request)
        full_prompt = f"SYSTEM:\n{system_text}\n\nUSER:\n{user_prompt}"

        response = self._http_post_json(
            url=f"{self.base_url}/api/generate",
            payload={
                "model": self.model,
                "prompt": full_prompt,
                "stream": False,
            },
            timeout_seconds=self.timeout_seconds,
        )
        text = response.get("response")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Ollama response missing 'response' text")
        cleaned_text = postprocess_narration_text(text, debug=self.debug)
        return NarrationResponse(
            text=cleaned_text, provider=self.provider, model=self.model
        )


def _ollama_post_json(
    url: str,
    payload: dict[str, JSONValue],
    headers: dict[str, str] | None = None,
    timeout_seconds: float = float(DEFAULT_NARRATOR_TIMEOUT_SECONDS),
) -> dict[str, JSONValue]:
    """POST JSON to Ollama and return parsed JSON response."""
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url=url, data=body, headers=request_headers, method="POST")

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = _short_error_body(exc.read())
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Ollama request timed out after {timeout_seconds:g}s"
        ) from exc
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise RuntimeError(
                f"Ollama request timed out after {timeout_seconds:g}s"
            ) from exc
        raise RuntimeError(f"Ollama network error: {reason}") from exc
    except socket.timeout as exc:
        raise RuntimeError(
            f"Ollama request timed out after {timeout_seconds:g}s"
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama invalid JSON response: {exc.msg}") from exc
    parsed_payload = _to_json_value(parsed)
    if not isinstance(parsed_payload, dict):
        raise RuntimeError("Ollama invalid JSON response: expected object")
    return parsed_payload


def _short_error_body(raw: bytes, max_len: int = 300) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return "no response body"
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[:max_len]

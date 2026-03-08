"""Minimal drand HTTP client for randomness beacon retrieval."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

from chronicle_weaver_ai.models import JSONValue, _to_json_value

DEFAULT_DRAND_BASE_URL = "https://api.drand.sh"


@dataclass(frozen=True)
class DrandBeacon:
    """drand beacon payload subset used by this project."""

    round: int
    randomness: str
    signature: str
    previous_signature: str | None = None


class DrandClientError(RuntimeError):
    """Structured drand client failure with fallback classification."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class DrandHTTPClient:
    """Small HTTP client for drand v1 relay endpoints."""

    def __init__(
        self,
        base_url: str = DEFAULT_DRAND_BASE_URL,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def base_url(self) -> str:
        return self._base_url

    def latest(self) -> DrandBeacon:
        """Fetch latest drand beacon."""
        payload = self._get_json("/public/latest")
        return _parse_beacon(payload)

    def by_round(self, round_number: int) -> DrandBeacon:
        """Fetch drand beacon by round."""
        if round_number < 1:
            raise ValueError("round_number must be >= 1")
        payload = self._get_json(f"/public/{round_number}")
        return _parse_beacon(payload)

    def _get_json(self, path: str) -> dict[str, JSONValue]:
        url = f"{self._base_url}{path}"
        try:
            with urlopen(url, timeout=self._timeout_seconds) as response:  # nosec B310
                raw = response.read().decode("utf-8")
        except TimeoutError as exc:
            raise DrandClientError(
                "timeout", f"drand request timed out: {exc}"
            ) from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise DrandClientError(
                    "timeout", f"drand request timed out: {reason}"
                ) from exc
            raise DrandClientError(
                "network_error", f"drand request failed: {exc}"
            ) from exc
        except OSError as exc:
            if isinstance(exc, socket.timeout):
                raise DrandClientError(
                    "timeout", f"drand request timed out: {exc}"
                ) from exc
            raise DrandClientError(
                "network_error", f"drand request failed: {exc}"
            ) from exc

        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DrandClientError(
                "bad_response", f"drand response is not valid JSON: {exc.msg}"
            ) from exc
        if not isinstance(decoded, dict):
            raise DrandClientError(
                "bad_response", "drand response must be a JSON object"
            )
        payload = _to_json_value(decoded)
        if not isinstance(payload, dict):
            raise DrandClientError(
                "bad_response", "drand response must be a JSON object"
            )
        return payload


def _parse_beacon(payload: dict[str, JSONValue]) -> DrandBeacon:
    round_raw = payload.get("round")
    randomness_raw = payload.get("randomness")
    signature_raw = payload.get("signature")
    previous_signature_raw = payload.get("previous_signature")

    if not isinstance(round_raw, int):
        raise DrandClientError("bad_response", "drand response missing integer 'round'")
    if not isinstance(randomness_raw, str) or not randomness_raw:
        raise DrandClientError(
            "bad_response", "drand response missing string 'randomness'"
        )
    if not isinstance(signature_raw, str) or not signature_raw:
        raise DrandClientError(
            "bad_response", "drand response missing string 'signature'"
        )
    if previous_signature_raw is not None and not isinstance(
        previous_signature_raw, str
    ):
        raise DrandClientError(
            "bad_response",
            "drand response 'previous_signature' must be a string",
        )

    return DrandBeacon(
        round=round_raw,
        randomness=randomness_raw,
        signature=signature_raw,
        previous_signature=previous_signature_raw,
    )

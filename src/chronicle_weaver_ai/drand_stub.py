"""drand integration contracts (stub only)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrandRandomness:
    """Placeholder drand randomness payload."""

    round: int
    randomness: str


class DrandClientStub:
    """Placeholder drand client, intentionally unused in phase-1 flow."""

    def latest(self) -> DrandRandomness:
        """Fetch latest randomness from drand (not implemented)."""
        raise NotImplementedError("drand is stubbed in this phase.")

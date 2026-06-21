"""Abstract base for external AI provider adapters.

Dependency-inversion anchor: engine/ and handlers/ depend only on this
ABC, never on concrete providers. A new vendor = one new file under
lib/providers/ + one line in __init__.py REGISTRY.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


Capability = Literal["text", "json", "long-context", "code"]


class ProviderUnavailableError(RuntimeError):
    """Raised when an adapter is installed but its backend is not reachable now."""


@dataclass(frozen=True)
class AskRequest:
    prompt: str
    model: str | None = None              # None → provider's default
    max_tokens: int | None = None
    temperature: float | None = None
    system: str | None = None


@dataclass(frozen=True)
class AskResponse:
    text: str
    provider: str                         # canonical name, e.g. "anthropic"
    model: str                            # resolved concrete model id
    tokens_in: int | None = None
    tokens_out: int | None = None
    raw: dict | None = None               # provider-specific extras


class ProviderBase(ABC):
    """One provider = one vendor's inference adapter."""

    name: str = "base"
    default_model: str = ""
    capabilities: tuple[Capability, ...] = ("text",)

    @abstractmethod
    def is_available(self) -> bool:
        """True iff the backend (SDK / CLI / HTTP) can be reached RIGHT NOW."""

    @abstractmethod
    def ask(self, request: AskRequest) -> AskResponse:
        """Blocking call.

        Raises ProviderUnavailableError when is_available() would return False
        or the call fails for backend-specific reasons.
        """

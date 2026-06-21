"""External AI provider adapters — Registry + discovery.

Extension policy (Open-Closed):
  Add new provider:
    1. Create lib/providers/<name>.py exposing `PROVIDER = YourClass`
    2. Add entry to `_REGISTRY` below (key = lookup name or alias → module name)
  No changes anywhere else in the codebase.

Consumers use `get_provider(name)`; they never import concrete classes.
"""
from __future__ import annotations

from importlib import import_module

from .base import (
    AskRequest,
    AskResponse,
    ProviderBase,
    ProviderUnavailableError,
)


# name or alias -> module name (under this package)
_REGISTRY: dict[str, str] = {
    "anthropic": "anthropic",
    "claude":    "anthropic",
    "openai":    "openai",
    "codex":     "openai",
    "ollama":    "ollama",   # v15.35.2 — local LLM, ensemble pool diversity
    # Future:
    # "google":  "google",
    # "gemini":  "google",
}


def list_aliases() -> list[str]:
    """Return every name/alias accepted by get_provider()."""
    return sorted(_REGISTRY.keys())


def get_provider(name: str) -> ProviderBase:
    """Return a provider instance by name or alias.

    Raises:
        KeyError:                 unknown name
        ProviderUnavailableError: adapter loaded but backend unreachable
    """
    module_name = _REGISTRY.get(name.lower())
    if not module_name:
        raise KeyError(
            f"Unknown provider {name!r}. Known: {list_aliases()}"
        )
    mod = import_module(f"{__name__}.{module_name}")
    provider_cls = getattr(mod, "PROVIDER", None)
    if provider_cls is None:
        raise RuntimeError(
            f"Provider module {module_name!r} does not export PROVIDER"
        )
    return provider_cls()


__all__ = [
    "AskRequest",
    "AskResponse",
    "ProviderBase",
    "ProviderUnavailableError",
    "get_provider",
    "list_aliases",
]

"""Multiplexer adapters — psmux / zellij / subprocess fallback.

Registry pattern. `detect_best()` picks the first available in
`_REGISTRY_ORDER`. Adding a new multiplexer = new file + one line here.

Wave 1 ships subprocess_fallback (always available).
Wave 2 prepends psmux_adapter and zellij_adapter.
"""
from __future__ import annotations

from importlib import import_module

from .base import MultiplexerBase, WorkerHandle, WorkerUnavailableError


# Preference order. First one whose is_available() returns True wins.
_REGISTRY_ORDER: tuple[str, ...] = (
    "psmux_adapter",
    # Future: "zellij_adapter",
    "subprocess_fallback",
)


def get_multiplexer(name: str) -> MultiplexerBase:
    mod = import_module(f"{__name__}.{name}")
    cls = getattr(mod, "MULTIPLEXER", None)
    if cls is None:
        raise RuntimeError(
            f"Multiplexer module {name!r} does not export MULTIPLEXER"
        )
    return cls()


def detect_best() -> MultiplexerBase:
    """Return the first registered multiplexer whose backend is reachable."""
    last_error: str | None = None
    for name in _REGISTRY_ORDER:
        try:
            m = get_multiplexer(name)
            if m.is_available():
                return m
        except Exception as e:
            last_error = f"{name}: {e!r}"
    raise WorkerUnavailableError(
        f"No multiplexer available. Tried: {_REGISTRY_ORDER}. Last: {last_error}"
    )


__all__ = [
    "MultiplexerBase",
    "WorkerHandle",
    "WorkerUnavailableError",
    "detect_best",
    "get_multiplexer",
]

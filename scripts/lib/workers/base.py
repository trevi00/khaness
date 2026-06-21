"""Abstract multiplexer interface — one worker = one spawned process.

Concrete adapters (subprocess_fallback, psmux_adapter, zellij_adapter)
implement this ABC. Callers depend only on the ABC + WorkerHandle.

A worker is identified by (session, worker_id). Sessions are logical
groups the caller names; worker_ids are unique within a session.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence


class WorkerUnavailableError(RuntimeError):
    """No multiplexer backend available, or spawn/kill failed."""


@dataclass(frozen=True)
class WorkerHandle:
    """Opaque handle to a spawned worker.

    Adapters may return subclasses to carry extra fields (pane id, pid,
    tmux target), but callers should not rely on those fields.
    """
    session: str
    worker_id: str
    backend: str


class MultiplexerBase(ABC):
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """True iff the multiplexer backend is usable on this host."""

    @abstractmethod
    def spawn(
        self,
        command: Sequence[str],
        *,
        session: str,
        worker_id: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> WorkerHandle:
        """Start a worker; non-blocking — returns as soon as the process exists."""

    @abstractmethod
    def list_workers(self, session: str) -> list[WorkerHandle]:
        """Return handles to currently-running workers in the session."""

    @abstractmethod
    def kill(self, handle: WorkerHandle) -> bool:
        """Terminate one worker. Returns True iff a running worker was killed."""

    @abstractmethod
    def kill_session(self, session: str) -> int:
        """Kill every worker in a session. Returns the count terminated."""

"""Headless fallback multiplexer — pure subprocess.Popen.

Always available (stdlib only). No UI; use this for scripted parallel
execution when psmux/zellij are absent or undesired.

State: class-level dict mapping (session, worker_id) -> Popen, guarded by
a class-level lock for thread safety. Shared across callers in the SAME
Python process. Lost on process exit — persistent workers should use
psmux_adapter (Wave 2).
"""
from __future__ import annotations

import os
import subprocess
import threading
from typing import Sequence

from .base import MultiplexerBase, WorkerHandle, WorkerUnavailableError


class SubprocessFallback(MultiplexerBase):
    name = "subprocess"

    # Process-scoped registry. Keyed by (session, worker_id).
    _WORKERS: dict[tuple[str, str], subprocess.Popen] = {}
    _LOCK: threading.Lock = threading.Lock()

    def is_available(self) -> bool:
        return True

    def spawn(
        self,
        command: Sequence[str],
        *,
        session: str,
        worker_id: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> WorkerHandle:
        key = (session, worker_id)
        with self._LOCK:
            existing = self._WORKERS.get(key)
            if existing is not None and existing.poll() is None:
                raise WorkerUnavailableError(
                    f"worker {session}/{worker_id} already running (pid={existing.pid})"
                )
            merged_env = {**os.environ, **(env or {})}
            proc = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=merged_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            self._WORKERS[key] = proc
        return WorkerHandle(session=session, worker_id=worker_id, backend=self.name)

    def list_workers(self, session: str) -> list[WorkerHandle]:
        handles: list[WorkerHandle] = []
        with self._LOCK:
            items = list(self._WORKERS.items())
        for (s, wid), proc in items:
            if s != session:
                continue
            if proc.poll() is None:
                handles.append(WorkerHandle(session=s, worker_id=wid, backend=self.name))
        return handles

    def kill(self, handle: WorkerHandle) -> bool:
        key = (handle.session, handle.worker_id)
        with self._LOCK:
            proc = self._WORKERS.get(key)
        if proc is None or proc.poll() is not None:
            return False
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        except Exception:
            return False
        return True

    def kill_session(self, session: str) -> int:
        killed = 0
        for handle in list(self.list_workers(session)):
            if self.kill(handle):
                killed += 1
        return killed


MULTIPLEXER = SubprocessFallback

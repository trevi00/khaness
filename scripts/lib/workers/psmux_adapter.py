"""psmux multiplexer adapter (Windows-native, tmux-compatible).

Uses the psmux CLI — https://github.com/psmux/psmux — which installs
three identical binaries: `psmux`, `pmux`, `tmux`. We try them in that
order; whichever resolves first wins.

Model:
  - One worker = one named tmux-style window inside a session.
  - Session is lazily created (idempotent new-session -d).
  - kill targets "session:worker_id".

Requires psmux on PATH. is_available() returns False if none of the three
CLI aliases resolve, or if `-V` fails (e.g., binary present but broken).
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Sequence

from .base import MultiplexerBase, WorkerHandle, WorkerUnavailableError


class PsmuxAdapter(MultiplexerBase):
    name = "psmux"

    # psmux installs all three as identical binaries; prefer the unambiguous one.
    _CLI_CANDIDATES = ("psmux", "pmux", "tmux")

    def _cli(self) -> str | None:
        for c in self._CLI_CANDIDATES:
            path = shutil.which(c)
            if path:
                return c
        # Windows-only fallback: winget installs update user PATH but existing
        # shells don't inherit until restart. Locate psmux.exe under the
        # per-user WinGet Packages directory.
        return self._winget_fallback()

    @staticmethod
    def _winget_fallback() -> str | None:
        import glob
        import os

        localappdata = os.environ.get("LOCALAPPDATA")
        if not localappdata:
            return None
        pattern = os.path.join(
            localappdata, "Microsoft", "WinGet", "Packages", "marlocarlo.psmux*"
        )
        for pkg_dir in sorted(glob.glob(pattern)):
            for exe_name in ("psmux.exe", "pmux.exe", "tmux.exe"):
                candidate = os.path.join(pkg_dir, exe_name)
                if os.path.isfile(candidate):
                    return candidate
        return None

    def is_available(self) -> bool:
        cli = self._cli()
        if not cli:
            return False
        try:
            r = subprocess.run(
                [cli, "-V"],
                capture_output=True, text=True, encoding="utf-8", timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    def spawn(
        self,
        command: Sequence[str],
        *,
        session: str,
        worker_id: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> WorkerHandle:
        cli = self._cli()
        if not cli:
            raise WorkerUnavailableError("no psmux/pmux/tmux CLI available")

        # Windows-safe quoting — psmux runs commands via Windows shell, so
        # we need list2cmdline rules (not POSIX shlex.join). Preserves spaces
        # and quotes in arguments when the CLI spawns the command.
        cmd_str = subprocess.list2cmdline(list(command))

        # Create session if absent (non-zero rc is fine — session already exists).
        subprocess.run(
            [cli, "new-session", "-d", "-s", session],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )

        new_window_cmd: list[str] = [cli, "new-window", "-t", session, "-n", worker_id]
        if cwd:
            new_window_cmd.extend(["-c", cwd])
        new_window_cmd.append(cmd_str)

        merged_env = None
        if env:
            import os as _os
            merged_env = {**_os.environ, **env}

        r = subprocess.run(
            new_window_cmd,
            capture_output=True, text=True, encoding="utf-8", timeout=10,
            env=merged_env,
        )
        if r.returncode != 0:
            raise WorkerUnavailableError(
                f"{cli} new-window failed (rc={r.returncode}): {r.stderr[:200]}"
            )
        return WorkerHandle(session=session, worker_id=worker_id, backend=self.name)

    def list_workers(self, session: str) -> list[WorkerHandle]:
        cli = self._cli()
        if not cli:
            return []
        r = subprocess.run(
            [cli, "list-windows", "-t", session, "-F", "#W"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        if r.returncode != 0:
            return []
        names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
        return [
            WorkerHandle(session=session, worker_id=n, backend=self.name)
            for n in names
        ]

    def kill(self, handle: WorkerHandle) -> bool:
        cli = self._cli()
        if not cli:
            return False
        r = subprocess.run(
            [cli, "kill-window", "-t", f"{handle.session}:{handle.worker_id}"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        return r.returncode == 0

    def kill_session(self, session: str) -> int:
        """Kill every worker in a session.

        Returns the count of workers present immediately before the kill,
        but ONLY if the kill command actually succeeded (rc==0). Otherwise
        returns 0 — prevents false-positive accounting when the session
        name is wrong or psmux server is unreachable.
        """
        cli = self._cli()
        if not cli:
            return 0
        before = len(self.list_workers(session))
        r = subprocess.run(
            [cli, "kill-session", "-t", session],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        return before if r.returncode == 0 else 0


MULTIPLEXER = PsmuxAdapter

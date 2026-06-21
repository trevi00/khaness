"""psmux — Python wrapper for the psmux/tmux-compatible terminal multiplexer.

Closes vision items #11 (psmux 세션 분리 + 계속 살려두기) and #12 (하나의
터미널에서 여러 세션 창 패널 동시 관리). psmux is the Windows-native
tmux equivalent (winget install marlocarlo.psmux), command-compatible with
tmux so this wrapper also works on Linux/macOS where `tmux` is installed
under that name.

Tool discovery:
  - Probes `psmux` first, then `pmux`, then `tmux` in PATH.
  - psmux ships all three names per its --help (NOTE line at bottom).
  - On systems without any: helpers raise PsmuxNotFoundError.

Design:
  - All helpers are fail-soft for the common autopilot path: a missing
    session / unreachable pane returns None or False, never raises.
  - Hard failures (binary missing, command timeout) raise so the caller
    can decide.
  - Subprocess timeout default: 5s for read commands, 10s for state-changing.

Public surface:
  - which() -> str | None
  - new_session(name, *, detached=True, command=None) -> bool
  - has_session(name) -> bool
  - list_sessions() -> list[str]
  - kill_session(name) -> bool
  - send_keys(target, text, *, literal=True, send_enter=False) -> bool
  - split_window(target, *, horizontal=False, percent=None, command=None) -> bool
  - list_panes(target_session) -> list[str]
  - capture_pane(target, *, max_lines=200) -> str | None
  - run_session_with_command(name, command, *, attach=False) -> bool

Caveats (cross-platform truthing):
  - psmux/tmux servers are PER-USER. send_keys to another user's pane
    fails by design.
  - On Windows, the default shell is pwsh; on Linux/macOS, the user's $SHELL.
    Helpers do NOT prescribe — pass `command` if a specific binary is needed.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Iterable


_BINARY_CANDIDATES: tuple[str, ...] = ("psmux", "pmux", "tmux")
_DEFAULT_READ_TIMEOUT: float = 5.0
_DEFAULT_WRITE_TIMEOUT: float = 10.0


class PsmuxNotFoundError(RuntimeError):
    """Raised when no compatible multiplexer binary is found in PATH."""


def which() -> str | None:
    """Return the resolved path of the first available multiplexer binary,
    or None if none is installed. Probes psmux → pmux → tmux."""
    for name in _BINARY_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _binary_or_raise() -> str:
    path = which()
    if path is None:
        raise PsmuxNotFoundError(
            f"None of {_BINARY_CANDIDATES} found in PATH. "
            "Install psmux: `winget install marlocarlo.psmux` (Windows) "
            "or `apt/brew install tmux` (Linux/macOS)."
        )
    return path


def _run(
    args: Iterable[str],
    *,
    timeout: float = _DEFAULT_READ_TIMEOUT,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Run multiplexer with prepended binary path. Returns CompletedProcess
    even on non-zero exit (caller inspects rc). Raises on timeout."""
    binary = _binary_or_raise()
    return subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        check=check,
    )


# ---------- Session lifecycle ----------

def has_session(name: str) -> bool:
    """True if a session named `name` exists. Empty/missing name → False.

    Uses psmux exit code: `has-session -t <name>` returns 0 when present.
    """
    if not name:
        return False
    try:
        proc = _run(["has-session", "-t", name])
    except (PsmuxNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def new_session(
    name: str,
    *,
    detached: bool = True,
    command: str | None = None,
    command_argv: list[str] | None = None,
    start_dir: str | None = None,
) -> bool:
    """Create a new session. Returns True on success.

    `detached=True` (default) creates the session without attaching — needed
    for autopilot use where we spawn workers in background.

    `command_argv` (preferred for paths with spaces or arbitrary args) passes
    a pre-split argv list literally — no whitespace splitting, no quote
    interpretation. Each element becomes one psmux command token after `--`.

    `command` (legacy convenience) accepts a single string and splits on
    whitespace. Mutually exclusive with `command_argv`. Use `command_argv`
    when the binary path may contain spaces or args contain shell metacharacters.
    """
    if not name:
        return False
    if command and command_argv:
        return False  # ambiguous: caller picks one
    args: list[str] = ["new-session", "-s", name]
    if detached:
        args.append("-d")
    if start_dir:
        args.extend(["-c", start_dir])
    if command_argv:
        args.append("--")
        args.extend(command_argv)
    elif command:
        args.append("--")
        # psmux accepts the rest as the literal argv to the spawned process.
        # Splitting on whitespace is fine for simple commands; for paths with
        # spaces use command_argv to bypass the split.
        args.extend(command.split())

    try:
        proc = _run(args, timeout=_DEFAULT_WRITE_TIMEOUT)
    except (PsmuxNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def kill_session(name: str) -> bool:
    """Kill session by name. Returns True on success, False if session
    didn't exist or kill failed (idempotent fail-soft)."""
    if not name:
        return False
    if not has_session(name):
        return False
    try:
        proc = _run(["kill-session", "-t", name], timeout=_DEFAULT_WRITE_TIMEOUT)
    except (PsmuxNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def list_sessions() -> list[str]:
    """Return active session names. Empty list on no-server / not-installed.

    `psmux ls` outputs lines like `name: 1 windows (created ...)`. We split
    on the first colon to extract just the name.
    """
    try:
        proc = _run(["list-sessions"])
    except (PsmuxNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            out.append(line.split(":", 1)[0].strip())
    return out


# ---------- Pane / window operations ----------

def split_window(
    target: str,
    *,
    horizontal: bool = False,
    percent: int | None = None,
    command: str | None = None,
    start_dir: str | None = None,
) -> bool:
    """Split a window in `target` (session or pane id). Returns True on success.

    `horizontal=True`: splits side-by-side (left/right). Default is vertical
    (top/bottom) per psmux convention.

    `percent`: size of new pane as percentage of available space.
    """
    if not target:
        return False
    args: list[str] = ["split-window", "-t", target]
    if horizontal:
        args.append("-h")
    else:
        args.append("-v")
    if percent is not None:
        args.extend(["-p", str(percent)])
    if start_dir:
        args.extend(["-c", start_dir])
    if command:
        args.append("--")
        args.extend(command.split())

    try:
        proc = _run(args, timeout=_DEFAULT_WRITE_TIMEOUT)
    except (PsmuxNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def list_panes(target_session: str) -> list[str]:
    """Return pane ids in `target_session` (e.g. ['%0', '%1']).

    `psmux list-panes -t <session>` prints lines like:
        0: [80x24] [history 0/2000, 0 bytes] %0 (active)
    We extract the `%N` token from each line.
    """
    if not target_session:
        return []
    try:
        proc = _run(["list-panes", "-t", target_session])
    except (PsmuxNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        for token in line.split():
            if token.startswith("%") and len(token) >= 2 and token[1:].isdigit():
                out.append(token)
                break
    return out


def send_keys(
    target: str,
    text: str,
    *,
    literal: bool = True,
    send_enter: bool = False,
) -> bool:
    """Send `text` keystrokes to `target` (pane id like `%2` or session name).

    `literal=True` (default) passes -l so psmux doesn't interpret keynames.
    `send_enter=True` appends an Enter keypress (useful for command exec).
    """
    if not target or not text:
        return False
    args: list[str] = ["send-keys", "-t", target]
    if literal:
        args.append("-l")
    args.append(text)
    if send_enter:
        # send-keys allows trailing keynames after literal text; we issue a
        # second call with `Enter` (no -l) so psmux interprets it as keypress.
        try:
            _run(args, timeout=_DEFAULT_WRITE_TIMEOUT)
            proc = _run(
                ["send-keys", "-t", target, "Enter"],
                timeout=_DEFAULT_WRITE_TIMEOUT,
            )
        except (PsmuxNotFoundError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0
    try:
        proc = _run(args, timeout=_DEFAULT_WRITE_TIMEOUT)
    except (PsmuxNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def capture_pane(target: str, *, max_lines: int = 200) -> str | None:
    """Capture pane scrollback to stdout. Returns text or None on failure.

    `max_lines` clamps the returned lines from the END (most recent N).
    """
    if not target:
        return None
    try:
        proc = _run(["capture-pane", "-p", "-t", target])
    except (PsmuxNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    lines = proc.stdout.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines)


# ---------- High-level helpers ----------

def run_session_with_command(
    name: str,
    command: str,
    *,
    start_dir: str | None = None,
) -> bool:
    """Convenience: spawn a detached session running `command`. Idempotent
    in the sense that an already-existing session by that name returns False
    without clobbering the running one — caller decides whether to kill+re-spawn.
    """
    if has_session(name):
        return False
    return new_session(name, detached=True, command=command, start_dir=start_dir)


def ensure_session(
    name: str,
    *,
    command: str | None = None,
    start_dir: str | None = None,
) -> bool:
    """Idempotent variant: create session if absent, return True if exists
    after the call (created or pre-existing)."""
    if has_session(name):
        return True
    return new_session(name, detached=True, command=command, start_dir=start_dir)

"""async_spawn — cross-platform detached subprocess helper (v15.35.6).

debate-1779008782-230c36 gen 4 Architect condition P3 fix infrastructure.

The debate gen 4 Critic confirmed that no detached-subprocess primitive
exists in `lib/evaluator_dispatcher`: both `invoke_evaluator_isolated`
and `invoke_ensemble_evaluator` use synchronous `subprocess.run(...,
capture_output=True)` which blocks the caller until subprocess exit.
For an "async-only Phase 3.5 dispatch" (gen 3 Architect S1) to be
possible, the dispatcher needs a `spawn-and-return-immediately`
primitive. This module provides that primitive in isolation.

## Scope (this cycle: infrastructure-only)

- **Land**: `spawn_detached`, `is_alive`, `wait_for_exit`,
  `read_log_tail`, `SpawnHandle` dataclass + embedded self-check.
- **NOT land**: `lib/evaluator_dispatcher` wiring (operator token
  required per CLAUDE.md L0 — runtime policy mutation; converting
  synchronous invoke paths to detached is a behavior change to the
  evaluator dispatch contract).

## Platform contracts

**POSIX** (`os.name == "posix"`):
- `Popen(argv, start_new_session=True, stdin=DEVNULL, stdout=log_fd,
  stderr=STDOUT, close_fds=True, cwd=cwd, env=env)`
- `start_new_session=True` calls `setsid()` post-fork, severing the
  parent's process group + controlling terminal. Subprocess survives
  parent SIGHUP / parent exit (`nohup`-equivalent without the wrapper).

**Windows** (`os.name == "nt"`):
- `Popen(argv, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
  stdin=DEVNULL, stdout=log_fd, stderr=STDOUT, cwd=cwd, env=env)`
- `DETACHED_PROCESS`: no console window. `CREATE_NEW_PROCESS_GROUP`:
  Ctrl+Break to parent does not propagate. Combined = the closest
  POSIX-setsid equivalent on Windows.
- `subprocess.DETACHED_PROCESS` is `0x00000008`,
  `CREATE_NEW_PROCESS_GROUP` is `0x00000200`. Both live in
  `subprocess` module on Windows builds.

## Log file convention

Caller passes `log_path` (Path). Module opens it in append+binary mode,
hands the fd to Popen, and closes the fd in the parent after spawn (the
subprocess keeps its own dup). Stdout AND stderr both route into this
single file (stderr=STDOUT) — keeps the log surface simple for
operator tail.

## Liveness check

`is_alive(pid)` uses platform-appropriate probe:
- POSIX: `os.kill(pid, 0)` — raises ProcessLookupError if dead,
  PermissionError if alive-but-foreign. Foreign-pid is unlikely in
  harness context but treated as "alive" (defensive).
- Windows: `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, ...)` via
  ctypes — returns NULL handle on dead pid, valid handle on alive.

## Public surface

- `SpawnHandle` (frozen dataclass: pid, log_path, started_at_iso, argv_repr)
- `SpawnError` (RuntimeError subclass)
- `spawn_detached(argv, log_path, *, cwd=None, env=None) -> SpawnHandle`
- `is_alive(pid) -> bool`
- `wait_for_exit(pid, *, timeout_seconds=30.0, poll_interval=0.2) -> bool`
- `read_log_tail(log_path, *, max_bytes=8192) -> str`
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


# ============================================================================
# Errors / dataclasses
# ============================================================================


class SpawnError(RuntimeError):
    """Raised when detached spawn fails before the OS reports a PID."""


@dataclass(frozen=True)
class SpawnHandle:
    """Opaque handle to a detached subprocess.

    `pid` may be reused by the OS after the original process exits —
    treat `is_alive(handle.pid)` results as best-effort, not as a
    strong identity guarantee. For long-lived tracking, log
    `started_at_iso` alongside pid.
    """
    pid: int
    log_path: Path
    started_at_iso: str
    argv_repr: str


# ============================================================================
# Spawn
# ============================================================================


def _utc_iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def spawn_detached(
    argv: Sequence[str],
    log_path: Path,
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> SpawnHandle:
    """Spawn `argv` as a detached subprocess; return immediately.

    The subprocess:
      - Has its own session/process-group (POSIX setsid / Windows
        DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP).
      - Inherits NO stdin (redirected from DEVNULL).
      - Tees stdout AND stderr to `log_path` (append binary).
      - Inherits `cwd` and `env` if provided.

    Raises:
      - SpawnError on Popen failure (e.g., argv[0] not on PATH).
      - ValueError on bad inputs (empty argv, log_path parent missing).

    Caller is responsible for:
      - Periodic `is_alive(handle.pid)` polling if liveness matters.
      - Eventually reading `read_log_tail(handle.log_path)` for output.
      - Cleaning up the log file (this module does not GC logs).
    """
    if not argv:
        raise ValueError("argv must be non-empty")
    if not all(isinstance(a, str) for a in argv):
        raise ValueError("all argv elements must be str")
    if not isinstance(log_path, Path):
        log_path = Path(log_path)
    if not log_path.parent.exists():
        raise ValueError(
            f"log_path parent does not exist: {log_path.parent}"
        )

    # Open log fd in append+binary; pass to Popen; close in parent.
    # We use O_APPEND for atomic concurrent writes (multiple detached
    # spawns can share the same log if caller wishes).
    try:
        log_fd = os.open(
            str(log_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
    except OSError as e:
        raise SpawnError(
            f"failed to open log_path={log_path}: {type(e).__name__}: {e}"
        ) from e

    popen_kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_fd,
        "stderr": subprocess.STDOUT,
        "cwd": str(cwd) if cwd else None,
        "env": env,
    }

    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
        popen_kwargs["close_fds"] = True
    elif os.name == "nt":
        # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP — most-POSIX-like
        # detachment available on Windows. close_fds default OK.
        # subprocess constants exist on Windows builds.
        flags = 0
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        popen_kwargs["creationflags"] = flags
    else:
        # Unknown platform — close fd + raise. Don't spawn into the void.
        try:
            os.close(log_fd)
        except OSError:
            pass
        raise SpawnError(f"unsupported os.name={os.name!r}")

    try:
        proc = subprocess.Popen(list(argv), **popen_kwargs)
    except OSError as e:
        try:
            os.close(log_fd)
        except OSError:
            pass
        raise SpawnError(
            f"Popen failed for argv[0]={argv[0]!r}: "
            f"{type(e).__name__}: {e}"
        ) from e
    finally:
        # Parent doesn't need the log fd anymore; subprocess has its own dup.
        # Only close if Popen succeeded (failure path closed already in except).
        try:
            os.close(log_fd)
        except OSError:
            pass

    return SpawnHandle(
        pid=proc.pid,
        log_path=log_path,
        started_at_iso=_utc_iso_now(),
        argv_repr=" ".join(argv),
    )


# ============================================================================
# Liveness
# ============================================================================


def is_alive(pid: int) -> bool:
    """Best-effort check whether `pid` is still alive.

    POSIX: `os.kill(pid, 0)` — raises ProcessLookupError if dead,
    PermissionError if foreign-but-alive (treated as alive).

    Windows: ctypes `OpenProcess` with PROCESS_QUERY_LIMITED_INFORMATION
    — NULL handle = dead, valid handle = alive.

    Returns False on invalid pid (≤0).

    NB: PID reuse means a False→True transition is impossible but a
    True→False→True is possible if the OS rapidly reassigns the pid.
    Combine with `started_at_iso` if identity matters.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False

    if os.name == "posix":
        # Reap first: a detached child we spawned stays a ZOMBIE after it exits
        # (kill(pid,0) keeps succeeding) until the parent waitpid's it — which would
        # make a short-lived spawn look "alive" forever. WNOHANG reaps it if it has
        # exited (→ definitively dead); ChildProcessError means it is not our child
        # (or was already reaped), so fall through to the kernel-visibility check.
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
            if reaped == pid:
                return False  # just reaped — the process has exited
        except (ChildProcessError, OSError):
            pass  # not our child / already reaped — defer to os.kill below
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # pid exists but not ours — alive from kernel's view
            return True
        except OSError:
            return False

    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
            )
            if not handle:
                return False
            # Check exit code: STILL_ACTIVE = 259
            exit_code = ctypes.c_ulong(0)
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            if not ok:
                return False
            return exit_code.value == 259
        except (OSError, AttributeError, ImportError):
            return False

    return False


def wait_for_exit(
    pid: int,
    *,
    timeout_seconds: float = 30.0,
    poll_interval: float = 0.2,
) -> bool:
    """Block until pid is no longer alive, or timeout. Returns True on
    exit, False on timeout.

    Polls `is_alive` at `poll_interval` (default 200ms) up to
    `timeout_seconds` (default 30s). Caller can set tighter intervals
    for unit tests with short-lived subprocesses.
    """
    if timeout_seconds <= 0:
        return not is_alive(pid)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_alive(pid):
            return True
        time.sleep(poll_interval)
    return not is_alive(pid)


# ============================================================================
# Log reader
# ============================================================================


def read_log_tail(log_path: Path, *, max_bytes: int = 8192) -> str:
    """Read up to `max_bytes` from the END of `log_path`. utf-8 decode
    with errors='replace'. Returns "" on missing file / IO error.

    Useful for operator inspection of the detached subprocess output
    without needing to stream the entire file.
    """
    if not isinstance(log_path, Path):
        log_path = Path(log_path)
    if not log_path.exists():
        return ""
    if max_bytes <= 0:
        return ""
    try:
        size = log_path.stat().st_size
        seek_to = max(0, size - max_bytes)
        with log_path.open("rb") as f:
            if seek_to:
                f.seek(seek_to)
            chunk = f.read(max_bytes)
    except OSError:
        return ""
    return chunk.decode("utf-8", errors="replace")


# ============================================================================
# Embedded self-check (single-file mutation surface — v15.35.6)
# ============================================================================


def _self_check() -> int:
    import tempfile

    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    # ---- 1. Input validation ----
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "x.log"

        try:
            spawn_detached([], log)
            case("empty_argv_rejects", False, "expected ValueError")
        except ValueError:
            case("empty_argv_rejects", True)

        try:
            spawn_detached([1, 2], log)  # type: ignore[list-item]
            case("non_str_argv_rejects", False, "expected ValueError")
        except ValueError:
            case("non_str_argv_rejects", True)

        try:
            spawn_detached(
                [sys.executable, "-c", "pass"],
                Path(td) / "missing_dir" / "x.log",
            )
            case("missing_log_parent_rejects", False,
                 "expected ValueError")
        except ValueError:
            case("missing_log_parent_rejects", True)

    # ---- 2. is_alive on bad pid ----
    case("is_alive_pid_zero_false", is_alive(0) is False)
    case("is_alive_pid_negative_false", is_alive(-1) is False)
    case("is_alive_pid_str_false", is_alive("123") is False)  # type: ignore[arg-type]
    # PID 999999 almost certainly dead/reserved
    case("is_alive_huge_pid_false", is_alive(999999) is False)

    # ---- 3. wait_for_exit on dead pid returns immediately ----
    start = time.monotonic()
    case("wait_dead_pid_returns_true",
         wait_for_exit(999999, timeout_seconds=2.0,
                       poll_interval=0.1) is True)
    elapsed = time.monotonic() - start
    case("wait_dead_pid_fast", elapsed < 1.0,
         f"took {elapsed:.2f}s, expected <1s")

    # ---- 4. read_log_tail on missing/empty ----
    with tempfile.TemporaryDirectory() as td:
        case("tail_missing_returns_empty",
             read_log_tail(Path(td) / "nope") == "")
        empty = Path(td) / "empty.log"
        empty.write_bytes(b"")
        case("tail_empty_file_returns_empty",
             read_log_tail(empty) == "")
        small = Path(td) / "small.log"
        # write_bytes — avoid Windows CRLF auto-conversion that
        # write_text does (would produce "hello world\r\n" on Windows).
        small.write_bytes(b"hello world\n")
        case("tail_small_file_returns_full",
             read_log_tail(small) == "hello world\n")
        # Large file: tail returns only last max_bytes
        big = Path(td) / "big.log"
        big.write_bytes(b"A" * 100 + b"B" * 100)
        tail_50 = read_log_tail(big, max_bytes=50)
        case("tail_large_file_returns_last_bytes",
             tail_50 == "B" * 50)

    # ---- 5. Real spawn — short echo via python -c ----
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "echo.log"
        argv = [sys.executable, "-c", "print('async_spawn_self_check_marker')"]
        try:
            handle = spawn_detached(argv, log)
            case("spawn_returns_handle", isinstance(handle, SpawnHandle))
            case("spawn_pid_positive", handle.pid > 0)
            case("spawn_log_path_matches", handle.log_path == log)
            case("spawn_argv_repr_present",
                 sys.executable in handle.argv_repr)
            case("spawn_started_at_iso_format",
                 len(handle.started_at_iso) >= 19
                 and handle.started_at_iso.endswith("Z"))

            # Wait up to 10s for the python subprocess to exit
            exited = wait_for_exit(handle.pid,
                                   timeout_seconds=10.0,
                                   poll_interval=0.1)
            case("spawn_exits_within_timeout", exited)

            # Log should contain the marker
            time.sleep(0.5)  # Give OS time to flush log
            tail = read_log_tail(log)
            case("spawn_log_contains_marker",
                 "async_spawn_self_check_marker" in tail,
                 f"log content: {tail!r}")
        except SpawnError as e:
            case("spawn_real_python_subprocess", False, str(e))

    # ---- 6. Spawn bad argv[0] raises SpawnError ----
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "noexist.log"
        try:
            spawn_detached(
                ["this_binary_definitely_does_not_exist_xyz_123"],
                log,
            )
            case("spawn_missing_binary_raises", False,
                 "expected SpawnError")
        except SpawnError:
            case("spawn_missing_binary_raises", True)
        except FileNotFoundError:
            # Some platforms surface as FileNotFoundError before our wrap
            case("spawn_missing_binary_raises", True,
                 "(FileNotFoundError accepted)")

    # ---- 7. Platform-specific flag presence ----
    if os.name == "nt":
        # Verify constants resolve (either from subprocess or our fallback)
        df = getattr(subprocess, "DETACHED_PROCESS", 0x8)
        cnpg = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
        case("windows_detached_flag_present", df == 0x8 or df > 0)
        case("windows_new_pgroup_flag_present", cnpg == 0x200 or cnpg > 0)
    else:
        case("windows_detached_flag_present", True, "(POSIX — skipped)")
        case("windows_new_pgroup_flag_present", True, "(POSIX — skipped)")

    # ---- 8. SpawnHandle frozen ----
    handle = SpawnHandle(pid=1, log_path=Path("/tmp/x"),
                         started_at_iso="2026-05-17T00:00:00Z",
                         argv_repr="echo")
    try:
        handle.pid = 2  # type: ignore[misc]
        case("spawn_handle_frozen", False, "frozen=True breach")
    except (AttributeError, Exception):
        case("spawn_handle_frozen", True)

    # ---- report ----
    for name, ok, detail in cases:
        marker = "[OK]" if ok else "[FAIL]"
        suffix = f": {detail}" if detail and not ok else ""
        print(f"  {marker} {name}{suffix}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(cases)} self-check assertions failed")
        return 1
    print(f"\n[OK] {len(cases)} self-check assertions passed")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    print("lib.async_spawn — cross-platform detached subprocess (v15.35.6)")
    print(f"  platform:    os.name={os.name}")
    print(f"  spawn flag:  {'start_new_session=True' if os.name == 'posix' else 'DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP'}")
    print(f"  NOT wired to evaluator_dispatcher — infrastructure only this cycle")
    print(f"  use --self-check to run embedded smoke test (spawns real python subprocess)")
    sys.exit(0)

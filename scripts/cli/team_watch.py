#!/usr/bin/env python3
"""Live TUI dashboard for harness-team multi-worker sessions.

Watches `<session_dir>/worker-*.out` files and renders a single-page dashboard
with per-worker status (DONE / RUNNING / IDLE / FAILED), recent log tail, and
elapsed time. Replaces / complements the psmux 4-pane layout from view-setup.sh
when a single integrated view is preferred.

Usage:
    python -m cli.team_watch                    # auto-detect latest team session
    python -m cli.team_watch team-1777259068    # bare session id (under ~/.omc/team/)
    python -m cli.team_watch /path/to/session   # absolute path
    python -m cli.team_watch --once             # render once and exit (CI-friendly)

Exit codes:
    0 — clean exit (Ctrl+C, all DONE, or --once with no FAIL)
    1 — at least one worker FAILED at exit time

Status detection (per worker-N.out):
    not_started: file missing
    done:        last 64 bytes contain b"DONE"
    failed:      last 8KB contain failure tokens (Traceback, [FAIL], [ERROR])
    running:     mtime within RUNNING_WINDOW_SEC (default 10s)
    idle:        otherwise (file exists but no recent activity)

Layout (auto-grid sized by worker count):
    1 worker  → single column
    2 workers → 1×2
    3-4       → 2×2
    5-6       → 2×3
    7-9       → 3×3
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Make sibling lib/ importable for path constants
_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

DEFAULT_TEAM_ROOT = Path.home() / ".omc" / "team"
RUNNING_WINDOW_SEC = 10.0
TAIL_BYTES = 8192        # bytes to read from end for status + display
TAIL_LINES = 12          # lines to display per panel
REFRESH_HZ = 2           # 2 frames/sec

DONE_RE = re.compile(rb"\bDONE\b")
FAIL_RE = re.compile(rb"\[FAIL\]|\[ERROR\]|^Traceback", re.MULTILINE)

STATUS_STYLES = {
    "DONE":        ("bold green",   "[v]"),
    "RUNNING":     ("bold yellow",  "[~]"),
    "IDLE":        ("bold blue",    "[.]"),
    "FAILED":      ("bold red",     "[x]"),
    "NOT_STARTED": ("dim",          "[ ]"),
}


@dataclass
class WorkerState:
    name: str
    path: Path
    status: str
    last_lines: list[str]
    mtime: float | None
    size: int
    # W19.1.1+ mailbox depth (0 when /harness-team is standalone — mailbox
    # protocol only active when autopilot super-session drives the team).
    inbox_depth: int = 0
    outbox_depth: int = 0


def _read_tail(path: Path, n_bytes: int = TAIL_BYTES) -> bytes:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return b""
    with path.open("rb") as f:
        if size > n_bytes:
            f.seek(-n_bytes, os.SEEK_END)
        return f.read()


def _classify(path: Path) -> WorkerState:
    name = path.stem  # worker-1
    if not path.exists():
        return WorkerState(name=name, path=path, status="NOT_STARTED",
                           last_lines=[], mtime=None, size=0)

    raw = _read_tail(path)
    try:
        st = path.stat()
        mtime = st.st_mtime
        size = st.st_size
    except FileNotFoundError:
        mtime, size = None, 0

    # last lines for display
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()[-TAIL_LINES:]

    # status
    status = "IDLE"
    last64 = raw[-64:]
    if DONE_RE.search(last64):
        status = "DONE"
    elif FAIL_RE.search(raw):
        status = "FAILED"
    elif mtime is not None and (time.time() - mtime) <= RUNNING_WINDOW_SEC:
        status = "RUNNING"

    return WorkerState(name=name, path=path, status=status,
                       last_lines=lines, mtime=mtime, size=size,
                       inbox_depth=_safe_mailbox_depth(path.parent.name, name, "inbox"),
                       outbox_depth=_safe_mailbox_depth(path.parent.name, name, "outbox"))


def _safe_mailbox_depth(sid: str, worker_filename: str, side: str) -> int:
    """Probe state/team/<sid>/mailbox/ for mailbox depth (W19.1.1+).

    Returns 0 silently if the mailbox dir is absent — mailbox protocol is
    only active when /harness-autopilot drives the team. Standalone
    /harness-team has no mailbox; the panel just shows 0.
    """
    try:
        from lib.team_mailbox import mailbox_depth
        # worker_filename is "worker-N.out" -> worker_id is "worker-N"
        worker_id = worker_filename.rsplit(".", 1)[0] if "." in worker_filename else worker_filename
        return mailbox_depth(sid, worker_id, side=side)
    except Exception:
        return 0


def _resolve_session(arg: str | None) -> Path:
    """Resolve session id / path / auto-latest into a directory."""
    if arg:
        p = Path(arg).expanduser()
        if p.is_dir():
            return p.resolve()
        # bare session id under DEFAULT_TEAM_ROOT
        candidate = DEFAULT_TEAM_ROOT / arg
        if candidate.is_dir():
            return candidate.resolve()
        raise SystemExit(f"[team_watch] session not found: {arg!r}")

    if not DEFAULT_TEAM_ROOT.is_dir():
        raise SystemExit(f"[team_watch] no team sessions under {DEFAULT_TEAM_ROOT}")
    sessions = sorted(
        (p for p in DEFAULT_TEAM_ROOT.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not sessions:
        raise SystemExit(f"[team_watch] no team sessions under {DEFAULT_TEAM_ROOT}")
    return sessions[0].resolve()


def _discover_workers(session_dir: Path) -> list[Path]:
    return sorted(session_dir.glob("worker-*.out"), key=lambda p: p.name)


def _grid_dims(n: int) -> tuple[int, int]:
    """Return (rows, cols) for an N-panel grid."""
    if n <= 1:
        return (1, 1)
    if n == 2:
        return (1, 2)
    if n <= 4:
        return (2, 2)
    if n <= 6:
        return (2, 3)
    return (3, 3)


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _render_header(session_dir: Path, states: list[WorkerState], started: float) -> Panel:
    counts = {k: 0 for k in STATUS_STYLES}
    for s in states:
        counts[s.status] = counts.get(s.status, 0) + 1

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(justify="left", ratio=2)
    table.add_column(justify="right", ratio=3)

    left = Text()
    left.append("session ", style="dim")
    left.append(session_dir.name, style="bold")
    left.append("  ")
    left.append(_format_elapsed(time.time() - started), style="cyan")

    right = Text()
    for status in ("DONE", "RUNNING", "IDLE", "FAILED", "NOT_STARTED"):
        n = counts.get(status, 0)
        if n == 0 and status not in ("DONE", "RUNNING"):
            continue
        style, glyph = STATUS_STYLES[status]
        right.append(f"{glyph} {status} {n}  ", style=style)

    table.add_row(left, right)
    return Panel(table, title="harness-team watch", border_style="blue")


def _render_worker_panel(state: WorkerState) -> Panel:
    style, glyph = STATUS_STYLES[state.status]
    title = Text()
    title.append(f"{glyph} {state.name} ", style=style)
    title.append(f"[{state.status}]", style=f"{style} dim")

    body = Text()
    if state.status == "NOT_STARTED":
        body.append("(no output file yet)", style="dim italic")
    else:
        for ln in state.last_lines:
            ln_clean = ln.rstrip()
            line_style = ""
            if FAIL_RE.search(ln_clean.encode("utf-8", "replace")):
                line_style = "red"
            elif "[PASS]" in ln_clean or "DONE" in ln_clean:
                line_style = "green"
            elif "[WARN]" in ln_clean:
                line_style = "yellow"
            body.append(ln_clean[:200] + "\n", style=line_style)
        if not state.last_lines:
            body.append("(file empty)", style="dim italic")

        if state.mtime is not None:
            body.append(f"\nlast write: {_format_elapsed(time.time() - state.mtime)} ago • {state.size:,} B",
                        style="dim")

        # W19.1.1+ mailbox indicator — only show when there is traffic
        if state.inbox_depth > 0 or state.outbox_depth > 0:
            body.append(
                f"\nmailbox: in={state.inbox_depth} out={state.outbox_depth}",
                style="cyan",
            )

    border = "red" if state.status == "FAILED" else (
        "green" if state.status == "DONE" else (
            "yellow" if state.status == "RUNNING" else "blue"
        )
    )
    return Panel(body, title=title, border_style=border)


def _build_layout(session_dir: Path, started: float) -> tuple[Layout, list[Path]]:
    workers = _discover_workers(session_dir)
    if not workers:
        raise SystemExit(f"[team_watch] no worker-*.out files in {session_dir}")
    rows, cols = _grid_dims(len(workers))

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )
    layout["body"].split_column(*[Layout(name=f"row{r}") for r in range(rows)])
    for r in range(rows):
        layout["body"][f"row{r}"].split_row(
            *[Layout(name=f"r{r}c{c}") for c in range(cols)]
        )

    return layout, workers


def _refresh(layout: Layout, session_dir: Path, workers: list[Path], started: float) -> list[WorkerState]:
    states = [_classify(p) for p in workers]
    layout["header"].update(_render_header(session_dir, states, started))
    rows, cols = _grid_dims(len(workers))

    idx = 0
    for r in range(rows):
        for c in range(cols):
            cell = layout["body"][f"row{r}"][f"r{r}c{c}"]
            if idx < len(workers):
                cell.update(_render_worker_panel(states[idx]))
            else:
                cell.update(Panel(Text("(empty slot)", style="dim italic"),
                                  border_style="dim"))
            idx += 1
    return states


def _all_done(states: list[WorkerState]) -> bool:
    return all(s.status in ("DONE", "FAILED") for s in states) and \
        any(s.status == "DONE" for s in states)


def _exit_code(states: list[WorkerState]) -> int:
    return 1 if any(s.status == "FAILED" for s in states) else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Live dashboard for harness-team workers")
    p.add_argument("session", nargs="?", help="session id or path (default: latest under ~/.omc/team)")
    p.add_argument("--once", action="store_true", help="render one frame and exit (CI/snapshot)")
    p.add_argument("--exit-on-done", action="store_true",
                   help="exit when all workers are DONE or FAILED")
    args = p.parse_args(argv)

    session_dir = _resolve_session(args.session)
    started = time.time()
    layout, workers = _build_layout(session_dir, started)
    # Force UTF-8 friendly behavior on legacy Windows consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    console = Console(legacy_windows=False)

    if args.once:
        states = _refresh(layout, session_dir, workers, started)
        console.print(layout)
        return _exit_code(states)

    last_states: list[WorkerState] = []
    try:
        with Live(layout, console=console, refresh_per_second=REFRESH_HZ, screen=True):
            while True:
                last_states = _refresh(layout, session_dir, workers, started)
                if args.exit_on_done and _all_done(last_states):
                    break
                time.sleep(1.0 / REFRESH_HZ)
    except KeyboardInterrupt:
        pass

    return _exit_code(last_states) if last_states else 0


if __name__ == "__main__":
    sys.exit(main())

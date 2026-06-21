#!/usr/bin/env python3
"""Status line renderer — original context-bar + harness-specific metrics.

Combines the original context-bar.sh functionality (model, cwd, git branch,
uncommitted file count, context window %) with harness-specific signals:
  - Active debate session         (state/debates/<sid>/events.jsonl)
  - Recent telemetry warnings     (debate-triggers, shim-hits in last 5 min)

Reads Claude Code's statusLine JSON payload from stdin, prints ONE colored
line to stdout. Degrades gracefully — if any source is missing, the affected
segment is skipped, never an exception.

Theme: light-daltonized (blue accent, consistent with settings.json.theme).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure lib/ is importable (sibling dir)
_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import STATE_DIR, TELEMETRY_DIR  # noqa: E402


# ANSI color — light-daltonized blue accent (matches context-bar.sh COLOR=blue)
RESET = "\033[0m"
GRAY = "\033[38;5;245m"
BAR_EMPTY = "\033[38;5;238m"
ACCENT = "\033[38;5;74m"

BASELINE_TOKENS = 20_000    # system prompt + tools + memory (matches sh implementation)
BAR_WIDTH = 10
WARN_WINDOW_SEC = 300       # 5-minute rolling window for warning counter
GIT_TIMEOUT = 3.0


def _read_stdin_json() -> dict:
    try:
        return json.loads(sys.stdin.read())
    except Exception:
        return {}


def _git(cwd: str, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True, text=True, encoding="utf-8", timeout=GIT_TIMEOUT,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _git_info(cwd: str) -> tuple[str, str]:
    """Return (branch, '(N files uncommitted, sync_state)') or ('', '')."""
    if not cwd or not os.path.isdir(cwd):
        return "", ""
    branch = _git(cwd, "branch", "--show-current")
    if not branch:
        return "", ""

    porcelain = _git(cwd, "--no-optional-locks", "status", "--porcelain", "-uno")
    lines = [ln for ln in porcelain.splitlines() if ln.strip()]
    file_count = len(lines)

    sync = "no upstream"
    upstream = _git(cwd, "rev-parse", "--abbrev-ref", "@{upstream}")
    if upstream:
        counts = _git(cwd, "rev-list", "--left-right", "--count", "HEAD...@{upstream}").split()
        if len(counts) == 2:
            try:
                ahead, behind = int(counts[0]), int(counts[1])
            except ValueError:
                ahead = behind = 0
            if ahead == 0 and behind == 0:
                sync = "synced"
            elif ahead and not behind:
                sync = f"{ahead} ahead"
            elif behind and not ahead:
                sync = f"{behind} behind"
            else:
                sync = f"{ahead} ahead, {behind} behind"

    if file_count == 0:
        status = f"(0 files uncommitted, {sync})"
    elif file_count == 1:
        single = lines[0][3:] if len(lines[0]) > 3 else lines[0]
        status = f"({single} uncommitted, {sync})"
    else:
        status = f"({file_count} files uncommitted, {sync})"

    return branch, status


def _context_bar(transcript_path: str, max_context: int) -> str:
    """Render the 10-cell context-window bar plus percentage label."""
    max_k = max(1, max_context // 1000)
    tokens = 0
    prefix = ""

    if transcript_path and os.path.isfile(transcript_path):
        try:
            last_usage = None
            with open(transcript_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if ev.get("isSidechain") or ev.get("isApiErrorMessage"):
                        continue
                    usage = (ev.get("message") or {}).get("usage")
                    if usage:
                        last_usage = usage
            if last_usage:
                tokens = (
                    int(last_usage.get("input_tokens") or 0)
                    + int(last_usage.get("cache_read_input_tokens") or 0)
                    + int(last_usage.get("cache_creation_input_tokens") or 0)
                )
        except Exception:
            pass

    if tokens <= 0:
        tokens = BASELINE_TOKENS
        prefix = "~"

    pct = min(100, tokens * 100 // max_context) if max_context > 0 else 0

    chunks: list[str] = []
    for i in range(BAR_WIDTH):
        progress = pct - i * 10
        if progress >= 8:
            chunks.append(f"{ACCENT}█{RESET}")
        elif progress >= 3:
            chunks.append(f"{ACCENT}▄{RESET}")
        else:
            chunks.append(f"{BAR_EMPTY}░{RESET}")
    return f"{''.join(chunks)} {GRAY}{prefix}{pct}% of {max_k}k tokens{RESET}"


def _active_debate() -> str | None:
    """Return 'gen<N>' for the most recent non-converged debate, else None."""
    marker = STATE_DIR / "current-debate-session"
    if not marker.is_file():
        return None
    try:
        sid = marker.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not sid:
        return None
    events_path = STATE_DIR / "debates" / sid / "events.jsonl"
    if not events_path.is_file():
        return None
    try:
        last_event = None
        latest_gen = 0
        with events_path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                last_event = ev
                gen = ev.get("gen")
                if isinstance(gen, int) and gen > latest_gen:
                    latest_gen = gen
        if not last_event:
            return None
        if (
            last_event.get("type") == "convergence"
            and (last_event.get("payload") or {}).get("converged")
        ):
            return None
        return f"gen{latest_gen}" if latest_gen else None
    except Exception:
        return None


def _recent_warnings(window_seconds: int = WARN_WINDOW_SEC) -> int:
    """Count telemetry events in the rolling window across tracked files."""
    tracked = (
        TELEMETRY_DIR / "debate-triggers.jsonl",
        TELEMETRY_DIR / "shim-hits.jsonl",  # coherence-ok: written by scripts/*-check.py + context-loader.py shims via direct path append, not log_telemetry
        TELEMETRY_DIR / "learner-candidates.jsonl",
    )
    cutoff = time.time() - window_seconds
    total = 0
    for p in tracked:
        if not p.is_file():
            continue
        try:
            with p.open(encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    ts = ev.get("ts", "")
                    if len(ts) < 19:
                        continue
                    try:
                        t = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                    except Exception:
                        continue
                    if t >= cutoff:
                        total += 1
        except Exception:
            continue
    return total


def _render(payload: dict) -> str:
    model = (
        (payload.get("model") or {}).get("display_name")
        or (payload.get("model") or {}).get("id")
        or "?"
    )
    cwd = payload.get("cwd") or ""
    dirname = os.path.basename(cwd) if cwd else "?"
    transcript = payload.get("transcript_path") or ""
    max_context = int(
        (payload.get("context_window") or {}).get("context_window_size") or 200_000
    )

    branch, git_status = _git_info(cwd)
    ctx = _context_bar(transcript, max_context)
    debate = _active_debate()
    warn_count = _recent_warnings()

    parts: list[str] = [f"{ACCENT}{model}{GRAY} 📁{dirname}"]
    if branch:
        parts.append(f"🔀{branch} {git_status}")
    if debate:
        parts.append(f"⚖ {debate}")
    if warn_count > 0:
        parts.append(f"⚠ {warn_count}")
    parts.append(ctx)
    return f"{GRAY} | {RESET}".join(parts) + RESET


def main() -> int:
    # Windows cp949 stdout cannot encode emojis / box chars — force utf-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        payload = _read_stdin_json()
        print(_render(payload))
    except Exception as e:  # guard: never crash the statusLine
        print(f"{GRAY}hud error: {type(e).__name__}{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""harness_bridge_state_block — D5+D5a kha↔harness composition bridge validator.

Source: debate-1779314852-338b28 converged path (4-LOCK byte-identical
gen2→gen3 sha1 dc809a9257f23c472212ce55d426fdccb039624b).

Enforces D5: the ``## Harness Bridge`` subsection inside
``.planning/STATE.md`` is append-only (no historical bullet deletions or
in-place modifications). Per gen-3 condition (Critic B2 sustained), scope
is the SUBSECTION ONLY — entire-file enforcement would conflict with
kha-executor's gsd-tools.cjs state advance-plan/update-progress in-place
mutations on other STATE.md sections (kha-executor.md:461-507).

Per gen-3 condition (Critic S2 promoted), cache miss with non-trivial
history surfaces as FAIL not WARN — operator must explicitly bootstrap
to avoid silent correctness regression on long-history monorepos.

D5a scope:
  - monorepo root only — git -C <repo_root> log over .planning/STATE.md
  - submodules out-of-scope (per-submodule STATE.md owned by sub-session)
  - cache pointer at state/validators/harness_bridge_state_block/last_seen_sha.txt

Bullet format (LOCK):
  - <ISO8601>Z | phase=X.Y | plan=<id> | autopilot_sid=<sid>

Invariants:
  - bullets monotonically non-decreasing by timestamp
  - no duplicate (phase, plan, sid) triple
  - historical bullets present in current section (append-only)

Caller contract (validators/__init__.py):
  - main() -> None, no args; reads os.getcwd() as project root
  - prints [PASS]/[FAIL] lines to stdout; never raises
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdin, sys.stdout):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        try:
            _reconfigure(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import STATE_DIR  # noqa: E402

# Cache pointer location — single-line file holding the SHA of the last
# git commit on .planning/STATE.md that was verified clean.
_CACHE_DIR: Path = STATE_DIR / "validators" / "harness_bridge_state_block"
_CACHE_PATH: Path = _CACHE_DIR / "last_seen_sha.txt"

# Cache-miss fail-fast threshold. If the cache is missing AND the STATE.md
# git history has more touching commits than this, we FAIL rather than
# silently scan a partial window (gen-3 condition S2 — promoted from
# Critic soft concern to Architect condition).
_CACHE_MISS_FAIL_THRESHOLD: int = 50

# Header literal — matches Markdown heading line ``## Harness Bridge``.
_SECTION_HEADER = "## Harness Bridge"

# Bullet line shape:
#   - 2026-05-21T07:30:00Z | phase=8.3 | plan=01-foo | autopilot_sid=debate-...
_BULLET_RE = re.compile(
    r"^- "
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) \| "
    r"phase=(?P<phase>[1-9]\d*\.(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))?) \| "
    r"plan=(?P<plan>[^|]+?) \| "
    r"autopilot_sid=(?P<sid>\S+)\s*$"
)


def _extract_bridge_section(text: str) -> list[str] | None:
    """Return bullet lines under `## Harness Bridge`, or None if absent.

    The section ends at the next ``## `` heading or EOF. Blank lines and
    non-bullet lines inside the section are ignored (caller's discipline,
    not validator's concern). Returns empty list when the section header
    exists but contains no bullets yet (PASS-eligible empty state).
    """
    lines = text.splitlines()
    in_section = False
    bullets: list[str] = []
    for ln in lines:
        if ln.strip() == _SECTION_HEADER:
            in_section = True
            continue
        if in_section:
            if ln.startswith("## "):
                # Next sibling heading — section ended.
                break
            stripped = ln.rstrip()
            if stripped.startswith("- "):
                bullets.append(stripped)
    if not in_section:
        return None
    return bullets


def _validate_format(bullets: list[str]) -> tuple[bool, str]:
    for i, b in enumerate(bullets):
        if not _BULLET_RE.match(b):
            return False, f"bullet {i+1} fails format: {b!r}"
    return True, ""


def _validate_monotonic(bullets: list[str]) -> tuple[bool, str]:
    prev_ts = ""
    for i, b in enumerate(bullets):
        m = _BULLET_RE.match(b)
        if not m:
            continue  # format check catches; defensive
        ts = m.group("ts")
        if prev_ts and ts < prev_ts:
            return False, (
                f"bullet {i+1} timestamp {ts} precedes previous {prev_ts}"
            )
        prev_ts = ts
    return True, ""


def _validate_no_dups(bullets: list[str]) -> tuple[bool, str]:
    seen: set[tuple[str, str, str]] = set()
    for i, b in enumerate(bullets):
        m = _BULLET_RE.match(b)
        if not m:
            continue
        key = (m.group("phase"), m.group("plan"), m.group("sid"))
        if key in seen:
            return False, (
                f"bullet {i+1} duplicates (phase, plan, sid)={key}"
            )
        seen.add(key)
    return True, ""


def _git(repo_root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _commits_touching(repo_root: Path, state_rel: str) -> list[str]:
    """Return commit SHAs (newest first) that touched .planning/STATE.md."""
    rc, out = _git(
        repo_root,
        "log",
        "--follow",
        "--pretty=format:%H",
        "--",
        state_rel,
    )
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def _state_md_at(repo_root: Path, sha: str, state_rel: str) -> str | None:
    rc, out = _git(repo_root, "show", f"{sha}:{state_rel}")
    if rc != 0:
        return None
    return out


def _read_cache() -> str | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        return _CACHE_PATH.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_cache(sha: str) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(sha + "\n", encoding="utf-8")


def _verify_append_only_against_history(
    repo_root: Path,
    state_rel: str,
    current_bullets: list[str],
    since_sha: str | None,
) -> tuple[bool, str, str | None]:
    """Walk history, ensure every historical bullet is present in current.

    Returns (ok, detail, latest_sha_walked).
    """
    commits = _commits_touching(repo_root, state_rel)
    if not commits:
        return True, "no STATE.md commits", None

    latest_sha = commits[0]

    if since_sha is None:
        # Cache miss — fail-fast if history exceeds threshold.
        if len(commits) > _CACHE_MISS_FAIL_THRESHOLD:
            return (
                False,
                (
                    f"cache miss with {len(commits)} commits touching STATE.md "
                    f"(> {_CACHE_MISS_FAIL_THRESHOLD}). Manual review required. "
                    f"After review, bootstrap via: echo {latest_sha} > "
                    f"state/validators/harness_bridge_state_block/last_seen_sha.txt"
                ),
                None,
            )
        history_slice = commits
    else:
        # Delta walk — only commits newer than cached SHA.
        if since_sha == latest_sha:
            return True, f"delta empty (HEAD={latest_sha[:8]} == cache)", latest_sha
        if since_sha not in commits:
            return (
                False,
                (
                    f"cached SHA {since_sha[:8]} not in STATE.md history — "
                    f"force-push or history rewrite detected"
                ),
                None,
            )
        cache_idx = commits.index(since_sha)
        history_slice = commits[:cache_idx]

    current_set = set(current_bullets)
    for sha in history_slice:
        hist_text = _state_md_at(repo_root, sha, state_rel)
        if hist_text is None:
            continue
        hist_bullets = _extract_bridge_section(hist_text)
        if not hist_bullets:
            continue
        for hb in hist_bullets:
            if hb not in current_set:
                return (
                    False,
                    (
                        f"bullet from {sha[:8]} no longer in current section: "
                        f"{hb!r} (append-only invariant violated)"
                    ),
                    None,
                )
    return True, f"walked {len(history_slice)} commits", latest_sha


def main() -> None:
    project_root = Path(os.getcwd())
    state_md = project_root / ".planning" / "STATE.md"
    if not state_md.exists():
        print("[PASS] no .planning/STATE.md (non-GSD project; bridge inactive)")
        return

    try:
        text = state_md.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[FAIL] cannot read {state_md}: {e}")
        return

    bullets = _extract_bridge_section(text)
    if bullets is None:
        print(
            "[PASS] STATE.md has no `## Harness Bridge` section "
            "(bridge not yet activated)"
        )
        return
    if not bullets:
        print(
            "[PASS] `## Harness Bridge` section present but empty "
            "(no bridge dispatches recorded)"
        )
        # Cache HEAD even with empty section so subsequent runs are delta-only.
        rc, out = _git(project_root, "rev-parse", "HEAD")
        if rc == 0 and out.strip():
            _write_cache(out.strip())
        return

    ok, detail = _validate_format(bullets)
    if not ok:
        print(f"[FAIL] format: {detail}")
        return
    ok, detail = _validate_monotonic(bullets)
    if not ok:
        print(f"[FAIL] monotonic: {detail}")
        return
    ok, detail = _validate_no_dups(bullets)
    if not ok:
        print(f"[FAIL] dedup: {detail}")
        return

    cache_sha = _read_cache()
    ok, detail, latest = _verify_append_only_against_history(
        project_root,
        ".planning/STATE.md",
        bullets,
        cache_sha,
    )
    if not ok:
        print(f"[FAIL] append-only history check: {detail}")
        return
    if latest:
        _write_cache(latest)
    print(
        f"[PASS] `## Harness Bridge` section: {len(bullets)} bullets, "
        f"format+monotonic+dedup+append-only OK ({detail})"
    )


if __name__ == "__main__":
    main()

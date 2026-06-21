"""claim_verifier — ADVISORY validator: commit-hash claims in governing docs.

Track 1 (harness-debate debate-1780722434-e5h19n gen-2, D3/C4). The governing
docs (HANDOFF / CLAUDE / HARNESS-GUIDE / ROADMAP) repeatedly claim work "landed"
at a commit hash. A dangling/orphan hash = self-model drift: the doc asserts a
state git cannot confirm. This validator resolves such claims against the
*bound* repository and WARNs when they do not resolve.

LOCKED contract (D3/C4):
- ADVISORY-ONLY: WARN-only, main()->0, NOT in VALIDATOR_NAMES, NOT
  graduation-eligible this generation (attribution false-negative rate is
  unproven — most real hashes in these docs are 7-hex short hashes BELOW the
  collision-safe threshold, so coverage is deliberately partial).
- Per-hash repo-binding: each candidate hash is bound to exactly ONE repo via
  its surrounding-text cue, then resolved ONLY in that repo. Never any-match
  across the repo map (that would be a silent false-attribution).
- min 12-hex: only `[0-9a-f]{12,40}` candidates are resolved (git accepts
  abbreviated prefixes; <12 hex risks collision false-positives). Shorter
  backtick hex tokens are COUNTED as below-threshold-skipped (honest FN
  surface) but NOT resolved.
- Resolution is read-only: `git -C <repo> cat-file -e <hash>^{commit}`.
  unmapped / unbound / absent-repo / git-missing => WARN 'unverifiable'
  (NEVER a silent pass). repo-present-but-hash-absent => WARN 'dangling'.
- Fully fail-soft (a missing repo or git binary never raises).

Run:
    python -m validators.claim_verifier
Exit code: 0 always (advisory).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import CLAUDE_HOME  # noqa: E402

_HOME = CLAUDE_HOME            # ~/.claude (its own git repo)
_USER = CLAUDE_HOME.parent     # /home/user (home scoped repo: CLAUDE.md)

# Repo map (key → working tree root). Each is git-resolved independently.
REPO_MAP: dict[str, Path] = {
    "claude-home": _HOME,
    "home": _USER,
    "example_project": _USER / "example_project-analysis",
}

# Docs that make hash claims, with the repo the doc itself lives in (default
# binding when no in-text cue picks a different repo).
def _doc_targets() -> list[tuple[Path, str]]:
    return [
        (_USER / "example_project-analysis" / "HANDOFF.md", "example_project"),
        (_USER / "example_project-analysis" / "PRODUCT-GRADE-ROADMAP.md", "example_project"),
        (_USER / "CLAUDE.md", "home"),
        (_HOME / "HARNESS-GUIDE.md", "claude-home"),
        (_HOME / "HANDOFF.md", "claude-home"),
    ]

MIN_HEX = 12
# Candidate hash inside backticks (the docs always backtick-wrap hashes).
_BACKTICK_HEX_RE = re.compile(r"`([0-9a-f]{7,40})`")
# Repo cues — searched in a window around each candidate; first match wins by
# proximity. Ordered most-specific first.
_CUES: list[tuple[str, str]] = [
    ("example_project", "example_project"),
    ("~/.claude", "claude-home"),
    ("scripts/", "claude-home"),
    ("validators/", "claude-home"),
    ("handlers/", "claude-home"),
    ("lib/", "claude-home"),
    ("cli/", "claude-home"),
    ("engine/", "claude-home"),
    ("agents/", "claude-home"),
    ("atlas/", "claude-home"),
    ("/home/user", "home"),
    ("home scoped", "home"),
    ("scoped repo", "home"),
]
_WINDOW = 90  # chars on each side of the hash searched for a cue


def _bind_repo(text: str, start: int, end: int, default_key: str) -> str:
    """Bind a hash at [start:end) to a repo key via the nearest surrounding cue;
    fall back to the doc's own repo (default_key). Proximity = min distance from
    the hash to the cue occurrence within the window."""
    lo = max(0, start - _WINDOW)
    hi = min(len(text), end + _WINDOW)
    window = text[lo:hi].lower()
    hash_pos = start - lo
    best_key = default_key
    best_dist = 10 ** 9
    for needle, key in _CUES:
        idx = window.find(needle)
        while idx != -1:
            dist = abs(idx - hash_pos)
            if dist < best_dist:
                best_dist, best_key = dist, key
            idx = window.find(needle, idx + 1)
    return best_key


# "hash-context-cued" gate (D3 scope): a >=12-hex token is treated as a COMMIT
# claim only when its window carries a commit cue AND no snapshot/lock cue. This
# excludes the many 40-hex debate-snapshot SHA-1s / insight-index LOCK hashes /
# fingerprints that are NOT git commits (the dominant false-positive class).
_COMMIT_CUES: tuple[str, ...] = (
    "commit", "origin/", "master", "branch", "rebase", "cherry-pick",
    "push", "atomic", "->`", "-> `", "pr #", "land", "→`", "→ `", "merge",
)
_SNAPSHOT_CUES: tuple[str, ...] = (
    "sha1", "sha-1", "sha 1", "snapshot", "ontology", "lock", "fingerprint",
    "hexdigest", "correlation", "converged", "convergence", "insight-index",
)


def _is_commit_context(window: str) -> bool:
    if any(c in window for c in _SNAPSHOT_CUES):
        return False
    return any(c in window for c in _COMMIT_CUES)


def _git_has_commit(repo: Path, sha: str) -> str:
    """Return 'present' | 'dangling' | 'unverifiable'. Read-only, fail-soft."""
    if not (repo.is_dir() and (repo / ".git").exists()):
        return "unverifiable"
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unverifiable"
    return "present" if proc.returncode == 0 else "dangling"


def scan() -> dict:
    """Resolve every >=12-hex, commit-context-cued backtick hash claim against
    its bound repo. Returns {checked, present, dangling_warns,
    unverifiable_warns, below_threshold, non_commit_skipped}. No side effects."""
    result = {
        "checked": 0, "present": 0,
        "dangling_warns": [], "unverifiable_warns": [],
        "below_threshold": 0, "non_commit_skipped": 0,
    }
    for path, default_key in _doc_targets():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.name
        for m in _BACKTICK_HEX_RE.finditer(text):
            sha = m.group(1)
            if len(sha) < MIN_HEX:
                result["below_threshold"] += 1
                continue
            lo = max(0, m.start(1) - _WINDOW)
            hi = min(len(text), m.end(1) + _WINDOW)
            window = text[lo:hi].lower()
            if not _is_commit_context(window):
                # snapshot SHA / lock / fingerprint — not a git-commit claim (D3
                # "hash-context-cued"). Counted for honesty, NOT resolved/warned.
                result["non_commit_skipped"] += 1
                continue
            key = _bind_repo(text, m.start(1), m.end(1), default_key)
            repo = REPO_MAP.get(key)
            result["checked"] += 1
            if repo is None:
                result["unverifiable_warns"].append(
                    f"[WARN] {rel}: hash `{sha[:12]}..` bound to unknown repo {key!r} - unverifiable"
                )
                continue
            verdict = _git_has_commit(repo, sha)
            if verdict == "present":
                result["present"] += 1
            elif verdict == "dangling":
                result["dangling_warns"].append(
                    f"[WARN] {rel}: hash `{sha[:12]}..` does NOT resolve in {key} repo "
                    f"({repo}) - dangling/orphan commit claim"
                )
            else:  # unverifiable
                result["unverifiable_warns"].append(
                    f"[WARN] {rel}: hash `{sha[:12]}..` bound to {key} repo but "
                    f"repo/git absent - unverifiable (NOT a silent pass)"
                )
    return result


def main() -> int:
    r = scan()
    for w in r["dangling_warns"]:
        print(w)
    for w in r["unverifiable_warns"]:
        print(w)
    total = len(r["dangling_warns"]) + len(r["unverifiable_warns"])
    print(
        f"[PASS] claim_verifier - {r['checked']} commit-hash claims checked "
        f"({r['present']} present, {len(r['dangling_warns'])} dangling, "
        f"{len(r['unverifiable_warns'])} unverifiable; skipped "
        f"{r['below_threshold']} below-{MIN_HEX}-hex + {r['non_commit_skipped']} "
        f"non-commit-context) ({total} total, advisory)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

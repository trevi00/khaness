"""Parser for `.claude/git-flow-overrides.md` — git-flow declarative override.

Mirrors `tech-stack.yaml` pattern: a project declares its workflow shape in a
single markdown file with `key: value` lines INSIDE a `---` frontmatter fence.
Both `validators/git_flow.py` and `handlers/pre_tool/guard.py` consume this
through `read_settings()` so they stay in sync.

Recognized keys (whitelisted — unknown keys are ignored, not raised):
- `override: company`        → switch validator to company-specific prefix set (구체 prefix 정의는 회사별 user-private 트리에 둠 — 예: `flutter/example_app/git-flow-company.md`)
- `mode: solo | single-dev | single_dev` → solo-developer repo
- `direct_push_main: allow | deny`       → fine-grained main-push gate

Fail-closed: missing file, missing fence, parse errors, or unrecognized
keys → empty dict (default strict Git Flow). Frontmatter-only ensures
markdown body text cannot accidentally activate policy.

is_solo_mode requires BOTH `mode: solo*` AND `direct_push_main: allow`
(worker-3 R2 HIGH fix: previously OR-condition allowed silent fail-open
when either key was malformed).
"""
from __future__ import annotations

from pathlib import Path


_RECOGNIZED_KEYS: frozenset[str] = frozenset({
    "override", "mode", "direct_push_main",
})

_SOLO_MODES: frozenset[str] = frozenset({"solo", "single-dev", "single_dev"})


def _read_frontmatter(path: Path) -> dict[str, str]:
    """Parse only the leading --- fence block. Body lines ignored."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    out: dict[str, str] = {}
    for line in parts[1].splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        k, v = s.split(":", 1)
        k = k.strip().lower()
        v = v.strip().lower().strip('"').strip("'")
        if k in _RECOGNIZED_KEYS and v and k not in out:
            out[k] = v
    return out


def read_settings(cwd: str | Path, *, max_levels: int = 6) -> dict[str, str]:
    """Parse `<cwd>/.claude/git-flow-overrides.md` frontmatter only.

    Walks up from cwd to root (default max 6 levels) looking for
    `.claude/git-flow-overrides.md`. This makes hooks behave correctly when
    invoked from subdirectories (e.g. the PreToolUse guard runs from the bash
    shell's cwd, which may be a project subdir like `scripts/` even when the
    override lives at the project root).

    `max_levels` is exposed for tests that create a tempdir under USERPROFILE
    (Windows default) — without a cap, the walk would otherwise reach
    `~/.claude/git-flow-overrides.md` and pick up the user's real settings.

    Returns recognized-key dict or {} on any error / missing file / missing
    frontmatter. Unknown keys silently dropped (key whitelist enforced).
    """
    p = Path(cwd).resolve()
    for _ in range(max_levels):
        candidate = p / ".claude" / "git-flow-overrides.md"
        if candidate.is_file():
            return _read_frontmatter(candidate)
        if p.parent == p:
            break
        p = p.parent
    return {}


def is_solo_mode(cwd: str | Path, *, max_levels: int = 6) -> bool:
    """Return True only when BOTH solo mode AND explicit main-push allow exist.

    worker-3 R2 HIGH: AND-condition replaces previous OR — a single broken or
    missing key is enough to fall back to strict Git Flow (fail-closed).
    """
    s = read_settings(cwd, max_levels=max_levels)
    return s.get("mode") in _SOLO_MODES and s.get("direct_push_main") == "allow"


def is_company_mode(cwd: str | Path, *, max_levels: int = 6) -> bool:
    """Return True if the repo declares a company-specific workflow override.

    Company-specific prefix tables / branch formats live in user-private
    skill subtrees (e.g. flutter/example_app/git-flow-company.md), not in this
    shared lib module.
    """
    return read_settings(cwd, max_levels=max_levels).get("override") == "company"

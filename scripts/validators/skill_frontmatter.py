#!/usr/bin/env python3
"""skill_frontmatter validator — wear-down on missing fields + namespace policy enforcement.

Per harness-perfection debate D6/D7 (Gen3+Gen4 converged):
- Per-skill frontmatter completeness check (name, description, keywords).
- Namespace policy enforcement (single source — not duplicated in hashline.py):
  - skills/ direct gsd-* OR skills/_gsd/* allowed (D6 union)
  - skills/harness-* prohibited (invariant=0 — namespace reserved for commands/)
- Missing fields produce [WARN] (wear-down telemetry, not [FAIL]) so the 18
  legacy skills don't break audit. New skills are expected to satisfy schema.
- Counts gaps in telemetry/skill-frontmatter-gaps.jsonl for trend tracking.

Caller contract (validators/__init__.py L14-19 표준):
- main() -> None, no args
- reads os.getcwd() (informational only — actually scans SKILLS_DIR)
- prints `[PASS]` / `[FAIL]` / `[WARN]` lines to stdout
- never raises; failures via stdout

Required fields (after wear-down): name, description, keywords.
Optional: intent, paths, patterns, requires, phase, min_score.

Harness-* in skills/ → [FAIL] (namespace violation).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.logging import log_stderr, log_telemetry  # noqa: E402
from lib.paths import SKILLS_DIR  # noqa: E402


REQUIRED_FIELDS = ("name", "description", "keywords")

# Subtree path prefixes (forward-slash form, relative to SKILLS_DIR) for which
# missing required fields produce FAIL instead of WARN. Per debate-1777606052
# (mobile co-load) D3+W3a: mobile/** demands complete frontmatter so the
# co-load priority gate has unambiguous metadata. Other subtrees keep the
# wear-down WARN policy. Forward-slash form is enforced via Path.as_posix()
# for Windows compatibility.
MANDATORY_FAIL_PREFIXES: tuple[str, ...] = (
    "mobile/",
)


def _check_naming(path: Path) -> list[str]:
    """Namespace policy enforcement (single source — D7).

    Rules (relative to SKILLS_DIR):
      - skills/harness-* (any nesting) → FAIL (namespace reserved for commands/)
      - skills/{gsd-*, _gsd/*} both allowed (D6 union)
      - other prefixes are unrestricted

    Returns list of failure messages (empty = OK).
    """
    failures: list[str] = []
    try:
        rel = path.relative_to(SKILLS_DIR)
    except ValueError:
        return failures  # not under skills/, no namespace policy

    parts = rel.parts
    if not parts:
        return failures

    top = parts[0]
    # harness-* in skills/ is invariant=0 — commands/ only
    if top.startswith("harness-") or top == "harness":
        failures.append(
            f"namespace violation: '{top}' under skills/ — harness-* prefix is reserved for commands/"
        )
    return failures


def _is_mandatory_subtree(rel: Path, prefixes: tuple[str, ...]) -> bool:
    """Forward-slash prefix match for Windows-safe path scoping.

    Per debate-1777606052 W3a: Path(rel).as_posix() coerces backslash separators
    to forward slashes BEFORE prefix comparison, so 'mobile/' matches both
    'mobile\\ios\\foo.md' (Windows raw) and 'mobile/ios/foo.md' (POSIX).
    """
    rel_posix = Path(rel).as_posix()
    return any(rel_posix.startswith(p) for p in prefixes)


def _is_content_module(path: Path) -> bool:
    """A file is a content module if its parent dir contains a SKILL.md AND
    the file is not SKILL.md itself.

    Convention (wave 7 후속 책임 회수): SKILL.md is the canonical skill entry
    per directory (carries frontmatter); sibling .md files are reference
    content modules referenced FROM SKILL.md and do NOT need frontmatter.

    Example: _example_app/SKILL.md is the entry; _example_app/business-logic.md is a
    content module. Same for _example_app/domains/SKILL.md + siblings.
    """
    if path.name == "SKILL.md":
        return False
    return (path.parent / "SKILL.md").is_file()


def _check_frontmatter_completeness(
    path: Path,
    *,
    mandatory_prefixes: tuple[str, ...] = MANDATORY_FAIL_PREFIXES,
) -> list[tuple[str, str]]:
    """Return (field, kind) gaps for one skill file. kind ∈ {WARN, FAIL}.

    Per debate-1777606052 D3 (mobile co-load priority): when the file lives
    under any prefix in `mandatory_prefixes`, missing required fields are
    elevated from WARN to FAIL. Other subtrees keep the wear-down policy.
    Default arg preserves backward compatibility for existing callers.
    """
    gaps: list[tuple[str, str]] = []
    res = parse_frontmatter(path)
    if res is None:
        gaps.append(("frontmatter", "FAIL"))
        return gaps
    meta, _ = res

    try:
        rel = path.relative_to(SKILLS_DIR)
    except ValueError:
        rel = Path(path.name)
    is_mandatory = _is_mandatory_subtree(rel, mandatory_prefixes)
    severity = "FAIL" if is_mandatory else "WARN"

    for field in REQUIRED_FIELDS:
        if not meta.get(field):
            gaps.append((field, severity))
    return gaps


def main() -> None:
    if not SKILLS_DIR.is_dir():
        print("[PASS] SKILLS_DIR 없음 (skip)")
        return

    files = sorted(SKILLS_DIR.glob("**/*.md"))
    # W23: README/CHANGELOG-style meta files are not skills — exclude.
    # Underscore-prefixed files (_template.md, _meta.md) already convention.
    _META_FILENAMES = frozenset({
        "readme.md", "changelog.md", "license.md", "contributing.md",
    })
    files = [
        f for f in files
        if f.name.lower() not in _META_FILENAMES and not f.name.startswith("_")
    ]
    if not files:
        print("[PASS] skills/ 아래 검사 대상 skill 파일 없음 (skip)")
        return

    total_warns = 0
    total_fails = 0

    for path in files:
        # Skip stack subtrees that aren't lang-agnostic conventions
        # (we still run namespace check on all)
        rel = path.relative_to(SKILLS_DIR)

        # 1. namespace policy
        nm_failures = _check_naming(path)
        for msg in nm_failures:
            print(f"[FAIL] {rel}: {msg}")
            total_fails += 1
            try:
                log_telemetry("skill-frontmatter-gaps", {
                    "path": str(rel), "kind": "FAIL", "field": "namespace", "msg": msg,
                })
            except Exception as e:
                log_stderr(f"[skill_frontmatter] telemetry failed: {e}")

        # 2. frontmatter completeness — applied to ALL skill subtrees
        # (W23 worker-2 R2 HIGH fix: was previously _common only, so flutter/
        # example_app-agent/* could land without frontmatter and silently fail to
        # match in handlers/prompt/skill_match.py:590).
        # Pipeline subtree skipped because it stores stages.yaml not skills.
        # Content modules (sibling of SKILL.md) skipped — SKILL.md is the
        # canonical entry, siblings are reference modules.
        if rel.parts and rel.parts[0] != "_pipeline" \
                and not _is_content_module(path):
            gaps = _check_frontmatter_completeness(path)
            for field, kind in gaps:
                if kind == "FAIL":
                    print(f"[FAIL] {rel}: invalid or missing frontmatter")
                    total_fails += 1
                else:
                    total_warns += 1
                    # WARN: telemetry only, no stdout noise per file
                try:
                    log_telemetry("skill-frontmatter-gaps", {
                        "path": str(rel), "kind": kind, "field": field,
                    })
                except Exception as e:
                    log_stderr(f"[skill_frontmatter] telemetry failed: {e}")

    suffix_parts = []
    if total_warns:
        suffix_parts.append(f"warns={total_warns}")
    if total_fails:
        suffix_parts.append(f"fails={total_fails}")
    suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""

    if total_fails == 0:
        print(f"[PASS] skill_frontmatter 검사 통과 ({len(files)}개 파일{suffix})")


if __name__ == "__main__":
    main()

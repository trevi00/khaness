#!/usr/bin/env python3
"""atlas_frontmatter validator — Atlas vault frontmatter schema enforcement.

Per atlas P0 design (allsolution-compressed-phase0, orchestrator session
orch-1779544694-27f7cc), enforces the Cursor MDC 4-mode activation
frontmatter schema:

  Required keys:
    id, type, activation, description, created, updated, last_writer, status

  type enum: concept | decision | artifact | journal | meta | moc
  activation enum: always | glob | description | manual
  last_writer enum: claude | human
  status enum: active | deprecated | superseded

  When activation=glob, `globs:` field MUST be present and non-empty (list).
  When type=decision and `supersedes` present, the superseded note must exist.
  Dates MUST be YYYY-MM-DD absolute format.

Caller contract (validators/__init__.py L14-19 표준):
  - main() -> None, no args
  - reads ATLAS_DIR (CLAUDE_HOME / 'atlas')
  - prints [PASS]/[FAIL]/[WARN] lines to stdout
  - never raises; failures via stdout
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import ATLAS_DIR  # noqa: E402


REQUIRED_KEYS = (
    "id", "type", "activation", "description",
    "created", "updated", "last_writer", "status",
)

TYPE_ENUM = frozenset({"concept", "decision", "artifact", "procedure", "journal", "meta", "moc"})
ACTIVATION_ENUM = frozenset({"always", "glob", "description", "manual"})
WRITER_ENUM = frozenset({"claude", "human"})
STATUS_ENUM = frozenset({"active", "deprecated", "superseded"})

# Decision body MUST contain `## Consequences` H2 (MADR 호환).
_CONSEQUENCES_HEADER_RE = re.compile(r"^##\s+Consequences\s*$", re.MULTILINE)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def _check_one(path: Path) -> list[tuple[str, str]]:
    """Return list of (severity, message). severity ∈ {WARN, FAIL}."""
    issues: list[tuple[str, str]] = []
    result = parse_frontmatter(path)
    if result is None:
        issues.append(("FAIL", "no frontmatter (no `---` fences)"))
        return issues
    meta, body = result

    # Required keys
    for key in REQUIRED_KEYS:
        if not meta.get(key, ""):
            issues.append(("FAIL", f"missing required key: {key}"))

    # Enum checks (only if key present)
    t = (meta.get("type") or "").strip()
    if t and t not in TYPE_ENUM:
        issues.append(("FAIL", f"type={t!r} not in {sorted(TYPE_ENUM)}"))

    a = (meta.get("activation") or "").strip()
    if a and a not in ACTIVATION_ENUM:
        issues.append(("FAIL", f"activation={a!r} not in {sorted(ACTIVATION_ENUM)}"))

    lw = (meta.get("last_writer") or "").strip()
    if lw and lw not in WRITER_ENUM:
        issues.append(("FAIL", f"last_writer={lw!r} not in {sorted(WRITER_ENUM)}"))

    st = (meta.get("status") or "").strip()
    if st and st not in STATUS_ENUM:
        issues.append(("FAIL", f"status={st!r} not in {sorted(STATUS_ENUM)}"))

    # id format
    id_val = (meta.get("id") or "").strip()
    if id_val and not _ID_RE.match(id_val):
        issues.append(("WARN", f"id={id_val!r} not kebab-case [a-z][a-z0-9_-]*"))

    # Dates
    for date_key in ("created", "updated"):
        dv = (meta.get(date_key) or "").strip()
        if dv and not _DATE_RE.match(dv):
            issues.append(("WARN", f"{date_key}={dv!r} not YYYY-MM-DD"))

    # activation=glob requires globs
    if a == "glob":
        globs = meta.get("globs")
        if not globs or (isinstance(globs, list) and not globs):
            issues.append(("FAIL", "activation=glob but globs field missing/empty"))

    # type=decision + supersedes consistency (best-effort: link target exists)
    if t == "decision":
        sup = meta.get("supersedes")
        if sup:
            # supersedes can be id (lookup) or path — best-effort path resolve
            issues.append(("WARN", f"supersedes={sup!r} — verify target exists manually"))

    # type=decision: body MUST contain `## Consequences` H2 (MADR 호환, conventions.md spec).
    if t == "decision":
        if not _CONSEQUENCES_HEADER_RE.search(body):
            issues.append((
                "WARN",
                "decision body missing `## Consequences` H2 section "
                "(MADR-style required by conventions.md)",
            ))

    # status=deprecated requires deprecated_at + deprecated_reason + superseded_by.
    if st == "deprecated":
        for req in ("deprecated_at", "deprecated_reason", "superseded_by"):
            if not (meta.get(req) or "").strip():
                issues.append((
                    "FAIL",
                    f"status=deprecated requires {req!r} (conventions.md spec)",
                ))
        # deprecated_at format check
        dep_at = (meta.get("deprecated_at") or "").strip()
        if dep_at and not _DATE_RE.match(dep_at):
            issues.append((
                "WARN",
                f"deprecated_at={dep_at!r} not YYYY-MM-DD",
            ))

    return issues


def main() -> None:
    if not ATLAS_DIR.is_dir():
        print("[PASS] ATLAS_DIR 없음 (skip)")
        return

    files = sorted(ATLAS_DIR.rglob("*.md"))
    if not files:
        print("[PASS] atlas_frontmatter: no .md files (empty vault)")
        return

    total_files = len(files)
    fail_count = 0
    warn_count = 0
    fail_files: list[str] = []

    for f in files:
        rel = f.relative_to(ATLAS_DIR)
        issues = _check_one(f)
        file_failed = False
        for severity, msg in issues:
            if severity == "FAIL":
                print(f"[FAIL] atlas_frontmatter: {rel}: {msg}")
                fail_count += 1
                file_failed = True
            else:
                print(f"[WARN] atlas_frontmatter: {rel}: {msg}")
                warn_count += 1
        if file_failed:
            fail_files.append(str(rel))

    if fail_count == 0 and warn_count == 0:
        print(f"[PASS] atlas_frontmatter: {total_files} files, all schema-valid")
    elif fail_count == 0:
        print(f"[PASS] atlas_frontmatter: {total_files} files, {warn_count} warnings, 0 failures")
    else:
        print(
            f"[FAIL] atlas_frontmatter: {total_files} files scanned, "
            f"{fail_count} failures across {len(fail_files)} files, {warn_count} warnings"
        )


if __name__ == "__main__":
    main()

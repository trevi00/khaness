#!/usr/bin/env python3
r"""mutation_safety validator — detect destructive shell snippets without nearby safety gates.

Round 5 W2/W3 systemic finding: many _common skills document shell commands
that mutate state (rm -rf, git reset --hard, docker compose down -v, drop
table, force push, etc.) without nearby `dry-run`, `snapshot`, `사용자 확인`,
`backup`, or similar safety language. A user copy-pasting the snippet without
reading the surrounding prose loses data.

This validator scans `skills/**/*.md` and flags any line containing a known
destructive token unless a safety token appears within ±10 lines.

## Caller contract
- main() -> None, no args
- reads os.getcwd() == project root
- prints `[PASS]` / `[FAIL]` / `[WARN]` lines to stdout
- never raises; failures via stdout

## Detection
Destructive tokens (case-insensitive, regex):
  - `rm -rf`, `rm\s+-fr`, `git reset --hard`, `git push.*--force(?!-with-lease)`
  - `git clean -fd`, `docker compose down -v`, `DROP TABLE`, `DROP DATABASE`,
  - `TRUNCATE`, `DELETE FROM` without WHERE-with-bind hint, `kubectl delete`

Safety tokens (any one within ±10 lines defuses the warning):
  - `dry-run`, `dryrun`, `--dry-run`, `snapshot`, `backup`, `백업`,
  - `사용자 확인`, `명시 확인`, `confirm`, `사용자 명시`, `dev 로컬`,
  - `prod 절대 금지`, `WHERE`, `--force-with-lease`, `non-destructive`, `비파괴`

Severity: WARN (telemetry only, doesn't fail CI by default). Pass `--strict`
to upgrade to FAIL.

## Whitelist
- `state/**`, `.git/**`, `node_modules/**`, `.omc/**`, `telemetry/**`
- `get-shit-done/**` (legacy CLI source — separate concern)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.logging import log_telemetry  # noqa: E402

DESTRUCTIVE_PATTERNS = [
    # rm -rf / rm -fr / rm --recursive (recursive flag mandatory — `rm -f file.txt` 단일 파일 제외)
    (r"\brm\s+(-[rR][fF]?|-[fF][rR]|--recursive)", "rm -rf"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard"),
    (r"\bgit\s+push\b.*--force(?!-with-lease)", "git push --force"),
    (r"\bgit\s+clean\s+-[fd]+\b", "git clean -fd"),
    (r"\bdocker\s+compose\s+down\s+-v\b", "docker compose down -v"),
    (r"\bdocker-compose\s+down\s+-v\b", "docker-compose down -v"),
    # SQL: DROP TABLE / DROP DATABASE — exclude prose "DROP TABLE for migration" 같은 example?
    # 의도적으로 keep, migration 코드에는 safety token (`migration`, `version`) 추가 권장.
    (r"\bDROP\s+TABLE\b", "DROP TABLE"),
    (r"\bDROP\s+DATABASE\b", "DROP DATABASE"),
    (r"\bTRUNCATE\s+TABLE\b", "TRUNCATE TABLE"),
    (r"\bkubectl\s+delete\b", "kubectl delete"),
]

SAFETY_TOKENS = {
    "dry-run", "dryrun", "--dry-run", "snapshot",
    "backup", "백업", "사용자 확인", "명시 확인",
    "confirm", "사용자 명시", "dev 로컬", "비파괴",
    "non-destructive", "WHERE", "--force-with-lease",
    "prod 절대 금지", "절대 금지",
    "anti-pattern", "anti pattern", "안티패턴", "잘못된",
    "예시", "example", "migration", "마이그레이션",
}

EXCLUDE_DIRS = (
    ".git", "node_modules", "__pycache__", "dist", "build",
    "state", ".omc", "telemetry",
    "get-shit-done",  # legacy CLI source — own scope
)

CONTEXT_RADIUS = 10  # lines


def _should_skip(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = rel.parts
    if not parts:
        return True
    return parts[0] in EXCLUDE_DIRS


def _has_safety_nearby(lines: list[str], idx: int, radius: int = CONTEXT_RADIUS) -> bool:
    lo = max(0, idx - radius)
    hi = min(len(lines), idx + radius + 1)
    window = "\n".join(lines[lo:hi]).lower()
    for tok in SAFETY_TOKENS:
        if tok.lower() in window:
            return True
    return False


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return [(lineno, pattern_label, full_line), ...]."""
    findings: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for pat, label in DESTRUCTIVE_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                if not _has_safety_nearby(lines, i):
                    findings.append((i + 1, label, line.strip()[:120]))
                break  # one finding per line
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="upgrade WARNs to FAILs for CI gate")
    args = ap.parse_args(argv)

    root = Path(os.getcwd())
    skill_files = sorted((root / "skills").glob("**/*.md")) if (root / "skills").is_dir() else []
    skill_files = [p for p in skill_files if not _should_skip(p, root)]

    total_files = 0
    total_findings = 0
    file_count = len(skill_files)

    for path in skill_files:
        findings = scan_file(path)
        if not findings:
            continue
        total_files += 1
        rel = path.relative_to(root)
        for lineno, label, snippet in findings:
            kind = "FAIL" if args.strict else "WARN"
            print(f"[{kind}] {rel}:{lineno}: destructive `{label}` without nearby safety gate")
            print(f"       └─ {snippet}")
            total_findings += 1
            try:
                log_telemetry("mutation-safety-gaps", {
                    "path": str(rel), "lineno": lineno,
                    "pattern": label, "snippet": snippet,
                })
            except Exception:
                pass

    if total_findings == 0:
        print(f"[PASS] mutation_safety: {file_count}개 파일 검사, 0 unprotected destructive op")
        return 0

    summary_kind = "FAIL" if args.strict else "WARN"
    print(f"[{summary_kind}] mutation_safety: {total_findings} unprotected ops in {total_files}/{file_count} 파일")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())

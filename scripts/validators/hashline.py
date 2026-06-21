#!/usr/bin/env python3
"""Hashline validator — anchor-line consistency check for skill/CLAUDE.md edits.

## Spec (inline; no separate spec.md)

### Purpose
Skill/CLAUDE.md/AGENTS.md 같은 LLM-context 파일은 단일 hash anchor 라인
(`# !`, `<!-- ! -->`) 을 통해 다른 파일이 cross-reference 하는 핵심
selector를 노출한다. 이 anchor가 의도 없이 변경되면 의존하는 hook/skill 매처가
silent breakage. 이 validator는 anchor 라인의 형식·고유성을 검사한다.

### Caller contract (validators/__init__.py L14-19 표준 준수)
- main() -> None, no args
- reads os.getcwd() == project root
- prints `[PASS]` / `[FAIL]` / `[WARN]` lines to stdout
- never raises; failures via stdout

### Apply globs (cwd-relative)
- `**/CLAUDE.md` (project + subproject)
- `**/AGENTS.md`
- `.claude/skills/**/*.md`

User-level `~/.claude/skills/**/*.md` is NOT scanned by this validator (cwd-bound).
For user-level audit, run from `~/.claude/` directly or use `harness-audit`.

### Anchor 문법
```
# ! <ID> <description>           ← markdown
<!-- ! <ID> <description> -->    ← HTML 주석
```
- `<ID>`: 영문/숫자/하이픈만, 1-32자, kebab-case 권장
- 한 파일 내 ID는 unique (중복 시 FAIL)
- description: 자유 1줄 (≤120자)

### Whitelist (검사 제외)
- `.git/**`, `node_modules/**`, `__pycache__/**`, `dist/**`, `build/**`
- `state/omc-reference/**`, `state/superpowers-reference/**`,
  `state/openagent-reference/**` (외부 레퍼런스 클론)

### Registry priority
validators/__init__.py `VALIDATOR_NAMES` tuple 알파벳순 보존. 이 모듈은
'flow' 다음 'logical' 이전에 등록 (h < l).

### Tags telemetry
위반 발견 시 `log_telemetry("hashline-violations", {...})` 으로 기록.
PASS는 telemetry 안 남김 (noise 방지).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# Ensure scripts/ on sys.path so lib.* resolves when imported via subprocess
_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.logging import log_stderr, log_telemetry  # noqa: E402


ANCHOR_RE = re.compile(
    r"""(?x)
    ^\s*
    (?:
        \#\s*!\s+([A-Za-z0-9-]{1,32})\s+(.{1,120})$           # markdown form
      | <!--\s*!\s+([A-Za-z0-9-]{1,32})\s+(.{1,120}?)\s*-->$  # html-comment form
    )
    """,
    re.MULTILINE,
)

GLOBS = (
    "**/CLAUDE.md",
    "**/AGENTS.md",
    ".claude/skills/**/*.md",
)

WHITELIST_PARTS = (
    ".git",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    # external reference clones (not our content)
    "omc-reference",
    "superpowers-reference",
    "openagent-reference",
)


def _is_whitelisted(path: Path) -> bool:
    return any(part in WHITELIST_PARTS for part in path.parts)


def _scan_file(path: Path) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """Return (errors, warnings) for one file. Each entry: (kind, line_no, msg)."""
    errors: list[tuple[str, int, str]] = []
    warnings: list[tuple[str, int, str]] = []
    seen_ids: dict[str, int] = {}

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        warnings.append(("read-error", 0, f"파일 읽기 실패: {e}"))
        return errors, warnings

    for m in ANCHOR_RE.finditer(text):
        anchor_id = m.group(1) or m.group(3)
        # rough line number — count newlines up to match.start()
        line_no = text.count("\n", 0, m.start()) + 1
        if anchor_id in seen_ids:
            errors.append((
                "duplicate-id",
                line_no,
                f"anchor ID '{anchor_id}' duplicated (also at line {seen_ids[anchor_id]})",
            ))
        else:
            seen_ids[anchor_id] = line_no

    return errors, warnings


def main() -> None:
    cwd = Path(os.getcwd()).resolve()
    candidates: list[Path] = []
    for pattern in GLOBS:
        candidates.extend(cwd.glob(pattern))
    # dedup + filter whitelist
    seen: set[Path] = set()
    targets: list[Path] = []
    for p in candidates:
        if p in seen or not p.is_file() or _is_whitelisted(p):
            continue
        seen.add(p)
        targets.append(p)

    if not targets:
        print("[PASS] 검사 대상 anchor 파일 없음 (skip)")
        return

    total_errors = 0
    total_warnings = 0

    for path in targets:
        errors, warnings = _scan_file(path)
        total_errors += len(errors)
        total_warnings += len(warnings)
        try:
            rel = path.relative_to(cwd)
        except ValueError:
            rel = path
        for kind, line_no, msg in errors:
            print(f"[FAIL] {rel}:{line_no} ({kind}) {msg}")
            try:
                log_telemetry("hashline-violations", {
                    "path": str(rel),
                    "line": line_no,
                    "kind": kind,
                    "msg": msg,
                })
            except Exception as e:
                log_stderr(f"[hashline] telemetry append failed: {e}")
        for kind, line_no, msg in warnings:
            print(f"[WARN] {rel}:{line_no} ({kind}) {msg}")

    if total_errors == 0:
        suffix = f", warnings={total_warnings}" if total_warnings else ""
        print(f"[PASS] hashline anchor 검사 통과 ({len(targets)}개 파일{suffix})")


if __name__ == "__main__":
    main()

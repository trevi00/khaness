#!/usr/bin/env python3
"""private_content_leak validator — detect user-private content in shared skill trees.

Round 5/6 surfaced repeated user-private leak: company-specific (ACME_INTERNAL,
example_cloud, GP-AUTH headers, example_gateway, etc.) and project-specific (이커머스,
storeUnqcd) content was inlined into shared subtrees (`_common`, `java/lang`,
`java/springboot-3.2`, `kotlin/android`). Once cleaned, drift can recur.

This validator scans shared trees and flags any line containing known
user-private tokens. POINTER references (mentions in cross-link context like
"see flutter/example_app/...") are exempted via opt-out comment markers.

## Caller contract
- main() -> None
- prints `[PASS]` / `[FAIL]` / `[WARN]` lines, never raises
- reads cwd-relative `skills/` tree

## Shared trees (scanned)
- skills/_common/**
- skills/java/lang/**, skills/java/springboot-*/**
- skills/kotlin/lang/**, skills/kotlin/android/**, skills/kotlin/N.x/**
- skills/typescript/5.x/**, skills/typescript/{nextjs,nuxt,react,vue}/**
- skills/flutter/3.x/** (NOT flutter/example_app*)
- skills/dart/**, skills/mobile/**

User-private subtrees (NOT scanned — leak destination is OK):
- skills/flutter/example_app/, skills/flutter/example_app-agent/
- skills/java/example_app/, skills/java/ecommerce/

## Tokens
- ACME_INTERNAL / example_cloud / example_app-client-agent (회사 코드)
- GP-AUTH-ID / GP-AUTH-TOKEN / GP-AUTH-RULE (회사 헤더)
- fchqCode / storeUnqcd (회사 ID 포맷)
- 이커머스 (특정 프로젝트명, ACME_INTERNAL와 별도)

Pointer-OK markers:
- `flutter/example_app/`, `java/example_app/`, `java/ecommerce/`, `example_app-agent/` —
  의도적 cross-link 참조는 무시.
"""
from __future__ import annotations

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

# Tokens that should NOT appear in shared skill content (case-sensitive for
# brand names, case-insensitive for headers).
PRIVATE_TOKENS = [
    re.compile(r"\bACME_INTERNAL\b"),
    re.compile(r"\bexample_cloud\b"),
    re.compile(r"\bexample_app-client-agent\b"),
    re.compile(r"\bGP-AUTH-(ID|TOKEN|RULE)\b", re.IGNORECASE),
    re.compile(r"\bfchqCode\b"),
    re.compile(r"\bstoreUnqcd\b"),
    re.compile(r"이커머스"),
]

# Lines containing pointer-OK markers are exempted (cross-link references).
POINTER_OK_PATTERNS = [
    re.compile(r"flutter/example_app[/-]"),
    re.compile(r"java/example_app/"),
    re.compile(r"java/ecommerce/"),
    re.compile(r"feedback_example_app"),  # memory file references
    re.compile(r"feedback_legacy"),
    re.compile(r"feedback_git_convention"),
    re.compile(r"project_example_app"),
]

# Subtrees scanned for leak (positive list).
SHARED_SUBTREE_PATTERNS = [
    "_common",
    "java/lang",
    "java/springboot-3.2",
    "java/springboot-3.5",
    "java/springboot-4",
    "kotlin/lang",
    "kotlin/android",
    "kotlin/1.9.x",
    "kotlin/2.0.x",
    "kotlin/2.1.x",
    "typescript/5.x",
    "typescript/nextjs",
    "typescript/nuxt",
    "typescript/react",
    "typescript/vue",
    "flutter/3.x",
    "dart",
    "mobile/ios",
    "mobile/react-native",
]

# Subtrees that ARE allowed to contain private tokens (skip entirely).
PRIVATE_SUBTREE_PATTERNS = [
    "flutter/example_app",
    "flutter/example_app-agent",
    "java/example_app",
    "java/ecommerce",
]


def _is_private_subtree(rel: Path) -> bool:
    posix = rel.as_posix()
    for pat in PRIVATE_SUBTREE_PATTERNS:
        if posix.startswith(f"skills/{pat}/") or f"/{pat}/" in f"/{posix}":
            return True
    return False


def _is_in_shared_subtree(rel: Path) -> bool:
    posix = rel.as_posix()
    for pat in SHARED_SUBTREE_PATTERNS:
        if posix.startswith(f"skills/{pat}/"):
            return True
    return False


def _line_has_pointer_ok(line: str) -> bool:
    return any(p.search(line) for p in POINTER_OK_PATTERNS)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return [(lineno, token, line_snippet), ...] of private-token leaks."""
    findings: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    for i, line in enumerate(text.splitlines(), 1):
        if _line_has_pointer_ok(line):
            continue
        for pat in PRIVATE_TOKENS:
            m = pat.search(line)
            if m:
                findings.append((i, m.group(0), line.strip()[:120]))
                break
    return findings


def main() -> None:
    root = Path(os.getcwd())
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        print("[PASS] skills/ dir 없음 (skip)")
        return

    md_files = sorted(skills_dir.glob("**/*.md"))
    md_files = [p for p in md_files if not _is_private_subtree(p.relative_to(root))]
    md_files = [p for p in md_files if _is_in_shared_subtree(p.relative_to(root))]

    total_findings = 0
    files_with_leak = 0

    for path in md_files:
        findings = scan_file(path)
        if not findings:
            continue
        files_with_leak += 1
        rel = path.relative_to(root)
        for lineno, token, snippet in findings:
            print(f"[FAIL] {rel}:{lineno}: 사용자-private '{token}' 누출")
            print(f"       └─ {snippet}")
            total_findings += 1
            try:
                log_telemetry("private-content-leak", {
                    "path": str(rel), "lineno": lineno,
                    "token": token, "snippet": snippet,
                })
            except Exception:
                pass

    if total_findings == 0:
        print(f"[PASS] private_content_leak: {len(md_files)}개 shared 파일 검사, 0 leak")
        return

    print(f"[FAIL] private_content_leak: {total_findings} leak in {files_with_leak}/{len(md_files)} 파일")


if __name__ == "__main__":
    main()

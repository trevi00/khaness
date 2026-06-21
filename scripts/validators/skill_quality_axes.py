#!/usr/bin/env python3
"""skill_quality_axes validator — ISO/IEC 25010 9축 강제 게이트 (9 게이트 확장).

각 신규 추출 스킬은 9개 게이트 모두 통과해야 한다:
- G1 기능 적합성   · `## Source` 절 ≥ 1 인용 (정확성/안정성 추적)
- G2 성능 효율성   · ≤ 250 lines AND ≤ 8192 bytes (시간/자원/용량)
- G3 호환성       · frontmatter `requires:` ≥ 1 (공존성/상호운용성)
- G4 사용성       · 5 표준 절 (학습성/운영자 보호)
- G5 신뢰성       · Gotchas ≥ 3 (가용성/결함허용/회복성/무결성)
- G6 보안         · Source URL `https://` only + 시크릿 패턴 grep 차단
- G7 유지보수성    · `## 9축 품질 체크` 표에 9개 main 축 라벨 모두 등장
- G8 이식성       · frontmatter `tech-stack` ⊆ KNOWN_STACKS (any 또는 known)
- G9 확장성       · `requires:` 토큰 = 실제 존재하는 스킬 (name 또는 file stem)

Enforce 트리거 (둘 중 하나):
1. Path prefix 화이트리스트 (data/, infra/, ml/)
2. Frontmatter flag `quality_axes_enforced: true` (위치 무관 opt-in)

Wear-down: legacy 80+ 노드는 enforce 안 됨 (변경 영향 0).

Caller contract (validators/__init__.py L14-19 표준):
- main() -> None, no args
- prints `[PASS]` / `[FAIL]` lines to stdout
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
from lib.logging import log_stderr, log_telemetry  # noqa: E402
from lib.paths import SKILLS_DIR  # noqa: E402

MAX_LINES = 250
MAX_BYTES = 8192
MIN_GOTCHAS = 3
MIN_REQUIRES = 1

MANDATORY_PREFIXES: tuple[str, ...] = ("data/", "infra/", "ml/", "systems/")

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## 의사결정 트리",
    "## 가이드",
    "## Gotchas",
    "## 9축 품질 체크",
    "## Source",
)

REQUIRED_AXES_LABELS: tuple[str, ...] = (
    "기능 적합성",
    "성능 효율성",
    "호환성",
    "사용성",
    "신뢰성",
    "보안",
    "유지보수성",
    "이식성",
    "확장성",
)

KNOWN_STACKS: frozenset[str] = frozenset({
    "any", "java", "kotlin", "flutter", "dart", "typescript", "javascript",
    "swift", "python", "go", "rust", "scala", "ruby", "cpp", "csharp",
})

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\baws_secret\w*", re.IGNORECASE),
    re.compile(r"BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY"),
    re.compile(r"\bpassword\s*=\s*['\"][^'\"]{6,}", re.IGNORECASE),
    re.compile(r"\bAPI[_-]?KEY\s*=\s*['\"][^'\"]+", re.IGNORECASE),
)

_HTTP_INSECURE = re.compile(r"\bhttp://", re.IGNORECASE)


def _is_mandatory_prefix(rel: Path) -> bool:
    rel_posix = Path(rel).as_posix()
    return any(rel_posix.startswith(p) for p in MANDATORY_PREFIXES)


def _is_enforced(rel: Path, meta: dict | None) -> bool:
    if _is_mandatory_prefix(rel):
        return True
    if meta is not None:
        flag = meta.get("quality_axes_enforced")
        if isinstance(flag, bool):
            return flag
        if isinstance(flag, str):
            return flag.strip().lower() in {"true", "yes", "1"}
    return False


def _build_skill_index() -> set[str]:
    """Index all skill identifiers (frontmatter name OR file stem)."""
    idx: set[str] = set()
    if not SKILLS_DIR.is_dir():
        return idx
    for path in SKILLS_DIR.glob("**/*.md"):
        if path.name.startswith("_"):
            continue
        idx.add(path.stem)
        res = parse_frontmatter(path)
        if res is not None:
            meta, _ = res
            n = meta.get("name")
            if isinstance(n, str) and n.strip():
                idx.add(n.strip())
    return idx


def _check_quality_axes(
    path: Path,
    *,
    skill_index: set[str],
) -> list[tuple[str, str]]:
    """Return list of (gate, message)."""
    gaps: list[tuple[str, str]] = []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        gaps.append(("read", f"read failed: {e}"))
        return gaps

    line_count = text.count("\n") + 1
    byte_count = len(text.encode("utf-8"))
    if line_count > MAX_LINES:
        gaps.append(("G2-perf", f"line_count={line_count} > {MAX_LINES}"))
    if byte_count > MAX_BYTES:
        gaps.append(("G2-perf", f"byte_count={byte_count} > {MAX_BYTES}"))

    res = parse_frontmatter(path)
    meta: dict = {}
    if res is None:
        gaps.append(("G3-compat", "frontmatter missing or invalid"))
    else:
        meta, _ = res

    req_raw = meta.get("requires") or ""
    req_list = [t for t in str(req_raw).split() if t.strip()]
    if len(req_list) < MIN_REQUIRES:
        gaps.append(
            ("G3-compat",
             f"requires has {len(req_list)} entries (<{MIN_REQUIRES})")
        )
    for tok in req_list:
        if tok not in skill_index:
            gaps.append(("G9-extensibility", f"requires '{tok}' has no target skill"))

    for sect in REQUIRED_SECTIONS:
        if sect not in text:
            gaps.append(("G4-usability", f"missing section: {sect}"))

    if "## Source" in text:
        src_block = text.split("## Source", 1)[1]
        src_lines = [
            l.strip() for l in src_block.splitlines()
            if l.strip().startswith("-")
        ]
        if len(src_lines) < 1:
            gaps.append(("G1-evidence", "Source has 0 cited entries"))
        if _HTTP_INSECURE.search(src_block):
            gaps.append(("G6-security", "Source contains http:// (use https)"))

    if "## Gotchas" in text:
        after = text.split("## Gotchas", 1)[1]
        block = (
            after.split("## Source", 1)[0]
            if "## Source" in after else after
        )
        sub = [l for l in block.splitlines() if l.startswith("### ")]
        if len(sub) < MIN_GOTCHAS:
            gaps.append(
                ("G5-reliability",
                 f"Gotchas has {len(sub)} entries (<{MIN_GOTCHAS})")
            )

    if "## 9축 품질 체크" in text:
        after = text.split("## 9축 품질 체크", 1)[1]
        block = after.split("## ", 1)[0] if "## " in after else after
        for label in REQUIRED_AXES_LABELS:
            if label not in block:
                gaps.append(("G7-maintainability", f"axes table missing label: {label}"))

    for pat in SECRET_PATTERNS:
        if pat.search(text):
            gaps.append(("G6-security", f"secret pattern detected: {pat.pattern[:40]}"))

    ts_raw = meta.get("tech-stack") or meta.get("tech_stack") or ""
    ts_tokens = [t.strip() for t in str(ts_raw).replace(",", " ").split() if t.strip()]
    if not ts_tokens:
        gaps.append(("G8-portability", "tech-stack is empty"))
    else:
        unknown = [t for t in ts_tokens if t not in KNOWN_STACKS]
        if unknown:
            gaps.append(
                ("G8-portability",
                 f"tech-stack has unknown values: {unknown} (allowed: any/known stack)")
            )

    return gaps


def main() -> None:
    if not SKILLS_DIR.is_dir():
        print("[PASS] SKILLS_DIR 없음 (skip)")
        return

    files = sorted(SKILLS_DIR.glob("**/*.md"))
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

    skill_index = _build_skill_index()

    total_fails = 0
    inspected = 0

    for path in files:
        try:
            rel = path.relative_to(SKILLS_DIR)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] == "_pipeline":
            continue

        res = parse_frontmatter(path)
        meta = res[0] if res is not None else None
        if not _is_enforced(rel, meta):
            continue
        inspected += 1

        gaps = _check_quality_axes(path, skill_index=skill_index)
        for gate, msg in gaps:
            print(f"[FAIL] {rel}: [{gate}] {msg}")
            total_fails += 1
            try:
                log_telemetry("skill-quality-axes-gaps", {
                    "path": str(rel), "gate": gate, "msg": msg,
                })
            except Exception as e:
                log_stderr(f"[skill_quality_axes] telemetry failed: {e}")

    suffix = f" (fails={total_fails})" if total_fails else ""
    if total_fails == 0:
        print(
            f"[PASS] skill_quality_axes 9게이트 통과 "
            f"(inspected={inspected}{suffix})"
        )


if __name__ == "__main__":
    main()

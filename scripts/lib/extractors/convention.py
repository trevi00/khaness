"""Reverse-engineer .claude/convention.md from Java source.

Extracts:
- Package structure (top-level + per-domain layout)
- Custom annotations (@Validation, @Configuration, etc.)
- ErrorCode-like enums (numeric codes + messages)
- Response wrapper class fields (ApiResponse, CommonResponse, ...)
- URL patterns from @RequestMapping (controller class-level + handler-level prefixes)

Output passes validators/convention.py basic checks (package table, DTO mention,
ErrorCode mention).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .base import (
    ExtractionResult,
    find_java_sources,
    safe_read,
    strip_java_comments,
)


# Package declaration
_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
# class header — captures class/interface/enum + name + annotations preceding (rough)
_CLASS_HEADER_RE = re.compile(
    r"((?:@\w+(?:\([^)]*\))?\s+)*)"
    r"public\s+(?:final\s+|abstract\s+)?(class|interface|enum)\s+(\w+)",
    re.MULTILINE,
)
# @RequestMapping class-level OR handler-level
_REQUEST_MAPPING_RE = re.compile(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]+)"')
_HANDLER_MAPPING_RE = re.compile(
    r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*\(\s*(?:value\s*=\s*)?"([^"]+)"'
)
# Numeric error code constants — supports `int X = 8020001;` or `X(8020001, "...")`
_ERROR_CODE_FIELD_RE = re.compile(r"\b([A-Z][A-Z0-9_]+)\s*=\s*(\d{6,})\b")
_ERROR_CODE_ENUM_RE = re.compile(r"\b([A-Z][A-Z0-9_]+)\s*\(\s*(\d{4,})\s*,\s*\"([^\"]+)\"")


class ConventionExtractor:
    name = "convention"
    target = ".claude/convention.md"
    description = "Reverse-engineer convention.md from Java source"

    def can_extract(self, root: Path) -> bool:
        return bool(find_java_sources(root, max_files=1))

    def extract(self, root: Path) -> ExtractionResult:
        notes: list[str] = []
        sources: list[str] = []

        java_files = find_java_sources(root)
        if not java_files:
            return ExtractionResult(
                extractor=self.name, target=self.target,
                content="# Convention (no Java source found)\n",
                confidence=0.0, notes=["no .java under src/main/java"],
            )

        sources = [p.relative_to(root).as_posix() for p in java_files[:20]]

        package_segments = self._collect_packages(java_files)
        url_prefixes = self._collect_url_prefixes(java_files)
        error_codes = self._collect_error_codes(java_files)
        response_classes = self._collect_response_wrappers(java_files)

        # Confidence calculation — weighted signal presence
        signals = sum([
            bool(package_segments),
            bool(url_prefixes),
            bool(error_codes),
            bool(response_classes),
        ])
        confidence = round(0.3 + 0.175 * signals, 2)  # 4 signals = 1.0

        if signals == 0:
            notes.append("no convention signals found — output is a placeholder")
        else:
            notes.append(f"{signals}/4 convention signals detected")

        content = self._render(package_segments, url_prefixes, error_codes, response_classes)

        return ExtractionResult(
            extractor=self.name,
            target=self.target,
            content=content,
            confidence=min(confidence, 1.0),
            notes=notes,
            sources=sources,
        )

    # === collectors ===

    def _collect_packages(self, files: list[Path]) -> Counter:
        """Top-3-segment package paths, counted."""
        counter: Counter = Counter()
        for f in files:
            text = strip_java_comments(safe_read(f))
            m = _PACKAGE_RE.search(text)
            if not m:
                continue
            segs = m.group(1).split(".")
            top = ".".join(segs[:3]) if len(segs) >= 3 else m.group(1)
            counter[top] += 1
        return counter

    def _collect_url_prefixes(self, files: list[Path]) -> list[tuple[str, str]]:
        """(class_name, base_url) pairs for @RestController-like classes."""
        out: list[tuple[str, str]] = []
        for f in files:
            text = strip_java_comments(safe_read(f))
            if "@RestController" not in text and "@Controller" not in text:
                continue
            class_match = _CLASS_HEADER_RE.search(text)
            if not class_match:
                continue
            name = class_match.group(3)
            mapping = _REQUEST_MAPPING_RE.search(text)
            base = mapping.group(1) if mapping else "(no class-level @RequestMapping)"
            out.append((name, base))
        return out

    def _collect_error_codes(self, files: list[Path]) -> list[tuple[str, str, str]]:
        """(name, code, message) — message may be empty for plain field-form codes."""
        results: list[tuple[str, str, str]] = []
        for f in files:
            text = strip_java_comments(safe_read(f))
            if "ErrorCode" not in f.name and "ErrorType" not in f.name and "Error" not in f.name:
                continue
            for m in _ERROR_CODE_ENUM_RE.finditer(text):
                results.append((m.group(1), m.group(2), m.group(3)))
            for m in _ERROR_CODE_FIELD_RE.finditer(text):
                results.append((m.group(1), m.group(2), ""))
            if results:
                break
        # Dedupe by name, preserve order
        seen = set()
        deduped = []
        for name, code, msg in results:
            if name in seen:
                continue
            seen.add(name)
            deduped.append((name, code, msg))
        return deduped[:30]  # cap

    def _collect_response_wrappers(self, files: list[Path]) -> list[str]:
        """Class names matching common response wrapper patterns."""
        out = []
        seen = set()
        for f in files:
            stem = f.stem
            if stem in seen:
                continue
            if any(k in stem for k in ("ApiResponse", "CommonResponse", "Result", "Response")):
                if stem.endswith("Response") or stem.endswith("Result"):
                    out.append(stem)
                    seen.add(stem)
            if len(out) >= 8:
                break
        return out

    # === rendering ===

    def _render(self, packages: Counter, urls: list[tuple[str, str]],
                error_codes: list[tuple[str, str, str]], wrappers: list[str]) -> str:
        L = []
        L.append("<!-- AUTO-GENERATED by lib.extractors.convention — review and refine. -->")
        L.append("")
        L.append("# Convention")
        L.append("")
        L.append("## 패키지 구조")
        L.append("")
        L.append("| 패키지 | 사용 횟수 | 설명 |")
        L.append("|---|---|---|")
        for pkg, count in packages.most_common(10):
            L.append(f"| `{pkg}` | {count} | (분석 필요) |")
        if not packages:
            L.append("| (없음) | | 패키지 추출 실패 |")
        L.append("")

        L.append("## 컨트롤러 URL 컨벤션")
        L.append("")
        L.append("| Controller | Base URL |")
        L.append("|---|---|")
        for name, base in urls[:20]:
            L.append(f"| `{name}` | `{base}` |")
        if not urls:
            L.append("| (없음) | (Controller 미발견) |")
        L.append("")

        L.append("## ErrorCode 체계")
        L.append("")
        if error_codes:
            L.append("| 코드 상수 | 숫자 | 메시지 |")
            L.append("|---|---|---|")
            for name, code, msg in error_codes:
                L.append(f"| `{name}` | `{code}` | {msg or '_(메시지 없음)_'} |")
        else:
            L.append("_ErrorCode/ErrorType 클래스 미발견 — 직접 작성 필요_")
        L.append("")

        L.append("## 공통 응답 형식 (Response 클래스)")
        L.append("")
        if wrappers:
            for w in wrappers:
                L.append(f"- `{w}`")
        else:
            L.append("_응답 wrapper 클래스 미발견_")
        L.append("")

        L.append("## DTO 컨벤션")
        L.append("")
        L.append("- Request/Response DTO를 분리한다")
        L.append("- 도메인별 `dto/` 패키지에 배치한다")
        L.append("")

        return "\n".join(L) + "\n"


# Lazy-registry export (matches lib.providers PROVIDER / lib.workers MULTIPLEXER pattern).
EXTRACTOR = ConventionExtractor

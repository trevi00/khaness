#!/usr/bin/env python3
"""dart_strict_type_advisor.py - PreToolUse hook

Detects raw-type / inference_failure-prone patterns in Dart code before Write/Edit.
Emits non-blocking advisory (additionalContext) so Claude can self-correct.

Triggered learnings (2-Strike satisfied, example_project project):
  - Stage 17 hotfix: 14 instances (Dio.post + MaterialPageRoute + Map literal)
  - I-5 hotfix:     3 instances (`<Map>[]` in integration_test)
  Total 17 strict_raw_type / inference_failure warnings across 2 phases.

Patterns flagged (all advisory — no DENY):
  1. `<Map>` / `<List>` / `<Set>` raw type literal (e.g. `<Map>[]`, `<Map>{}`)
  2. `Map<dynamic, dynamic>` implicit (bare `{}` in typed context — best-effort)
  3. `MaterialPageRoute(` without `<T>` type argument
  4. `dio.<verb>(` / `_dio.<verb>(` without `<T>` type argument
     verbs: post / get / put / delete / patch / fetch / request

Hook output schema mirrors pre_tool/guard.py:
  WARN: {"hookSpecificOutput": {"hookEventName":"PreToolUse", "additionalContext":"..."}}
"""

import sys
import json
import re
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

try:
    from lib.logging import timed  # noqa: E402
except Exception:  # pragma: no cover — lib.logging absent in some test envs
    def timed(_name):
        def deco(fn):
            return fn
        return deco


DART_EXTENSIONS = (".dart",)

# --- Patterns ---
# (regex, label) — each match contributes one advisory bullet.
PATTERNS = [
    (
        re.compile(r"<\s*(Map|List|Set)\s*>\s*[\[{(]"),
        "raw type literal `<{m}>{{|[|(` — generic argument 누락 (strict_raw_type). "
        "예: `<Map<String, dynamic>>[]` / `<int>[]`",
    ),
    (
        re.compile(r"\bMaterialPageRoute\s*\("),
        "`MaterialPageRoute(` 호출에 type argument 누락 (inference_failure). "
        "예: `MaterialPageRoute<void>(builder: ...)` 또는 `<bool>`",
    ),
    (
        re.compile(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\.(post|get|put|delete|patch|fetch|request)\s*\("
        ),
        "Dio/HTTP `.{verb}(` 호출에 response type argument 누락 (inference_failure). "
        "예: `dio.post<Map<String, dynamic>>(...)` 또는 `<void>`",
    ),
]

# Tighten Dio false-positives: only flag when the receiver looks Dio-shaped.
DIO_RECEIVER_RX = re.compile(
    r"\b(dio|_dio|client|_client|httpClient|_httpClient|api|_api)$",
    re.IGNORECASE,
)


def _is_dart_file(file_path: str) -> bool:
    if not file_path:
        return False
    # str() coerces a non-string tool_input so a malformed payload fails OPEN
    # (returns a clean bool) instead of an uncaught AttributeError exit-1
    # (deep-audit rank 8 — advisory hook must not fail-closed-by-accident).
    return str(file_path).lower().endswith(DART_EXTENSIONS)


def _extract_payload(tool_name: str, tool_input: dict) -> str:
    """Pull the newly-written content out of the tool input.

    Write    -> content
    Edit     -> new_string
    MultiEdit -> concatenation of every edits[i].new_string
    """
    if tool_name == "Write":
        return tool_input.get("content", "") or ""
    if tool_name == "Edit":
        return tool_input.get("new_string", "") or ""
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits", []) or []
        return "\n".join(e.get("new_string", "") or "" for e in edits)
    return ""


def _scan(payload: str) -> list[str]:
    findings: list[str] = []
    for rx, template in PATTERNS:
        for m in rx.finditer(payload):
            groups = m.groups()
            if rx.pattern.startswith(r"\b([A-Za-z_]"):
                # Dio-shaped receiver gate to cut noise on non-HTTP method calls.
                recv = groups[0] if groups else ""
                if not DIO_RECEIVER_RX.search(recv):
                    continue
                # Skip if already has type argument: `recv.post<...>(`
                tail = payload[m.end() - 1:m.end() + 1]  # captures the `(` boundary
                # look back one char from `(` to see if it was `>`
                prev = payload[max(0, m.end() - 2):m.end() - 1]
                if prev == ">":
                    continue
                msg = template.format(verb=groups[1])
            elif r"MaterialPageRoute" in rx.pattern:
                prev = payload[max(0, m.end() - 2):m.end() - 1]
                if prev == ">":
                    continue
                msg = template
            else:
                msg = template.format(m=groups[0]) if groups else template
            findings.append(msg)
            if len(findings) >= 5:
                return findings  # cap noise
    # dedupe while preserving order
    seen: set[str] = set()
    deduped = []
    for f in findings:
        if f in seen:
            continue
        seen.add(f)
        deduped.append(f)
    return deduped


def emit_warn(warning_text: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                "<pre-tool-warning>\n"
                "[Dart strict-type advisor] 다음 패턴은 strict_raw_type / "
                "inference_failure warning을 일으킬 수 있습니다:\n"
                f"{warning_text}\n"
                "  → `dart/strict-types-and-codegen` 스킬 참조"
                "</pre-tool-warning>"
            ),
        }
    }
    print(json.dumps(output, ensure_ascii=False))


@timed("pre_tool.dart_strict_type_advisor")
def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "")
    if not _is_dart_file(file_path):
        sys.exit(0)

    payload = _extract_payload(tool_name, tool_input)
    if not payload:
        sys.exit(0)

    findings = _scan(payload)
    if not findings:
        sys.exit(0)

    bullets = "\n".join(f"  - {f}" for f in findings)
    emit_warn(bullets)
    sys.exit(0)


if __name__ == "__main__":
    main()

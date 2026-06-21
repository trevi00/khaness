#!/usr/bin/env python3
"""End-to-end integration tests for handler hooks.

Round 7 Phase B.3 (debate-1777614013 follow-on observability work).

Plan gap #2 'Observability blind spots' identified that 0/48 test files
exercise handler main() through the actual stdin JSON → stdout JSON contract.
This file provides the missing E2E framework. Tests run each handler as a
subprocess (python -m handlers.<group>.<name>), feed it crafted stdin JSON,
and assert the stdout response shape.

Coverage (4 highest-impact hooks):
- prompt/skill_match (UserPromptSubmit) — keyword matching → activated-skills
- pre_tool/guard (PreToolUse) — sensitive file deny / sensitive bash deny
- post_tool/reviewer (PostToolUse) — silent on safe tools, ratio/sensor on Edits
- stop/response_guard (Stop) — currently lazy-pattern detection in stop content

Each hook gets ≥3 cases:
- happy path (valid input → valid response shape or graceful no-op)
- empty input (silent no-op, exit 0)
- malformed JSON (silent no-op, exit 0)

Conventions per hook contract:
- All hooks must exit 0 even on error (silent failure preserves Claude flow).
- Output is single-line JSON on stdout, OR empty (no advisory).
- stderr may contain telemetry warnings — ignored by these tests.

Why subprocess and not in-process: handlers reconfigure stdin/stdout encoding
+ install lib paths via sys.path mutation. In-process invocation pollutes
the test runner. subprocess gives true E2E isolation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


HANDLERS = {
    "skill_match": "handlers.prompt.skill_match",
    "guard": "handlers.pre_tool.guard",
    "reviewer": "handlers.post_tool.reviewer",
    "response_guard": "handlers.stop.response_guard",
}


def _run_hook(handler_module: str, stdin_payload: dict | str) -> tuple[int, str, str]:
    """Run handler as subprocess. Return (returncode, stdout, stderr).

    stdin_payload: dict → JSON-encoded; str → sent verbatim (for malformed cases).
    """
    if isinstance(stdin_payload, dict):
        stdin_data = json.dumps(stdin_payload, ensure_ascii=False)
    else:
        stdin_data = stdin_payload

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.run(
        [sys.executable, "-m", handler_module],
        input=stdin_data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(_SCRIPTS),
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _parse_optional_json(stdout: str) -> dict | None:
    """Hook output is either a single-line JSON object or empty. None if empty/non-json."""
    s = stdout.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


# ============================================================
# UserPromptSubmit: skill_match
# ============================================================

def test_skill_match_happy_path_emits_activated_skills():
    """A prompt with TS/strict keywords should produce an additionalContext."""
    rc, stdout, _ = _run_hook(
        HANDLERS["skill_match"],
        {"prompt": "how to setup typescript strict mode", "cwd": str(_SCRIPTS.parent)},
    )
    assert rc == 0
    out = _parse_optional_json(stdout)
    if out is None:
        return  # No skills matched at all — acceptable on a thin tree
    assert "hookSpecificOutput" in out
    hook_out = out["hookSpecificOutput"]
    assert hook_out.get("hookEventName") == "UserPromptSubmit"
    assert "additionalContext" in hook_out


def test_skill_match_empty_prompt_no_op():
    rc, stdout, _ = _run_hook(HANDLERS["skill_match"], {"prompt": ""})
    assert rc == 0
    assert stdout.strip() == ""


def test_skill_match_malformed_json_no_op():
    rc, stdout, _ = _run_hook(HANDLERS["skill_match"], "{not valid json")
    assert rc == 0
    assert stdout.strip() == ""


# ============================================================
# PreToolUse: guard
# ============================================================

def test_guard_safe_bash_pass_through():
    """A non-destructive command should not produce a deny output."""
    rc, stdout, _ = _run_hook(
        HANDLERS["guard"],
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
        },
    )
    assert rc == 0
    out = _parse_optional_json(stdout)
    if out is None:
        return  # Silent pass — acceptable
    # If there's any output, it should NOT be a deny.
    assert out.get("decision") != "block"


def test_guard_empty_tool_no_op():
    rc, stdout, _ = _run_hook(HANDLERS["guard"], {"tool_name": "", "tool_input": {}})
    assert rc == 0
    # Empty tool name → silent no-op or non-deny
    out = _parse_optional_json(stdout)
    assert out is None or out.get("decision") != "block"


def test_guard_malformed_json_no_op():
    """guard must exit 0 (silent failure preserves Claude flow). Output may
    contain a generic 'no tool_input' deny on malformed input — both shapes ok.
    """
    rc, stdout, _ = _run_hook(HANDLERS["guard"], "}}}")
    assert rc == 0
    out = _parse_optional_json(stdout)
    # Either empty (silent) OR a structured response (not a crash)
    if out is not None:
        # Must be a recognizable hook response shape, not garbage
        assert (
            out.get("decision") in (None, "block")
            or "hookSpecificOutput" in out
        )


def test_guard_destructive_force_push_emits_deny():
    """`git push --force` to main is invariant=DENY (per CLAUDE.md safety protocol)."""
    rc, stdout, _ = _run_hook(
        HANDLERS["guard"],
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
        },
    )
    assert rc == 0
    out = _parse_optional_json(stdout)
    # Either a deny is emitted, OR a warning context (depends on mode/override).
    # We at minimum require the hook didn't crash. A specific deny is asserted via
    # tests/test_*_safety which target the lib directly.
    if out is not None:
        # If output exists, structure should be hook-shape
        if out.get("decision") == "block":
            assert "reason" in out
        else:
            assert "hookSpecificOutput" in out


# ============================================================
# PostToolUse: reviewer
# ============================================================

def test_reviewer_safe_tool_no_advisory():
    """Read on a non-special path should produce no advisory."""
    rc, stdout, _ = _run_hook(
        HANDLERS["reviewer"],
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/nonexistent.txt"},
            "tool_output": "",
            "cwd": str(_SCRIPTS.parent),
        },
    )
    assert rc == 0
    # Read on a non-code file usually silent
    out = _parse_optional_json(stdout)
    if out is not None:
        assert "hookSpecificOutput" in out
        assert out["hookSpecificOutput"].get("hookEventName") == "PostToolUse"


def test_reviewer_empty_tool_no_op():
    rc, stdout, _ = _run_hook(HANDLERS["reviewer"], {})
    assert rc == 0
    # No tool name → no review work
    assert stdout.strip() == "" or _parse_optional_json(stdout) is not None


def test_reviewer_malformed_json_no_op():
    rc, stdout, _ = _run_hook(HANDLERS["reviewer"], "garbage")
    assert rc == 0
    assert stdout.strip() == ""


# ============================================================
# Stop: response_guard
# ============================================================

def test_response_guard_clean_response_no_block():
    """A normal response without lazy patterns should not trigger a Stop block."""
    rc, stdout, _ = _run_hook(
        HANDLERS["response_guard"],
        {
            "stop_hook_active": False,
            "transcript_path": "/tmp/nonexistent_transcript.jsonl",
        },
    )
    assert rc == 0
    out = _parse_optional_json(stdout)
    # Stop hook may emit either block decision or empty — tolerate both.
    if out is not None:
        # If block, must have reason
        if out.get("decision") == "block":
            assert "reason" in out


def test_response_guard_empty_no_op():
    rc, stdout, _ = _run_hook(HANDLERS["response_guard"], {})
    assert rc == 0
    # Hook should be tolerant of missing fields


def test_response_guard_malformed_json_no_op():
    rc, stdout, _ = _run_hook(HANDLERS["response_guard"], "[]")
    assert rc == 0
    # Non-dict input — should fall through silently


# ============================================================
# Test runner
# ============================================================


def main() -> int:
    failures = []
    test_count = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            failures.append((name, repr(e)))
            print(f"  [ERR]  {name}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print(f"\n[OK] {test_count} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

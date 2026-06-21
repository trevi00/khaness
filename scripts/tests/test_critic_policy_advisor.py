#!/usr/bin/env python3
"""Tests for handlers/pre_tool/critic_policy_advisor.py (v15.10 wiring W2).

Coverage:
  - Non-Agent tool → silent (no stdout JSON).
  - Agent (invoke-list default) → additionalContext mentions 'invoke'.
  - Agent (skip-list default) → additionalContext mentions 'skip'.
  - Unknown agent → defaults to 'invoke' (conservative).
  - Hook is fail-soft on malformed stdin.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_HOOK = _SCRIPTS / "handlers" / "pre_tool" / "critic_policy_advisor.py"


def _invoke(payload, *, claude_home: Path,
            raw_input: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_HOME"] = str(claude_home)
    env.pop("ORCH_CRITIC_DECISION", None)
    input_text = raw_input if raw_input is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=15,
    )


def test_non_agent_tool_is_silent():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td)
        res = _invoke(
            {"tool_name": "Read", "tool_input": {"file_path": "x"}},
            claude_home=ch,
        )
        assert res.returncode == 0
        assert res.stdout == ""


def test_invoke_list_agent_advises_invoke():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-planner",
                "prompt": "x",
            },
            "session_id": "s",
        }
        res = _invoke(payload, claude_home=ch)
        assert res.returncode == 0
        parsed = json.loads(res.stdout)
        ctx = parsed["hookSpecificOutput"]["additionalContext"]
        assert "harness-planner" in ctx
        assert "invoke" in ctx
        assert "v15.10 D4" in ctx


def test_skip_list_agent_advises_skip():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "Explore",
                "prompt": "x",
            },
            "session_id": "s",
        }
        res = _invoke(payload, claude_home=ch)
        assert res.returncode == 0
        parsed = json.loads(res.stdout)
        ctx = parsed["hookSpecificOutput"]["additionalContext"]
        assert "skip" in ctx


def test_unknown_agent_defaults_to_invoke():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "totally-unknown-xyz",
                "prompt": "x",
            },
        }
        res = _invoke(payload, claude_home=ch)
        assert res.returncode == 0
        parsed = json.loads(res.stdout)
        ctx = parsed["hookSpecificOutput"]["additionalContext"]
        assert "invoke" in ctx


def test_fail_soft_on_garbage_stdin():
    with tempfile.TemporaryDirectory() as td:
        ch = Path(td)
        res = _invoke({}, claude_home=ch, raw_input="not-json")
        assert res.returncode == 0
        # Empty stdout is OK; no crash is the contract
        assert res.stdout in ("",)


TESTS = [
    test_non_agent_tool_is_silent,
    test_invoke_list_agent_advises_invoke,
    test_skip_list_agent_advises_skip,
    test_unknown_agent_defaults_to_invoke,
    test_fail_soft_on_garbage_stdin,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Tests for handlers/post_tool/agent_invocation_audit.py — platform-level
Agent dispatch audit log hook.

The hook runs as a subprocess invoked by Claude Code's PostToolUse channel.
Tests fork a subprocess with the hook script + craft hook-input JSON on
stdin, then assert the resulting state/subagent_invocations/<sid>.jsonl
shape.
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

_HOOK = _SCRIPTS / "handlers" / "post_tool" / "agent_invocation_audit.py"


def _invoke_hook(payload: dict, *, env_overrides: dict | None = None,
                 claude_home: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Strip any inherited ORCH_SID so tests start clean
    env.pop("ORCH_SID", None)
    if claude_home is not None:
        env["CLAUDE_HOME"] = str(claude_home)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def _read_invocations(claude_home: Path) -> list[dict]:
    log_dir = claude_home / "state" / "subagent_invocations"
    if not log_dir.exists():
        return []
    out: list[dict] = []
    for jsonl in sorted(log_dir.glob("*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def test_hook_records_agent_invocation_with_sid_in_prompt():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-critic",
                "prompt": "Review proposal for debate-1778500000-abc123 generation 2.",
            },
            "tool_response": {"ok": True},
            "session_id": "test-session-001",
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0, f"hook failed: {proc.stderr}"
        records = _read_invocations(home)
        assert len(records) == 1
        rec = records[0]
        assert rec["sid"] == "debate-1778500000-abc123"
        assert rec["agent"] == "harness-critic"
        assert rec["role"] == "post-tool-hook"
        assert rec["extra"]["auto_recorded"] is True


def test_hook_uses_orch_sid_env_when_present():
    """ORCH_SID env var beats prompt-grep — autopilot super-session
    propagates this to every child Agent."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-planner",
                # Prompt contains a different sid; env should win
                "prompt": "Build proposal — sid debate-1778600000-xyz999",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(
            payload,
            env_overrides={"ORCH_SID": "orch-1778700000-aabbcc"},
            claude_home=home,
        )
        assert proc.returncode == 0
        records = _read_invocations(home)
        assert len(records) == 1
        assert records[0]["sid"] == "orch-1778700000-aabbcc"


def test_hook_falls_back_to_unknown_sha_when_no_sid():
    """No env, no sid prefix in prompt → fallback to unknown-<sha8>."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-evaluator",
                "prompt": "Evaluate something with no session id at all.",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        records = _read_invocations(home)
        assert len(records) == 1
        assert records[0]["sid"].startswith("unknown-")
        # sha8 = 8 hex chars
        assert len(records[0]["sid"]) == len("unknown-") + 8


def test_hook_skips_non_agent_tools():
    """matcher='Agent' is in settings.json but hook also defends in code."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_response": {"stdout": ""},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        # No state/subagent_invocations/ dir created
        assert not (home / "state" / "subagent_invocations").exists()


def test_hook_skips_when_subagent_type_missing():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {"prompt": "no subagent_type field"},
            "tool_response": {},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        assert not (home / "state" / "subagent_invocations").exists()


def test_hook_handles_malformed_stdin():
    """Garbage stdin → fail-soft, exit 0, no log."""
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0


def test_hook_handles_empty_stdin():
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0


def test_hook_resolves_tools_from_frontmatter():
    """The hook should populate `tools` field from agents/<name>.md
    frontmatter via expected_tools(), not from anything in tool_input."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-critic",
                "prompt": "debate-1778900000-toolchk",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        records = _read_invocations(home)
        assert len(records) == 1
        # harness-critic frontmatter declares Read, Grep, Glob, WebFetch
        assert "WebFetch" in records[0]["tools"]
        assert "Read" in records[0]["tools"]


def test_hook_records_silent_no_stdout():
    """Hook is silent — audit log is observability, not user-visible feedback."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-planner",
                "prompt": "debate-1778100000-silent",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.stdout == ""


def test_hook_extracts_team_single_hyphen_sid():
    """team-<ts> format (no rand suffix) — D1 closure 2026-05-10."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-explore",
                "prompt": "Help with team-1778500000 review",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        records = _read_invocations(home)
        assert len(records) == 1
        assert records[0]["sid"] == "team-1778500000"


def test_hook_extracts_allsolution_single_hyphen_sid():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-researcher",
                "prompt": "research for allsolution-1778600000 phase B",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        records = _read_invocations(home)
        assert records[0]["sid"] == "allsolution-1778600000"


def test_hook_extracts_ultrawork_single_hyphen_sid():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-explore",
                "prompt": "ultrawork-1778700000 wave 1",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        records = _read_invocations(home)
        assert records[0]["sid"] == "ultrawork-1778700000"


def test_hook_records_origin_field_as_hook():
    """D4 closure 2026-05-10: hook-emitted records carry origin='hook' so
    post-hoc grep can split hook vs directive surfaces."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-critic",
                "prompt": "debate-1778800000-origin1",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        rec = _read_invocations(home)[0]
        assert rec["extra"]["origin"] == "hook"
        assert rec["extra"]["auto_recorded"] is True


def test_hook_explicit_sid_label_beats_prefix_grep():
    """E7 closure 2026-05-10: explicit `sid: <X>` label wins over prefix grep
    so a caller can disambiguate when prompt mentions multiple sids."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-evaluator",
                "prompt": (
                    "sid: orch-1779000000-explicit\n"
                    "Reference: debate-1778900000-other generation 2."
                ),
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        rec = _read_invocations(home)[0]
        assert rec["sid"] == "orch-1779000000-explicit"


def test_hook_explicit_sid_label_with_equals_form():
    """sid=<X> equals-form is also accepted (E7)."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-planner",
                "prompt": "sid=debate-1779100000-eq001 generate proposal",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        rec = _read_invocations(home)[0]
        assert rec["sid"] == "debate-1779100000-eq001"


def test_hook_explicit_sid_label_rejects_path_traversal():
    """An explicit `sid: ../escape` label should NOT be honored — it must
    fail the path-traversal guard and fall through to prefix grep / sha8."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-architect",
                "prompt": "sid: ../escape but mention debate-1779200000-good",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        rec = _read_invocations(home)[0]
        # Falls through to prefix grep
        assert rec["sid"] == "debate-1779200000-good"


def test_hook_handles_oversized_prompt_within_cap():
    """E11 closure 2026-05-10: 2 MiB prompt should not slow the hook
    significantly — head+tail truncation applies to sha8 hashing path.
    We just assert the hook completes and records something."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        big_payload = "X" * (2 * 1024 * 1024)  # 2 MiB
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-explore",
                "prompt": big_payload,  # No sid mentioned → fallback path
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        rec = _read_invocations(home)[0]
        # No sid in prompt → unknown-<sha8> fallback
        assert rec["sid"].startswith("unknown-")


def test_hook_origin_uses_lib_constant_value():
    """The origin field must equal the value of ORIGIN_HOOK exported from
    lib.subagent_invocation_log — pins E8 centralization (no string drift
    between hook + lib)."""
    from lib.subagent_invocation_log import ORIGIN_HOOK
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-critic",
                "prompt": "debate-1779300000-pin001",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        rec = _read_invocations(home)[0]
        assert rec["extra"]["origin"] == ORIGIN_HOOK


def test_hook_dual_hyphen_prefix_takes_priority_over_single():
    """When prompt contains both 'debate-<ts>-<rand>' AND a bare
    'team-<ts>' substring, the dual-hyphen variant should win because it
    appears first alphabetically in the alternation. This pins the
    determinism contract — operators relying on the prefix grep should
    get the most-specific match."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-architect",
                "prompt": "debate-1778900000-priority team-1778900000 both present",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        rec = _read_invocations(home)[0]
        # Prefer the dual-hyphen variant (more specific, harder to false-match)
        assert rec["sid"] == "debate-1778900000-priority"


def test_hook_rejects_path_traversal_in_extracted_sid():
    """The sid prefix regex refuses path-traversal characters by
    construction. A prompt with ../escape after a valid prefix should
    NOT match, so we fall back to unknown-sha (no exception)."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "harness-architect",
                "prompt": "debate-../../etc/passwd-bad something",
            },
            "tool_response": {"ok": True},
        }
        proc = _invoke_hook(payload, claude_home=home)
        assert proc.returncode == 0
        records = _read_invocations(home)
        assert len(records) == 1
        assert records[0]["sid"].startswith("unknown-")


TESTS = [
    test_hook_records_agent_invocation_with_sid_in_prompt,
    test_hook_uses_orch_sid_env_when_present,
    test_hook_falls_back_to_unknown_sha_when_no_sid,
    test_hook_skips_non_agent_tools,
    test_hook_skips_when_subagent_type_missing,
    test_hook_handles_malformed_stdin,
    test_hook_handles_empty_stdin,
    test_hook_resolves_tools_from_frontmatter,
    test_hook_records_silent_no_stdout,
    test_hook_extracts_team_single_hyphen_sid,
    test_hook_extracts_allsolution_single_hyphen_sid,
    test_hook_extracts_ultrawork_single_hyphen_sid,
    test_hook_records_origin_field_as_hook,
    test_hook_explicit_sid_label_beats_prefix_grep,
    test_hook_explicit_sid_label_with_equals_form,
    test_hook_explicit_sid_label_rejects_path_traversal,
    test_hook_handles_oversized_prompt_within_cap,
    test_hook_origin_uses_lib_constant_value,
    test_hook_dual_hyphen_prefix_takes_priority_over_single,
    test_hook_rejects_path_traversal_in_extracted_sid,
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

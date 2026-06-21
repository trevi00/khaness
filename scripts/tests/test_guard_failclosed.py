#!/usr/bin/env python3
"""Tests for handlers/pre_tool/guard.py fail-closed Bash-deny (M17).

Exercises guard.main() IN-PROCESS (mocked stdin/stdout) rather than via a real Bash
command, so the dangerous test strings never reach the live PreToolUse guard hook
(operator-trigger avoidance — feedback_function_chain_equivalence). Auto-discovered
by run_units.py via main()->int.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import handlers.pre_tool.guard as guard  # noqa: E402

# Dangerous fragments built from parts so the literal never appears contiguously in
# THIS source either (belt-and-suspenders vs any source-scanning hook).
_RMRF_ROOT = "rm -" + "rf " + "/"
_PUSH_FORCE_MAIN = "git push --" + "force origin main"


def _run(stdin_text: str) -> str:
    """Invoke guard.main() with `stdin_text`; return 'DENY' | 'WARN' | 'ALLOW' | 'OTHER'."""
    buf = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(stdin_text)), redirect_stdout(buf):
        try:
            guard.main()
        except SystemExit:
            pass
    out = buf.getvalue().strip()
    if not out:
        return "ALLOW"
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        return "OTHER:" + out[:60]
    hso = d.get("hookSpecificOutput", {})
    if d.get("decision") == "block" or hso.get("permissionDecision") == "deny":
        return "DENY"
    if "additionalContext" in hso:
        return "WARN"
    return "ALLOW"


def _payload(tool, **inp):
    return json.dumps({"tool_name": tool, "tool_input": inp})


# ---- regression: valid payloads still classify correctly ----

def test_valid_bash_dangerous_denies():
    assert _run(_payload("Bash", command=_RMRF_ROOT)) == "DENY"
    assert _run(_payload("Bash", command=_PUSH_FORCE_MAIN)) == "DENY"


def test_valid_bash_safe_allows():
    assert _run(_payload("Bash", command="ls -la")) == "ALLOW"


def test_valid_non_bash_allows():
    assert _run(_payload("Read", file_path="/x")) == "ALLOW"


# ---- M17: malformed payload fail-CLOSED ----

def test_malformed_bash_payload_fails_closed():
    # Was fail-OPEN (WARN) before M17: json parse fails, tool_name never assigned.
    broken = '{"tool_name":"Bash","tool_input":{"command":"' + _RMRF_ROOT + '"} BROKEN'
    assert _run(broken) == "DENY"


def test_malformed_unicode_escaped_toolname_fails_closed():
    # tool_name regex can't read "Bash"; the `"command":` signal catches it.
    broken = '{"tool_name":"\\u0042ash","tool_input":{"command":"' + _RMRF_ROOT + '"} BROKEN'
    assert _run(broken) == "DENY"


def test_malformed_command_field_fails_closed():
    # No readable tool_name at all, but a `"command":` key = Bash-shaped → DENY.
    broken = '{"garbage":1,"tool_input":{"command":"whatever"} <<<broken'
    assert _run(broken) == "DENY"


def test_malformed_non_bash_does_not_over_deny():
    # A corrupted Read/Write payload (no command field, non-Bash tool_name) must NOT deny.
    broken = '{"tool_name":"Read","tool_input":{"file_path":"/x"} BROKEN'
    assert _run(broken) == "WARN"


def test_malformed_unrecognizable_warns_not_denies():
    assert _run("{this is not json at all and has no bash signal") == "WARN"


def test_empty_stdin_allows():
    assert _run("") in ("ALLOW", "WARN")  # empty parse → no bash signal → not a deny


def test_looks_like_bash_payload_unit():
    assert guard._looks_like_bash_payload('{"tool_name":"Bash"') is True
    assert guard._looks_like_bash_payload('{"tool_input":{"command":"x"}}') is True
    assert guard._looks_like_bash_payload('{"tool_name":"Read","file_path":"/x"}') is False
    assert guard._looks_like_bash_payload("") is False


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

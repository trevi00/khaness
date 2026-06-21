#!/usr/bin/env python3
"""Tests for lib.operator_ledger + cli.operator_override (v15.10 D5).

Coverage map (every D5 contract clause hit):
  - project_id_for: deterministic, 12-hex, stable under case on Windows.
  - task_hash_for: deterministic, 16-hex, prompt whitespace + case
    normalization, tool order independence.
  - ledger_path: project-scoped + agent-segregated.
  - header_path written on first append; not overwritten subsequently.
  - append_record: defaults applied, file created, JSONL append-only.
  - append_record emits ledger.verification_gap when self_only +
    downstream_used=true.
  - append_record DOES NOT emit when verification is good.
  - read_records: yields appended records in order; malformed lines skipped.
  - apply_override: requires token, rejects bad action / empty reason.
  - apply_override: persists record with human_override payload.
  - CLI: missing args → exit 2; wrong token → exit 3; happy path → exit 0.
"""
from __future__ import annotations

import json
import sys
import tempfile
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import operator_ledger as OL  # noqa: E402
from cli.operator_override import main as cli_main  # noqa: E402


def _redirect_ledger_root(tmp: Path) -> Path:
    OL.LEDGER_ROOT = tmp / "operator-ledger"
    return OL.LEDGER_ROOT


def _captured_emit():
    events: list[tuple[str, dict]] = []
    def emit(t: str, p: dict) -> None:
        events.append((t, dict(p)))
    return events, emit


# ---- ID + hash helpers ----------------------------------------------------------

def test_project_id_is_deterministic_12_hex():
    pid1 = OL.project_id_for("C:/proj/alpha")
    pid2 = OL.project_id_for("C:/proj/alpha")
    assert pid1 == pid2
    assert len(pid1) == 12
    assert all(c in "0123456789abcdef" for c in pid1)


def test_project_id_differs_across_roots():
    assert OL.project_id_for("C:/proj/alpha") != OL.project_id_for("C:/proj/beta")


def test_project_id_case_collapse_on_windows():
    """If running on nt the upper/lower variants must collide; on POSIX they differ."""
    pid_lower = OL.project_id_for("C:/proj/alpha")
    pid_upper = OL.project_id_for("C:/PROJ/ALPHA")
    import os as _os
    if _os.name == "nt":
        assert pid_lower == pid_upper
    else:
        assert pid_lower != pid_upper


def test_task_hash_is_deterministic_16_hex():
    h = OL.task_hash_for("C:/proj", "fix bug", ["Read", "Grep"])
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)
    assert h == OL.task_hash_for("C:/proj", "fix bug", ["Read", "Grep"])


def test_task_hash_normalizes_whitespace_and_case():
    a = OL.task_hash_for("C:/proj", "Fix   THE  Bug", ["Read"])
    b = OL.task_hash_for("C:/proj", "fix the bug",     ["Read"])
    assert a == b


def test_task_hash_is_tool_order_independent():
    a = OL.task_hash_for("C:/proj", "x", ["Bash", "Read", "Grep"])
    b = OL.task_hash_for("C:/proj", "x", ["Grep", "Bash", "Read"])
    assert a == b


def test_task_hash_changes_with_tool_set():
    a = OL.task_hash_for("C:/proj", "x", ["Read"])
    b = OL.task_hash_for("C:/proj", "x", ["Read", "Bash"])
    assert a != b


# ---- path helpers ---------------------------------------------------------------

def test_ledger_path_layout():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        path = OL.ledger_path("C:/proj/alpha", "researcher")
        assert path.parent.parent.name == "operator-ledger"
        assert path.parent.name == OL.project_id_for("C:/proj/alpha")
        assert path.name == "researcher.jsonl"


def test_ledger_path_rejects_empty_agent():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        try:
            OL.ledger_path("C:/proj", "")
        except ValueError:
            pass
        else:
            raise AssertionError("empty agent_type must raise ValueError")


# ---- append_record + header -----------------------------------------------------

def test_append_record_creates_header_and_file():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        path = OL.append_record(
            "C:/proj/alpha", "researcher",
            {"parent_sid": "sid-1", "task_hash": "ab" * 8, "success": True},
        )
        assert path.exists()
        header = OL.header_path("C:/proj/alpha")
        assert header.exists()
        header_text = header.read_text(encoding="utf-8")
        assert "project_id" in header_text
        assert OL.project_id_for("C:/proj/alpha") in header_text


def test_header_not_overwritten_on_subsequent_appends():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        OL.append_record("C:/proj", "r", {"parent_sid": "s"})
        hp = OL.header_path("C:/proj")
        first_mtime = hp.stat().st_mtime_ns
        OL.append_record("C:/proj", "r", {"parent_sid": "s2"})
        assert hp.stat().st_mtime_ns == first_mtime


def test_append_record_applies_defaults():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        OL.append_record("C:/proj", "r", {"parent_sid": "s"})
        records = list(OL.read_records("C:/proj", "r"))
        assert len(records) == 1
        rec = records[0]
        assert rec["agent_type"] == "r"
        assert rec["failure_modes"] == []
        assert rec["success"] is False
        assert rec["verified_by"] == "self_only"
        assert rec["downstream_used"] is False
        assert rec["retry_count"] == 0
        assert "ts" in rec


def test_append_record_emits_verification_gap_when_self_only_downstream_true():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        events, emit = _captured_emit()
        OL.append_record(
            "C:/proj", "researcher",
            {
                "parent_sid": "s",
                "task_hash": "00" * 8,
                "verified_by": "self_only",
                "downstream_used": True,
            },
            emit_fn=emit,
        )
        gaps = [e for e in events if e[0] == "ledger.verification_gap"]
        assert len(gaps) == 1
        assert gaps[0][1]["agent_type"] == "researcher"


def test_append_record_no_gap_when_verified_by_evidence_validator():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        events, emit = _captured_emit()
        OL.append_record(
            "C:/proj", "researcher",
            {
                "verified_by": "evidence_validator",
                "downstream_used": True,
            },
            emit_fn=emit,
        )
        assert not any(e[0] == "ledger.verification_gap" for e in events)


def test_append_record_no_gap_when_downstream_unused():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        events, emit = _captured_emit()
        OL.append_record(
            "C:/proj", "researcher",
            {
                "verified_by": "self_only",
                "downstream_used": False,
            },
            emit_fn=emit,
        )
        assert not any(e[0] == "ledger.verification_gap" for e in events)


def test_append_record_agent_type_mismatch_raises():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        try:
            OL.append_record("C:/proj", "researcher", {"agent_type": "executor"})
        except ValueError as e:
            assert "contradicts" in str(e)
        else:
            raise AssertionError("agent_type mismatch must raise")


def test_read_records_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        OL.append_record("C:/proj", "r", {"parent_sid": "s1"})
        path = OL.ledger_path("C:/proj", "r")
        # Corrupt one line by appending non-JSON garbage
        with path.open("a", encoding="utf-8") as f:
            f.write("not valid json\n")
        OL.append_record("C:/proj", "r", {"parent_sid": "s2"})
        records = list(OL.read_records("C:/proj", "r"))
        assert len(records) == 2
        assert records[0]["parent_sid"] == "s1"
        assert records[1]["parent_sid"] == "s2"


# ---- apply_override -------------------------------------------------------------

def test_apply_override_wrong_token_raises_permission_error():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        try:
            OL.apply_override(
                "C:/proj", "researcher", "force_close",
                reason="ops", token="apply-user-preference",
            )
        except PermissionError as e:
            assert "configure-critic-policy" in str(e)
        else:
            raise AssertionError("wrong token must raise PermissionError")


def test_apply_override_invalid_action_raises():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        try:
            OL.apply_override(
                "C:/proj", "researcher", "bogus",
                reason="ops", token="configure-critic-policy",
            )
        except ValueError as e:
            assert "action" in str(e)
        else:
            raise AssertionError("invalid action must raise ValueError")


def test_apply_override_empty_reason_raises():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        try:
            OL.apply_override(
                "C:/proj", "researcher", "force_close",
                reason="   ", token="configure-critic-policy",
            )
        except ValueError as e:
            assert "reason" in str(e)
        else:
            raise AssertionError("empty reason must raise ValueError")


def test_apply_override_persists_human_override_payload():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        events, emit = _captured_emit()
        OL.apply_override(
            "C:/proj", "researcher", "skip_critic_once",
            reason="off-by-one diagnostic",
            token="configure-critic-policy",
            emit_fn=emit,
        )
        records = list(OL.read_records("C:/proj", "researcher"))
        assert len(records) == 1
        ho = records[0]["human_override"]
        assert ho is not None
        assert ho["action"] == "skip_critic_once"
        assert ho["reason"] == "off-by-one diagnostic"
        assert ho["token"] == "configure-critic-policy"
        assert any(e[0] == "ledger.human_override" for e in events)


# ---- CLI ------------------------------------------------------------------------

def test_cli_missing_args_returns_2():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        err = StringIO()
        with redirect_stderr(err):
            rc = cli_main([])
        assert rc == 2


def test_cli_wrong_token_returns_3():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        err = StringIO()
        with redirect_stderr(err):
            rc = cli_main([
                "--agent", "researcher",
                "--action", "force_close",
                "--reason", "test",
                "--token", "wrong",
                "--project-root", td,
            ])
        assert rc == 3
        assert "PermissionError" in err.getvalue() or "configure-critic-policy" in err.getvalue()


def test_cli_happy_path_returns_0_and_appends():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ledger_root(Path(td))
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main([
                "--agent", "researcher",
                "--action", "force_close",
                "--reason", "ops drained queue",
                "--token", "configure-critic-policy",
                "--project-root", td,
            ])
        assert rc == 0
        assert "appended override" in out.getvalue()
        records = list(OL.read_records(td, "researcher"))
        assert len(records) == 1
        assert records[0]["human_override"]["action"] == "force_close"


TESTS = [
    test_project_id_is_deterministic_12_hex,
    test_project_id_differs_across_roots,
    test_project_id_case_collapse_on_windows,
    test_task_hash_is_deterministic_16_hex,
    test_task_hash_normalizes_whitespace_and_case,
    test_task_hash_is_tool_order_independent,
    test_task_hash_changes_with_tool_set,
    test_ledger_path_layout,
    test_ledger_path_rejects_empty_agent,
    test_append_record_creates_header_and_file,
    test_header_not_overwritten_on_subsequent_appends,
    test_append_record_applies_defaults,
    test_append_record_emits_verification_gap_when_self_only_downstream_true,
    test_append_record_no_gap_when_verified_by_evidence_validator,
    test_append_record_no_gap_when_downstream_unused,
    test_append_record_agent_type_mismatch_raises,
    test_read_records_skips_malformed_lines,
    test_apply_override_wrong_token_raises_permission_error,
    test_apply_override_invalid_action_raises,
    test_apply_override_empty_reason_raises,
    test_apply_override_persists_human_override_payload,
    test_cli_missing_args_returns_2,
    test_cli_wrong_token_returns_3,
    test_cli_happy_path_returns_0_and_appends,
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

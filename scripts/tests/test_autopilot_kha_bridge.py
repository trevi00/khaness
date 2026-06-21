#!/usr/bin/env python3
"""Tests for lib.autopilot_kha_bridge (Wave 15).

Per converged debate session debate-1779314852-338b28 (4-LOCK
byte-identical gen2→gen3 sha1 dc809a9257f23c472212ce55d426fdccb039624b):

  (a) emit_bridge_dispatch dual-emit ordering — EventStore canonical
      written first, phase_events projection after
  (b) emit input validation rejects empty sid / phase / plan / bad mode
  (c) build_completed_tasks_table parses kha-executor commit subject
      shape `{type}({phase}-{plan}): <desc>` per kha-executor.md:370-375
      and emits CHECKPOINT-format table per kha-executor.md:281-313
  (d) detect_orphan_and_escalate returns False on (no commits) and on
      (commits + SUMMARY.md present), True on (commits + no SUMMARY.md);
      on True path advisory acked AND phase_event status=escalated written
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


def _reset_state_modules() -> None:
    """Drop cached modules so STATE_DIR reflects current CLAUDE_HOME env."""
    for m in list(sys.modules):
        if m.startswith(("lib.paths", "lib.event_store", "lib.phase_events",
                         "lib.advisory_ack", "lib.autopilot_kha_bridge")):
            del sys.modules[m]


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)


def _git_commit(root: Path, msg: str, file_rel: str, content: str = "x") -> str:
    fp = root / file_rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", file_rel], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg], check=True)
    rc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short=7", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return rc.stdout.strip()


def test_emit_dual_emit_writes_both_streams():
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_HOME"] = td
        _reset_state_modules()
        from lib.autopilot_kha_bridge import emit_bridge_dispatch

        sid = "orch-emit-1"
        rec = emit_bridge_dispatch(sid, gen=2, phase="8.3", plan="01-foo")
        assert rec.orch_sid == sid
        assert rec.phase == "8.3"
        assert rec.plan == "01-foo"
        assert rec.mode == "wrapped"
        assert rec.phase_event_id == "kha-8.3-01-foo"

        ev = Path(td) / "state" / "debates" / sid / "events.jsonl"
        pe = Path(td) / "state" / "orchestrator" / sid / "phase_events.jsonl"
        assert ev.exists(), f"events.jsonl missing at {ev}"
        assert pe.exists(), f"phase_events.jsonl missing at {pe}"

        ev_rec = json.loads(ev.read_text(encoding="utf-8").splitlines()[0])
        assert ev_rec["type"] == "bridge.dispatch"
        assert ev_rec["actor"] == "kha-bridge"
        assert ev_rec["gen"] == 2
        assert ev_rec["payload"]["kha_phase"] == "8.3"
        assert ev_rec["payload"]["kha_plan"] == "01-foo"
        assert ev_rec["payload"]["mode"] == "wrapped"
        assert ev_rec["payload"]["bridge_contract_version"] == "1"

        pe_rec = json.loads(pe.read_text(encoding="utf-8").splitlines()[0])
        assert pe_rec["status"] == "started"
        assert pe_rec["phase_id"] == "kha-8.3-01-foo"
        assert "kha-bridge" in pe_rec["reason"]


def test_emit_input_validation():
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_HOME"] = td
        _reset_state_modules()
        from lib.autopilot_kha_bridge import emit_bridge_dispatch

        for sid, phase, plan in [("", "8.3", "p1"), ("s", "", "p1"), ("s", "8.3", "")]:
            try:
                emit_bridge_dispatch(orch_sid=sid, gen=1, phase=phase, plan=plan)
                raise AssertionError(f"expected ValueError for {(sid, phase, plan)!r}")
            except ValueError:
                pass

        try:
            emit_bridge_dispatch(orch_sid="s", gen=1, phase="8.3", plan="p1", mode="bogus")
            raise AssertionError("expected ValueError for bad mode")
        except ValueError:
            pass


def test_build_completed_tasks_table_parses_commit_shape():
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_HOME"] = td
        _reset_state_modules()
        from lib.autopilot_kha_bridge import build_completed_tasks_table

        root = Path(td)
        _init_git_repo(root)
        h1 = _git_commit(root, "chore(0-init): seed", "README.md", "1")
        h2 = _git_commit(root, "feat(8.3-01): scaffold module", "src/a.py", "2")
        h3 = _git_commit(root, "test(8.3-01): add failing test", "src/b.py", "3")
        h4 = _git_commit(root, "fix(8.3-01): handle null", "src/c.py", "4")
        h5 = _git_commit(root, "feat(8.4-02): other plan", "src/d.py", "5")

        table = build_completed_tasks_table(root, "8.3", "01")
        assert table, "expected non-empty table"
        assert "| Task | Name | Commit | Files |" in table
        # 3 commits matched (8.3-01); 8.4-02 and 0-init excluded.
        # Filter to data rows only (start with "| <digit>"); excludes the
        # markdown separator row "| ---- | ----..." which also begins with "|".
        import re as _re
        rows = [ln for ln in table.splitlines() if _re.match(r"\| \d+ \|", ln)]
        assert len(rows) == 3, f"expected 3 task rows, got {len(rows)}\n{table}"
        assert "scaffold module" in table
        assert "add failing test" in table
        assert "handle null" in table
        assert "other plan" not in table


def test_build_completed_tasks_table_empty_when_no_match():
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_HOME"] = td
        _reset_state_modules()
        from lib.autopilot_kha_bridge import build_completed_tasks_table

        root = Path(td)
        _init_git_repo(root)
        _git_commit(root, "feat(1.0-init): only one", "src/a.py", "1")

        assert build_completed_tasks_table(root, "8.3", "01") == ""


def test_detect_orphan_returns_false_on_no_commits():
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_HOME"] = td
        _reset_state_modules()
        from lib.autopilot_kha_bridge import detect_orphan_and_escalate

        root = Path(td)
        _init_git_repo(root)
        assert detect_orphan_and_escalate(root, "8.3", "01", "orch-1") is False


def test_detect_orphan_returns_false_when_summary_present():
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_HOME"] = td
        _reset_state_modules()
        from lib.autopilot_kha_bridge import detect_orphan_and_escalate

        root = Path(td)
        _init_git_repo(root)
        _git_commit(root, "feat(8.3-01): scaffold", "src/a.py", "1")
        # SUMMARY present under .planning/phases/XX-name/
        summary = root / ".planning" / "phases" / "08-bridge" / "8.3-01-SUMMARY.md"
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text("# done\n", encoding="utf-8")

        assert detect_orphan_and_escalate(root, "8.3", "01", "orch-1") is False


def test_detect_orphan_true_acks_advisory_and_writes_phase_event():
    with tempfile.TemporaryDirectory() as td:
        os.environ["CLAUDE_HOME"] = td
        _reset_state_modules()
        from lib.autopilot_kha_bridge import detect_orphan_and_escalate
        from lib.advisory_ack import resolve as resolve_advisory

        root = Path(td)
        _init_git_repo(root)
        _git_commit(root, "feat(8.3-01): scaffold", "src/a.py", "1")
        _git_commit(root, "test(8.3-01): tests", "src/b.py", "2")
        # NO SUMMARY.md → orphan

        sid = "orch-orphan-1"
        result = detect_orphan_and_escalate(root, "8.3", "01", sid)
        assert result is True

        ack_store = resolve_advisory("aborted_kha_plan_validator_fail")
        keys = ack_store.load()
        assert f"{sid}:8.3:01:orphan" in keys

        pe = Path(td) / "state" / "orchestrator" / sid / "phase_events.jsonl"
        assert pe.exists()
        events = [json.loads(ln) for ln in pe.read_text(encoding="utf-8").splitlines() if ln.strip()]
        escalated = [e for e in events if e.get("status") == "escalated"]
        assert escalated, f"expected status=escalated event, got {events}"
        assert escalated[0]["phase_id"] == "kha-8.3-01"
        assert escalated[0]["reason"] == "orphan_commits_no_summary"


TESTS = [
    test_emit_dual_emit_writes_both_streams,
    test_emit_input_validation,
    test_build_completed_tasks_table_parses_commit_shape,
    test_build_completed_tasks_table_empty_when_no_match,
    test_detect_orphan_returns_false_on_no_commits,
    test_detect_orphan_returns_false_when_summary_present,
    test_detect_orphan_true_acks_advisory_and_writes_phase_event,
]


def main() -> int:
    failed = 0
    saved_home = os.environ.get("CLAUDE_HOME")
    try:
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
    finally:
        if saved_home is None:
            os.environ.pop("CLAUDE_HOME", None)
        else:
            os.environ["CLAUDE_HOME"] = saved_home
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

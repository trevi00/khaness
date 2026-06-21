#!/usr/bin/env python3
"""Tests for lib.team_policy + cli.team_policy_check (M28).

The deterministic team-monitor seam: D1 stall detection (watermark + AND-combiner +
pane-veto + fail-closed), D2 quorum-guarded kill, D3 frozen-denominator aggregate,
the decide_pass orchestrator, and the CLI's two-pass kill→idempotent roundtrip.
Auto-discovered by run_units.py via main()->int.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.team_policy import (  # noqa: E402
    WorkerAssessment,
    WorkerSignals,
    aggregate_quorum,
    decide_pass,
    evaluate_stall,
    has_terminal_marker,
    make_file_read_fn,
    should_kill,
)


def _wm_store():
    wm: dict = {}
    return wm, (lambda s, w: wm.get((s, w))), (lambda s, w, d: wm.__setitem__((s, w), d))


def _sig(out_bytes=None, *, alive=True, mbox=None, pane=None, hb=None):
    return lambda *_: WorkerSignals(out_bytes=out_bytes, heartbeat_out_bytes=hb,
                                    mailbox_depth=mbox, pane_hash=pane, alive=alive)


# ---- D1: evaluate_stall ----

def test_first_observation_establishes_baseline():
    wm, r, w = _wm_store()
    res = evaluate_stall("s", "w", 1000.0, stall_seconds=100, read_fn=_sig(100),
                         read_watermark=r, write_watermark=w)
    assert res.status == "progressing" and res.grew is False
    assert wm[("s", "w")]["last_progress_ts"] == 1000.0


def test_flat_below_threshold_progressing_ts_unchanged():
    wm, r, w = _wm_store()
    evaluate_stall("s", "w", 1000.0, stall_seconds=100, read_fn=_sig(100),
                   read_watermark=r, write_watermark=w)
    res = evaluate_stall("s", "w", 1050.0, stall_seconds=100, read_fn=_sig(100),
                         read_watermark=r, write_watermark=w)
    assert res.status == "progressing"
    # flat cycle: watermark NOT rewritten -> last_progress_ts frozen at baseline
    assert wm[("s", "w")]["last_progress_ts"] == 1000.0


def test_flat_past_threshold_alive_is_stalled():
    wm, r, w = _wm_store()
    evaluate_stall("s", "w", 1000.0, stall_seconds=100, read_fn=_sig(100),
                   read_watermark=r, write_watermark=w)
    res = evaluate_stall("s", "w", 1101.0, stall_seconds=100, read_fn=_sig(100),
                         read_watermark=r, write_watermark=w)
    assert res.status == "stalled" and res.elapsed >= 100


def test_growth_resets_clock():
    wm, r, w = _wm_store()
    evaluate_stall("s", "w", 1000.0, stall_seconds=100, read_fn=_sig(100),
                   read_watermark=r, write_watermark=w)
    res = evaluate_stall("s", "w", 1200.0, stall_seconds=100, read_fn=_sig(150),
                         read_watermark=r, write_watermark=w)
    assert res.status == "progressing" and res.grew is True
    assert wm[("s", "w")]["last_progress_ts"] == 1200.0


def test_flat_past_threshold_not_alive_is_progressing():
    wm, r, w = _wm_store()
    evaluate_stall("s", "w", 1000.0, stall_seconds=100, read_fn=_sig(100, alive=True),
                   read_watermark=r, write_watermark=w)
    # worker now terminal (alive=False) and flat -> NOT a kill target
    res = evaluate_stall("s", "w", 1500.0, stall_seconds=100, read_fn=_sig(100, alive=False),
                         read_watermark=r, write_watermark=w)
    assert res.status == "progressing"


def test_pane_change_vetoes_stall():
    wm, r, w = _wm_store()
    evaluate_stall("s", "w", 1000.0, stall_seconds=100, read_fn=_sig(100, pane="a"),
                   read_watermark=r, write_watermark=w)
    # primary flat past threshold, but pane changed -> corroborates liveness -> veto
    res = evaluate_stall("s", "w", 1200.0, stall_seconds=100, read_fn=_sig(100, pane="b"),
                         read_watermark=r, write_watermark=w)
    assert res.status == "progressing" and "veto" in res.reason
    # pane is never sole: it did NOT reset last_progress_ts
    assert wm[("s", "w")]["last_progress_ts"] == 1000.0


def test_mailbox_change_resets_clock_supplementary():
    wm, r, w = _wm_store()
    evaluate_stall("s", "w", 1000.0, stall_seconds=100, read_fn=_sig(100, mbox=2),
                   read_watermark=r, write_watermark=w)
    # primary flat but mailbox depth changed -> supplementary progress -> clock reset
    res = evaluate_stall("s", "w", 1200.0, stall_seconds=100, read_fn=_sig(100, mbox=3),
                         read_watermark=r, write_watermark=w)
    assert res.status == "progressing" and res.grew is True
    assert wm[("s", "w")]["last_progress_ts"] == 1200.0


def test_heartbeat_out_bytes_is_primary_when_out_missing():
    wm, r, w = _wm_store()
    evaluate_stall("s", "w", 1000.0, stall_seconds=100,
                   read_fn=_sig(None, hb=100), read_watermark=r, write_watermark=w)
    res = evaluate_stall("s", "w", 1200.0, stall_seconds=100,
                         read_fn=_sig(None, hb=140), read_watermark=r, write_watermark=w)
    assert res.status == "progressing" and res.grew is True


def test_read_none_is_unknown_watermark_untouched():
    wm, r, w = _wm_store()
    res = evaluate_stall("s", "w", 1000.0, stall_seconds=100,
                         read_fn=lambda *_: None, read_watermark=r, write_watermark=w)
    assert res.status == "unknown"
    assert ("s", "w") not in wm  # fail-closed: never wrote a baseline


def test_read_raises_is_unknown():
    def boom(*_):
        raise RuntimeError("disk gone")
    res = evaluate_stall("s", "w", 1000.0, stall_seconds=100, read_fn=boom,
                         read_watermark=lambda *_: None, write_watermark=lambda *a: None)
    assert res.status == "unknown" and "RuntimeError" in res.reason


def test_alive_none_is_unknown():
    res = evaluate_stall("s", "w", 1000.0, stall_seconds=100,
                         read_fn=_sig(100, alive=None),
                         read_watermark=lambda *_: None, write_watermark=lambda *a: None)
    assert res.status == "unknown"


# ---- D2: should_kill ----

def test_should_kill_when_quorum_reachable():
    d = should_kill("s", "w3", responded_count=2, frozen_quorum_threshold=2,
                    survivor_capacity=0)
    assert d.kill is True and d.action == "kill" and d.reachable_after_kill == 2


def test_skip_below_quorum_when_unreachable():
    d = should_kill("s", "w1", responded_count=0, frozen_quorum_threshold=2,
                    survivor_capacity=1)
    assert d.kill is False and d.action == "skip_below_quorum"
    assert d.reachable_after_kill == 1


# ---- D3: aggregate_quorum (frozen denominator) ----

def test_aggregate_unanimous_quorum():
    res = aggregate_quorum(["approve", "approve", "approve"], frozen_denominator=3)
    assert res.status == "quorum" and res.verdict == "approve" and res.threshold == 2


def test_aggregate_majority_quorum():
    res = aggregate_quorum(["yes", "yes", "no"], frozen_denominator=3)
    assert res.status == "quorum" and res.verdict == "yes"


def test_aggregate_tie_escalates():
    res = aggregate_quorum(["a", "b"], frozen_denominator=2)
    # threshold=1, both count=1 -> tie -> split -> escalate
    assert res.status == "split" and res.verdict == "escalate"


def test_aggregate_no_majority_escalates():
    res = aggregate_quorum(["a", "b", "c", "d", "e"], frozen_denominator=5)
    assert res.status == "split" and res.verdict == "escalate" and res.threshold == 3


def test_aggregate_frozen_denominator_blocks_unreachable():
    # 2 survivors agree, but frozen N=5 -> threshold 3 -> unreachable (denominator frozen)
    res = aggregate_quorum(["pass", "pass"], frozen_denominator=5)
    assert res.status == "unreachable" and res.verdict == "escalate"
    assert res.threshold == 3 and res.frozen_denominator == 5


def test_aggregate_frozen_denominator_exact_threshold():
    # 3 survivors agree on frozen N=5 (threshold 3) -> quorum reached at the floor
    res = aggregate_quorum(["pass", "pass", "pass"], frozen_denominator=5)
    assert res.status == "quorum" and res.verdict == "pass"


def test_aggregate_empty_unreachable():
    res = aggregate_quorum([], frozen_denominator=3)
    assert res.status == "unreachable" and res.verdict == "escalate"


def test_aggregate_dict_results_normalized():
    res = aggregate_quorum([{"verdict": "ok"}, {"verdict": "ok"}, "ok"], frozen_denominator=3)
    assert res.status == "quorum" and res.verdict == "ok"


# ---- decide_pass orchestration ----

def _asmt(wid, status, *, responded=False, alive=True):
    return WorkerAssessment(wid, status, responded, alive, "")


def test_decide_pass_noop_when_none_stalled():
    d = decide_pass("s", [_asmt("worker-1", "progressing"),
                          _asmt("worker-2", "progressing")], frozen_n=2)
    assert d.exit_code == 0 and not d.actions


def test_decide_pass_kills_when_quorum_already_met():
    a = [_asmt("worker-1", "progressing", responded=True, alive=False),
         _asmt("worker-2", "progressing", responded=True, alive=False),
         _asmt("worker-3", "stalled", responded=False, alive=True)]
    d = decide_pass("s", a, frozen_n=3)
    assert d.exit_code == 3 and d.actions[0].action == "kill"


def test_decide_pass_escalates_when_kill_breaks_quorum():
    a = [_asmt("worker-1", "stalled", responded=False, alive=True)]
    d = decide_pass("s", a, frozen_n=3)
    assert d.exit_code == 5 and d.actions[0].action == "escalate"


def test_decide_pass_skipped_for_safety_on_unknown():
    a = [_asmt("worker-1", "unknown", alive=None),
         _asmt("worker-2", "progressing")]
    d = decide_pass("s", a, frozen_n=2)
    assert d.exit_code == 4 and not d.actions


def test_decide_pass_already_killed_excluded():
    a = [_asmt("worker-1", "stalled", alive=True)]
    d = decide_pass("s", a, frozen_n=3, already_killed={"worker-1"})
    assert d.exit_code == 0 and not d.actions


def test_decide_pass_kills_then_escalates_at_floor():
    # responded=1, threshold=2, two stalled-alive: kill the first (survivor props
    # quorum), then escalate the second (floor reached). escalate(5) dominates.
    a = [_asmt("worker-0", "progressing", responded=True, alive=False),
         _asmt("worker-1", "stalled", responded=False, alive=True),
         _asmt("worker-2", "stalled", responded=False, alive=True)]
    d = decide_pass("s", a, frozen_n=3)
    assert d.exit_code == 5
    assert [x.action for x in d.actions] == ["kill", "escalate"]


# ---- helpers ----

def test_has_terminal_marker():
    assert has_terminal_marker("[start]\nstuff\nDONE") is True
    assert has_terminal_marker("[start]\nstuff\n") is False
    assert has_terminal_marker("") is False


def test_make_file_read_fn_reads_real_artifacts():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "worker-1.out").write_text("[start] worker-1\nhello\n", encoding="utf-8")
        (d / "worker-1.heartbeat.jsonl").write_text(
            '{"event":"start","out_bytes":10}\n{"event":"heartbeat","out_bytes":24}\n',
            encoding="utf-8")
        rf = make_file_read_fn(d)
        sig = rf("s", "worker-1")
        assert sig.out_bytes > 0 and sig.heartbeat_out_bytes == 24 and sig.alive is True
        # terminal worker -> alive False
        (d / "worker-2.out").write_text("[start]\n[end] worker-2 rc=0\nDONE\n", encoding="utf-8")
        sig2 = rf("s", "worker-2")
        assert sig2.alive is False
        # absent worker -> unknown (alive None)
        sig3 = rf("s", "worker-9")
        assert sig3.alive is None


# ---- CLI end-to-end (two-pass kill + idempotency) ----

def _run_cli(**kw):
    import cli.team_policy_check as cli
    return cli.run(**kw)


def test_cli_two_pass_kill_then_idempotent():
    import lib.paths as paths
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(paths, "STATE_DIR", Path(td) / "state"):
            sid = "team-cli-test"
            tdir = str(Path(td) / "omc")
            workers = ["worker-1", "worker-2", "worker-3"]
            killed: list[str] = []

            def read_fn(_sid, wid):
                if wid in ("worker-1", "worker-2"):
                    return WorkerSignals(out_bytes=50, alive=False)  # responded
                return WorkerSignals(out_bytes=100, alive=True)      # w3 flat & alive

            def term(_sid, wid):
                killed.append(wid)
                return True

            common = dict(read_fn=read_fn, terminate_fn=term,
                          list_workers_fn=lambda _td, _s: workers,
                          alive_fn=lambda *_: False, mailbox_depth_fn=lambda *_: None,
                          capture_pane_fn=lambda *_: None, stall_seconds=100)

            # Pass 1 — establishes baselines, nothing stalled yet.
            r1, c1 = _run_cli(session_id=sid, team_dir=tdir, now=1000.0, **common)
            assert c1 == 0 and r1["frozen_n"] == 3 and r1["threshold"] == 2

            # Pass 2 — w3 flat 1000s past threshold -> stalled; quorum already met -> kill.
            r2, c2 = _run_cli(session_id=sid, team_dir=tdir, now=2000.0, **common)
            assert c2 == 3 and r2["killed"] == ["worker-3"] and killed == ["worker-3"]

            # Pass 3 — w3 now in killed-set -> excluded -> no duplicate kill.
            r3, c3 = _run_cli(session_id=sid, team_dir=tdir, now=3000.0, **common)
            assert c3 == 0 and r3["killed"] == [] and killed == ["worker-3"]

            # events.jsonl is the single writer and recorded the kill.
            ev_path = Path(td) / "state" / "team" / sid / "events.jsonl"
            text = ev_path.read_text(encoding="utf-8")
            assert "team_policy_kill" in text and "team_policy_pass" in text


def test_cli_escalates_when_lone_stalled_worker():
    import lib.paths as paths
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(paths, "STATE_DIR", Path(td) / "state"):
            sid = "team-cli-escalate"
            tdir = str(Path(td) / "omc")
            killed: list[str] = []
            common = dict(
                read_fn=lambda _s, _w: WorkerSignals(out_bytes=100, alive=True),
                terminate_fn=lambda _s, w: (killed.append(w) or True),
                list_workers_fn=lambda _td, _s: ["worker-1"],
                alive_fn=lambda *_: False, mailbox_depth_fn=lambda *_: None,
                capture_pane_fn=lambda *_: None, stall_seconds=100, frozen_n=3)
            _run_cli(session_id=sid, team_dir=tdir, now=1000.0, **common)        # baseline
            r2, c2 = _run_cli(session_id=sid, team_dir=tdir, now=2000.0, **common)
            # lone stalled worker, responded=0, threshold=2 -> killing breaks quorum
            assert c2 == 5 and r2["escalated"] is True and killed == []


def test_cli_argparse_usage_exit2():
    import cli.team_policy_check as cli
    try:
        cli.main(["--team-dir", "x"])  # missing --session-id
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected SystemExit(2)")


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

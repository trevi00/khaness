#!/usr/bin/env python3
"""End-to-end integration test for Path 2 D1+D2+D6+D7 chain.

Path 2 D5 (debate-1779229138-db17ce gen 3 LOCK SHA
c75bfaf403981c1fcd8cb45c0872c83ae564b777). Exercises the full pipeline
from D2 ledger → D1 scan_deadlines → D6 Stop-hook adapter and from D2
ledger → D7 dispatcher reader → fallback_to_legacy_e2 plumbing.

`today: date` is INJECTED everywhere — no freezegun, no monkeypatch on
date.today(). This is the testability invariant from the LOCK blueprint
(L5: "e2e integration test — today: date 주입").

Auto-discovered by tests/run_units.py via top-level main() -> int.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ============================================================================
# Fixtures
# ============================================================================


def _write_ledger(state_root: Path, gate_id: str, known_defects: int,
                  deadline: str | None) -> Path:
    """Write one ledger file under state_root/residual_norm/ and return path."""
    rn = state_root / "residual_norm"
    rn.mkdir(parents=True, exist_ok=True)
    p = rn / f"{gate_id}.json"
    payload = {
        "schema_version": 1,
        "gate_id": gate_id,
        "known_defects": known_defects,
        "deadline": deadline,
        "last_eval_ts": None,
        "last_verdict": None,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False))
    return p


# ============================================================================
# Test cases — D1+D2 (calendar_gate against committed ledger schema)
# ============================================================================


def test_d1_d2_baseline_zero_defects_not_overdue():
    """D1 scan_deadlines against D2 ledger with known_defects=0 → empty."""
    from lib.calendar_gate import scan_deadlines
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 0, "2026-01-01")
        # Past deadline but zero defects — must NOT surface
        results = scan_deadlines(state_root, date(2026, 5, 20))
        assert results == [], f"expected [], got {results}"


def test_d1_d2_overdue_with_defects_surfaces():
    """known_defects>0 + deadline passed → ScanResult emitted."""
    from lib.calendar_gate import scan_deadlines
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 3, "2026-04-20")
        results = scan_deadlines(state_root, date(2026, 5, 20))
        assert len(results) == 1, f"expected 1 result, got {len(results)}"
        r = results[0]
        assert r.gate_id == "rlm_gate"
        assert r.known_defects == 3
        assert r.days_overdue == 30


def test_d1_d2_future_deadline_not_overdue():
    """today < deadline → not surfaced even with defects."""
    from lib.calendar_gate import scan_deadlines
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 5, "2027-01-01")
        results = scan_deadlines(state_root, date(2026, 5, 20))
        assert results == [], f"expected [], got {results}"


# ============================================================================
# Test cases — D6 (Stop-hook adapter against D1+D2 chain)
# ============================================================================


def test_d6_emitter_returns_none_when_zero_defects():
    """D6 adapter returns None (no block) when ledger known_defects=0."""
    from handlers.stop.calendar_gate_emitter import build_block_payload
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 0, "2026-01-01")
        payload = build_block_payload(state_root, date(2026, 5, 20))
        assert payload is None, f"expected None, got {payload!r}"


def test_d6_emitter_returns_block_when_overdue_with_defects():
    """D6 adapter returns Stop-hook block payload when overdue + defects."""
    from handlers.stop.calendar_gate_emitter import build_block_payload
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 2, "2026-04-20")
        payload = build_block_payload(state_root, date(2026, 5, 20))
        assert payload is not None
        assert payload["decision"] == "block"
        reason = payload["reason"]
        assert "rlm_gate" in reason
        assert "known_defects=2" in reason
        assert "days_overdue=30" in reason


def test_d6_emitter_payload_json_serializable():
    """D6 payload must round-trip through json.dumps for stdout emit."""
    from handlers.stop.calendar_gate_emitter import build_block_payload
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 1, "2026-04-20")
        payload = build_block_payload(state_root, date(2026, 5, 20))
        # Round-trip
        rendered = json.dumps(payload, ensure_ascii=False)
        recovered = json.loads(rendered)
        assert recovered == payload


# ============================================================================
# Test cases — D7 (dispatcher ledger reader)
# ============================================================================


def test_d7_reads_zero_when_ledger_clean():
    """D7 reader returns 0 when ledger known_defects=0."""
    from lib.evaluator_dispatcher import read_known_defects_from_ledger
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 0, "2026-08-19")
        assert read_known_defects_from_ledger(state_root) == 0


def test_d7_reads_sum_across_multiple_ledgers():
    """D7 sums known_defects across all residual-norm ledgers."""
    from lib.evaluator_dispatcher import read_known_defects_from_ledger
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 2, "2026-08-19")
        _write_ledger(state_root, "other_gate", 3, "2026-08-19")
        assert read_known_defects_from_ledger(state_root) == 5


def test_d7_gate_filter_narrows_to_single_ledger():
    """D7 with gate_id= narrows the sum to one ledger."""
    from lib.evaluator_dispatcher import read_known_defects_from_ledger
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 2, "2026-08-19")
        _write_ledger(state_root, "other_gate", 3, "2026-08-19")
        assert read_known_defects_from_ledger(state_root, "rlm_gate") == 2
        assert read_known_defects_from_ledger(state_root, "other_gate") == 3


def test_d7_update_round_trip_writes_ts_and_verdict():
    """update_ledger_post_dispatch persists last_eval_ts + last_verdict."""
    from lib.evaluator_dispatcher import (
        read_known_defects_from_ledger, update_ledger_post_dispatch,
    )
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        ledger_path = _write_ledger(state_root, "rlm_gate", 0, "2026-08-19")
        ok = update_ledger_post_dispatch(
            "rlm_gate", "approved", state_root=state_root,
            ts="2026-05-20T01:00:00+00:00",
        )
        assert ok is True
        data = json.loads(ledger_path.read_text())
        assert data["last_eval_ts"] == "2026-05-20T01:00:00+00:00"
        assert data["last_verdict"] == "approved"
        # Re-read defects unchanged
        assert read_known_defects_from_ledger(state_root) == 0


# ============================================================================
# Test cases — Full chain (D1+D2+D6+D7 together)
# ============================================================================


def test_chain_clean_ledger_allows_dispatch_with_zero_defects():
    """Clean ledger → no Stop-hook block + dispatcher fallback sees defects=0
    (completeness=True when validators+units pass)."""
    from handlers.stop.calendar_gate_emitter import build_block_payload
    from lib.evaluator_dispatcher import (
        read_known_defects_from_ledger, fallback_to_legacy_e2, FallbackReason,
    )
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 0, "2026-08-19")
        today = date(2026, 5, 20)

        # D6 path: no block
        assert build_block_payload(state_root, today) is None

        # D7 path: dispatcher gets known_defects=0 → completeness=True
        defects = read_known_defects_from_ledger(state_root, "rlm_gate")
        assert defects == 0
        fb = fallback_to_legacy_e2(
            FallbackReason.SUBAGENT_TIMEOUT,
            sid="e2e-sid", phase_id="phase_3.5",
            validators_passed=True, units_passed=True, known_defects=defects,
        )
        assert fb["completeness"] is True
        # SUBAGENT_TIMEOUT + completeness → 'iterate' (transient retry)
        assert fb["verdict"] == "iterate"


def test_chain_defective_ledger_blocks_and_forces_iterate():
    """Defective ledger (known_defects>0) → D6 blocks AND D7 plumbs
    completeness=False to fallback → verdict='iterate'."""
    from handlers.stop.calendar_gate_emitter import build_block_payload
    from lib.evaluator_dispatcher import (
        read_known_defects_from_ledger, fallback_to_legacy_e2, FallbackReason,
    )
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 2, "2026-04-20")
        today = date(2026, 5, 20)

        # D6 path: block emitted
        payload = build_block_payload(state_root, today)
        assert payload is not None
        assert payload["decision"] == "block"

        # D7 path: dispatcher gets known_defects=2 → completeness=False
        defects = read_known_defects_from_ledger(state_root, "rlm_gate")
        assert defects == 2
        fb = fallback_to_legacy_e2(
            FallbackReason.SUBAGENT_TIMEOUT,
            sid="e2e-sid", phase_id="phase_3.5",
            validators_passed=True, units_passed=True, known_defects=defects,
        )
        # known_defects>0 → completeness=False → verdict='iterate'
        assert fb["completeness"] is False
        assert fb["verdict"] == "iterate"


def test_chain_defective_ledger_paradox_fail_escalates():
    """Defective ledger + PARADOX_GUARD_FAIL reason → still 'iterate'
    (completeness=False overrides). Confirms completeness clamp wins."""
    from lib.evaluator_dispatcher import (
        read_known_defects_from_ledger, fallback_to_legacy_e2, FallbackReason,
    )
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 1, "2026-04-20")
        defects = read_known_defects_from_ledger(state_root)
        fb = fallback_to_legacy_e2(
            FallbackReason.PARADOX_GUARD_FAIL,
            sid="e2e-sid", phase_id="phase_3.5",
            validators_passed=True, units_passed=True, known_defects=defects,
        )
        # completeness=False forces 'iterate' even with PARADOX_GUARD_FAIL
        assert fb["completeness"] is False
        assert fb["verdict"] == "iterate"


def test_chain_clean_ledger_paradox_fail_escalates_to_operator():
    """Clean ledger + PARADOX_GUARD_FAIL → completeness=True + verdict=
    'escalate' (operator review needed when paradox fails despite clean tests)."""
    from lib.evaluator_dispatcher import (
        read_known_defects_from_ledger, fallback_to_legacy_e2, FallbackReason,
    )
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 0, "2026-08-19")
        defects = read_known_defects_from_ledger(state_root)
        assert defects == 0
        fb = fallback_to_legacy_e2(
            FallbackReason.PARADOX_GUARD_FAIL,
            sid="e2e-sid", phase_id="phase_3.5",
            validators_passed=True, units_passed=True, known_defects=defects,
        )
        assert fb["completeness"] is True
        assert fb["verdict"] == "escalate"


def test_chain_update_after_dispatch_persists_and_d6_still_blocks():
    """Post-dispatch ledger update preserves D6 block semantic (gate is
    about known_defects, not about whether we've evaluated recently)."""
    from handlers.stop.calendar_gate_emitter import build_block_payload
    from lib.evaluator_dispatcher import update_ledger_post_dispatch
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 2, "2026-04-20")
        today = date(2026, 5, 20)

        # Pre-dispatch: D6 blocks
        assert build_block_payload(state_root, today) is not None

        # Dispatch happens, update ledger
        ok = update_ledger_post_dispatch(
            "rlm_gate", "iterate", state_root=state_root,
            ts="2026-05-20T02:00:00+00:00",
        )
        assert ok is True

        # Post-dispatch: D6 STILL blocks (known_defects didn't drop)
        payload = build_block_payload(state_root, today)
        assert payload is not None
        assert payload["decision"] == "block"


def test_chain_today_injection_no_clock_call():
    """Adapter functions must accept today as injected date, never call
    date.today() internally. Verify by exercising with arbitrary past +
    future dates without monkeypatching anything."""
    from handlers.stop.calendar_gate_emitter import build_block_payload
    with tempfile.TemporaryDirectory() as td:
        state_root = Path(td)
        _write_ledger(state_root, "rlm_gate", 1, "2026-05-01")

        # Past today (before deadline) → no block
        assert build_block_payload(state_root, date(2026, 4, 30)) is None

        # On-deadline today → block (days_overdue=0)
        on = build_block_payload(state_root, date(2026, 5, 1))
        assert on is not None and "days_overdue=0" in on["reason"]

        # Far-future today → block (days_overdue=large)
        far = build_block_payload(state_root, date(2027, 5, 1))
        assert far is not None and "days_overdue=365" in far["reason"]


# ============================================================================
# Test cases — D3 timeout constant verification (Path 2 invariant)
# ============================================================================


def test_d3_dispatcher_timeout_is_270():
    """D3 SUBAGENT_TIMEOUT_SECONDS must be 270 (post wave 10 Path 2 land).

    Path 2 invariant: dispatcher fires fallback BEFORE openai.py 300s
    subprocess timeout (which would wrap inner TimeoutExpired as
    ProviderUnavailableError, losing the SUBAGENT_TIMEOUT fallback reason
    categorization). 270s = 30s teardown buffer.
    """
    from lib.evaluator_dispatcher import SUBAGENT_TIMEOUT_SECONDS
    assert SUBAGENT_TIMEOUT_SECONDS == 270, (
        f"D3 invariant broken: SUBAGENT_TIMEOUT_SECONDS={SUBAGENT_TIMEOUT_SECONDS}, "
        f"expected 270 (wave 10 Path 2 LOCK c75bfaf4)"
    )


def test_d3_dispatcher_timeout_below_codex_subprocess_cap():
    """D3 invariant: dispatcher timeout < openai.py subprocess timeout
    (300s hard cap in OpenAIProvider.ask). Otherwise fallback reason
    categorization is lost (inner TimeoutExpired wrapped as
    ProviderUnavailableError)."""
    from lib.evaluator_dispatcher import SUBAGENT_TIMEOUT_SECONDS
    # openai.py codex exec timeout is hardcoded at 300s (line 71/81).
    OPENAI_HARD_CAP = 300
    assert SUBAGENT_TIMEOUT_SECONDS < OPENAI_HARD_CAP, (
        f"D3 invariant: dispatcher {SUBAGENT_TIMEOUT_SECONDS}s must fire "
        f"before openai.py {OPENAI_HARD_CAP}s subprocess cap"
    )
    # Buffer >= 20s for clean teardown
    assert (OPENAI_HARD_CAP - SUBAGENT_TIMEOUT_SECONDS) >= 20, (
        f"D3 invariant: insufficient teardown buffer "
        f"({OPENAI_HARD_CAP - SUBAGENT_TIMEOUT_SECONDS}s); recommended >=20s"
    )


# ============================================================================
# Test runner — main() per tests/run_units.py convention
# ============================================================================


TESTS = [
    # D1+D2
    test_d1_d2_baseline_zero_defects_not_overdue,
    test_d1_d2_overdue_with_defects_surfaces,
    test_d1_d2_future_deadline_not_overdue,
    # D6
    test_d6_emitter_returns_none_when_zero_defects,
    test_d6_emitter_returns_block_when_overdue_with_defects,
    test_d6_emitter_payload_json_serializable,
    # D7
    test_d7_reads_zero_when_ledger_clean,
    test_d7_reads_sum_across_multiple_ledgers,
    test_d7_gate_filter_narrows_to_single_ledger,
    test_d7_update_round_trip_writes_ts_and_verdict,
    # Full chain
    test_chain_clean_ledger_allows_dispatch_with_zero_defects,
    test_chain_defective_ledger_blocks_and_forces_iterate,
    test_chain_defective_ledger_paradox_fail_escalates,
    test_chain_clean_ledger_paradox_fail_escalates_to_operator,
    test_chain_update_after_dispatch_persists_and_d6_still_blocks,
    test_chain_today_injection_no_clock_call,
    # D3 invariant
    test_d3_dispatcher_timeout_is_270,
    test_d3_dispatcher_timeout_below_codex_subprocess_cap,
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

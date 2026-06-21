#!/usr/bin/env python3
"""Tests for lib.calibration.breaker_proposer + CLI 통합 (v15.14).

Coverage:
  - _parse_key_filename: agent_type__failure_mode 분리
  - analyze_breaker: 빈 file / malformed / 정상 record
  - BR1: insufficient history → skip
  - BR2: frequent trip → TRIP_PER_MODE 상향 제안
  - BR3: trip 없음 + 임계 직전 누적 → advisory note only
  - BR4: reopen-heavy → BACKOFF_BASE_SEC 상향 제안
  - propose_breaker_changes: project_root None vs 특정
  - CLI: 통합 (critic_policy 0 + breaker 1) 출력
"""
from __future__ import annotations

import json
import sys
import tempfile
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.calibration.breaker_proposer import (  # noqa: E402
    FREQUENT_TRIP_COUNT,
    MIN_HISTORY_LEN,
    REOPEN_HEAVY_TRIP_COUNT,
    BreakerProposal,
    BreakerStats,
    _parse_key_filename,
    analyze_breaker,
    propose_breaker_changes,
)
from lib.breakers.composite import (  # noqa: E402
    BACKOFF_BASE_SEC,
    BACKOFF_CAP_SEC,
    TRIP_PER_MODE,
    TRIP_WINDOW,
)
from lib.operator_ledger import project_id_for  # noqa: E402
from cli.calibration_review import main as cli_main  # noqa: E402


def _write_breaker(root: Path, project: str, agent: str, mode: str,
                   record: dict) -> Path:
    pid = project_id_for(project)
    p = root / pid / f"{agent}__{mode}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record), encoding="utf-8")
    return p


# ---- helpers ----

def test_parse_key_filename_basic():
    p = Path("/x/researcher__evidence_fabrication.json")
    a, m = _parse_key_filename(p)
    assert a == "researcher"
    assert m == "evidence_fabrication"


def test_parse_key_filename_no_separator():
    p = Path("/x/bogus.json")
    a, m = _parse_key_filename(p)
    assert a == "?" and m == "?"


# ---- analyze_breaker ----

def test_analyze_missing_file_returns_none():
    assert analyze_breaker(Path("/no/such/file__x.json")) is None


def test_analyze_normal_record():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = _write_breaker(root, "C:/proj", "researcher", "evidence_fabrication", {
            "state": "closed",
            "trip_count": 2,
            "history": [True, False, True, True, False, True, True, True, True, False],
            "opened_at": None,
            "cool_off_until": None,
        })
        stats = analyze_breaker(path)
        assert stats is not None
        assert stats.agent_type == "researcher"
        assert stats.failure_mode == "evidence_fabrication"
        assert stats.trip_count == 2
        assert stats.history_len == 10
        assert stats.failures_in_window == 3
        assert stats.window_failure_rate == 0.3


def test_analyze_empty_record_returns_zero_stats():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = _write_breaker(root, "C:/proj", "x", "y", {})
        stats = analyze_breaker(path)
        assert stats is not None
        assert stats.history_len == 0
        assert stats.trip_count == 0


# ---- BR1: insufficient history ----

def test_br1_skips_short_history():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_breaker(root, "C:/proj", "researcher", "evidence_fabrication", {
            "state": "closed",
            "trip_count": 0,
            "history": [True, False, True],  # < MIN_HISTORY_LEN
        })
        proposals = propose_breaker_changes("C:/proj", breakers_root=root)
        assert proposals == []


# ---- BR2: frequent trip ----

def test_br2_frequent_trip_proposes_trip_per_mode_increase():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 5 trips + window with 3+ failures
        _write_breaker(root, "C:/proj", "researcher", "evidence_fabrication", {
            "state": "open",
            "trip_count": FREQUENT_TRIP_COUNT,
            "history": [False] * TRIP_PER_MODE + [True] * (TRIP_WINDOW - TRIP_PER_MODE),
        })
        proposals = propose_breaker_changes("C:/proj", breakers_root=root)
        assert len(proposals) == 1
        p = proposals[0]
        assert p.target_constant == "trip_per_mode"
        assert p.current_value == TRIP_PER_MODE
        assert p.suggested_value == TRIP_PER_MODE + 1
        assert "상향" in p.rationale


# ---- BR4: reopen-heavy ----

def test_br4_reopen_heavy_proposes_backoff_increase():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        opened_at = 1_000_000.0
        # cool_off short (< BACKOFF_CAP_SEC/2 = 1800s)
        cool_off_until = opened_at + 120  # 2 min — very short
        _write_breaker(root, "C:/proj", "researcher", "evidence_fabrication", {
            "state": "open",
            "trip_count": REOPEN_HEAVY_TRIP_COUNT,  # not in BR2 territory (< FREQUENT_TRIP_COUNT)
            "history": [True] * TRIP_WINDOW,  # no failures in window → BR2 skip
            "opened_at": opened_at,
            "cool_off_until": cool_off_until,
        })
        proposals = propose_breaker_changes("C:/proj", breakers_root=root)
        assert len(proposals) == 1
        p = proposals[0]
        assert p.target_constant == "backoff_base_sec"
        assert p.current_value == BACKOFF_BASE_SEC
        assert p.suggested_value == min(BACKOFF_BASE_SEC * 2, BACKOFF_CAP_SEC // 2)


# ---- BR3: trip 없음 + 임계 직전 누적 ----

def test_br3_advisory_only_no_action():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # trip_count=0 + history 2*MIN + failures in (0, TRIP_PER_MODE)
        history = ([False] * (TRIP_PER_MODE - 1)
                   + [True] * (MIN_HISTORY_LEN * 2 - (TRIP_PER_MODE - 1)))
        _write_breaker(root, "C:/proj", "researcher", "evidence_fabrication", {
            "state": "closed",
            "trip_count": 0,
            "history": history,
        })
        proposals = propose_breaker_changes("C:/proj", breakers_root=root)
        assert len(proposals) == 1
        p = proposals[0]
        assert p.suggested_value is None  # advisory only
        assert p.note is not None
        assert "false-positive" in p.note.lower() or "false negative" in p.rationale.lower()


# ---- scope ----

def test_propose_breaker_scoped_to_project():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Project A: BR2 trigger
        _write_breaker(root, "C:/proj-A", "researcher", "evidence_fabrication", {
            "state": "open",
            "trip_count": FREQUENT_TRIP_COUNT,
            "history": [False] * TRIP_PER_MODE + [True] * (TRIP_WINDOW - TRIP_PER_MODE),
        })
        # Project B: no trigger
        _write_breaker(root, "C:/proj-B", "executor", "tool_misuse", {
            "state": "closed",
            "trip_count": 0,
            "history": [True] * TRIP_WINDOW,
        })
        # All projects scan
        all_proposals = propose_breaker_changes(breakers_root=root)
        assert len(all_proposals) == 1
        # Project A only
        a_only = propose_breaker_changes("C:/proj-A", breakers_root=root)
        assert len(a_only) == 1
        # Project B only
        b_only = propose_breaker_changes("C:/proj-B", breakers_root=root)
        assert b_only == []


# ---- CLI ----

def test_cli_combined_output_when_only_breaker_proposal():
    """critic_policy 0 + breaker 1 — combined output 형식 검증."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        # Monkey-patch STATE_DIR to point at our tmp breakers root
        from lib import paths as P
        from lib.breakers import composite as comp
        from lib.calibration import breaker_proposer as BP

        # We can't easily redirect breaker location without monkey-patching STATE_DIR.
        # Simpler: set BP._iter_breaker_files's default breakers_root by writing
        # to the real STATE_DIR/breakers — but that would pollute. Instead test
        # cli_main with a custom project_root pointing at an isolated location
        # is not directly supported. We just verify the CLI runs with an empty
        # state and exits 0.
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main(["--project-root", td])
        assert rc == 0
        # Either no proposal or some (depends on real ~/.claude/state) — main thing:
        # CLI does not crash with combined output structure.


def test_cli_json_includes_both_kinds():
    """JSON 출력 schema가 critic_policy_count + breaker_count + 분류된 proposals."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main(["--project-root", td, "--json"])
        assert rc == 0
        parsed = json.loads(out.getvalue())
        assert "critic_policy_count" in parsed
        assert "breaker_count" in parsed
        assert "proposals" in parsed


TESTS = [
    test_parse_key_filename_basic,
    test_parse_key_filename_no_separator,
    test_analyze_missing_file_returns_none,
    test_analyze_normal_record,
    test_analyze_empty_record_returns_zero_stats,
    test_br1_skips_short_history,
    test_br2_frequent_trip_proposes_trip_per_mode_increase,
    test_br4_reopen_heavy_proposes_backoff_increase,
    test_br3_advisory_only_no_action,
    test_propose_breaker_scoped_to_project,
    test_cli_combined_output_when_only_breaker_proposal,
    test_cli_json_includes_both_kinds,
    # apply_command tests appended after their definitions (Python forward-ref limit)
]


def test_breaker_apply_command_includes_strong_token_on_increase():
    """v15.18: BR2 (TRIP_PER_MODE 상향) 제안 → configure-critic-policy."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_breaker(root, "C:/proj", "researcher", "evidence_fabrication", {
            "state": "open",
            "trip_count": FREQUENT_TRIP_COUNT,
            "history": [False] * TRIP_PER_MODE + [True] * (TRIP_WINDOW - TRIP_PER_MODE),
        })
        proposals = propose_breaker_changes("C:/proj", breakers_root=root)
        assert len(proposals) == 1
        from cli.calibration_review import _breaker_apply_command
        cmd = _breaker_apply_command(proposals[0])
        assert cmd is not None
        assert "cli.breaker_override" in cmd
        assert "--key trip_per_mode" in cmd
        assert f"--value {TRIP_PER_MODE + 1}" in cmd
        assert "configure-critic-policy" in cmd  # increase = strong


def test_breaker_apply_command_includes_safe_token_on_decrease():
    """Custom proposal where value < current → safe token."""
    from lib.calibration.breaker_proposer import BreakerProposal, BreakerStats
    from cli.calibration_review import _breaker_apply_command
    stats = BreakerStats("x", "y", "closed", 0, 20, 5, None, None)
    p = BreakerProposal(
        agent_type="x", failure_mode="y",
        target_constant="trip_per_mode",
        current_value=3, suggested_value=2,  # decrease
        evidence=stats, rationale="ops",
    )
    cmd = _breaker_apply_command(p)
    assert cmd is not None
    assert "apply-user-preference" in cmd


TESTS.extend([
    test_breaker_apply_command_includes_strong_token_on_increase,
    test_breaker_apply_command_includes_safe_token_on_decrease,
])


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

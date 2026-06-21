"""Completion gate primitive — pure decision logic + iteration counter.

Extracted from `engine/orchestrator.py` to retire the `handlers/stop/
autopilot_continue.py:467` layer-adjacency violation (handlers → engine
forbidden per `validators/commit_layer_adjacency.py` 4-tier model).

This module is *lib-tier*: no engine/handlers deps. Engine retains a
thin wrapper around `decide_completion` for callers that still hold an
`OrchestratorSession`; the Stop hook calls this module directly with an
int iteration count obtained via `count_orchestrator_iterations`.

## Layer-adjacency cleanup trail

- baseline regression introduced by `engine/orchestrator.py` evolving
  to be imported from `handlers/stop/autopilot_continue.py` (origin
  commit 843df69 v15.28, "autopilot_continue.py extends ac_verdict
  scalar → EventStore reduction")
- wave 7 후속 5 (commit 2c97aab) reported validators 22/22 — that snapshot
  pre-dated the v15.28 extension that introduced the violation
- wave 7 후속 12 (commit e92b84f) shipped D4+D8 without addressing it,
  flagged by Stop hook 응답 품질 ([책임 회피] 원인을 조사하고 수정)
- this module retires the violation by inverting the dependency:
  engine still owns session state, but the *decision logic* moves down
  to lib, and the iteration *count* primitive lives in lib too.

## API

- `decide_completion(iteration, *, validators_passed, tests_passed,
   blocking_question_count=0, max_iterations=DEFAULT_MAX_ITERATIONS,
   evaluator_verdict=None) -> str`
- `count_orchestrator_iterations(sid: str) -> int | None`
- `DEFAULT_MAX_ITERATIONS: int = 3`

Returns of decide_completion: `'complete' | 'iterate' | 'escalate'`.

`count_orchestrator_iterations` returns:
- None        — `STATE_DIR/orchestrator/<sid>/events.jsonl` does not exist
                (cold-start; caller falls through to inline gate)
- int >= 0    — count of `iteration_started` events found
"""
from __future__ import annotations

import json


DEFAULT_MAX_ITERATIONS: int = 3


def decide_completion(
    iteration: int,
    *,
    validators_passed: bool,
    tests_passed: bool,
    blocking_question_count: int = 0,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    evaluator_verdict: str | None = None,
    require_evaluator: bool = False,
) -> str:
    """Decide stop/loop/escalate. Pure logic — no I/O, no session state.

    Returns one of:
      'complete' — validators + tests pass, no blocking questions, AND
                   (if evaluator_verdict provided) verdict='approved'.
      'iterate'  — failure observed AND iteration < max_iterations.
      'escalate' — max_iterations reached OR blocking_question_count > 0
                   OR evaluator_verdict='escalate'.

    `evaluator_verdict` (DGE E2 integration per debate-1778248254-0b7092):
      None       — caller did not run E2 evaluator; legacy boolean-only gate
      'approved' — E2 verdict approved AND objective tests pass → 'complete'
      'iterate'  — E2 says iterate (axis≤3 OR completeness=False)
      'escalate' — E2 structural concern → 'escalate' immediately

    `require_evaluator` (E2 PLATFORM ENFORCEMENT per debate-1780564679-8mgxsd
    D1/D4): default False preserves the legacy boolean-only contract BYTE-
    IDENTICAL for every prior caller. When True (autopilot shared-sid Stop
    gate), a missing verdict (None) can NEVER complete — the legacy
    None-completion branch is gated behind `not require_evaluator`, so control
    falls through to the `iteration >= max_iterations` check (escalate at the
    cap — bounded termination, D4) else 'iterate' (re-run so the platform
    produces a durable verdict). A fresh evaluator_verdict='approved' (with
    clean tests) still completes; 'escalate'/'iterate' route as usual.

    Conservative: any failure dimension blocks 'complete'.
    """
    if blocking_question_count > 0:
        return "escalate"
    if evaluator_verdict == "escalate":
        return "escalate"
    if evaluator_verdict == "approved" and validators_passed and tests_passed:
        return "complete"
    # E2 platform enforcement (debate-1780564679-8mgxsd D1): the legacy
    # boolean-only completion below is reached ONLY when require_evaluator is
    # False. When require_evaluator is True a missing verdict (None) skips
    # completion and falls through to the iteration>=max_iterations escalate
    # (D4 bounded termination) else 'iterate'. require_evaluator=False keeps
    # this line logically identical to the prior unconditional branch, so the
    # existing truth-table assertions are unchanged.
    if (
        not require_evaluator
        and evaluator_verdict is None
        and validators_passed
        and tests_passed
    ):
        return "complete"
    if iteration >= max_iterations:
        return "escalate"
    return "iterate"


def count_orchestrator_iterations(sid: str) -> int | None:
    """Replay `STATE_DIR/orchestrator/<sid>/events.jsonl` and count
    `iteration_started` events. Returns None if events.jsonl is missing
    (cold-start signal, equivalent to the old `load_session` returning None).

    Corrupt JSONL lines are skipped (mirrors orchestrator's replay tolerance);
    only `iteration_started` typed lines contribute to the count.
    """
    if not sid or "/" in sid or ".." in sid:
        return None
    # Lazy STATE_DIR resolution so a test rebinding `lib.paths.STATE_DIR`
    # (and CLAUDE_HOME isolation harnesses) is honored — a module-level
    # `from .paths import STATE_DIR` captured at import time would point at
    # the real state dir. Mirrors the lazy pattern in evaluator_dispatcher.
    from .paths import STATE_DIR
    events_path = STATE_DIR / "orchestrator" / sid / "events.jsonl"
    if not events_path.exists():
        return None
    count = 0
    try:
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "iteration_started":
                    count += 1
    except OSError:
        return None
    return count


def iteration_started_ts(sid: str) -> float | None:
    """Float epoch ts of the LAST `iteration_started` event in
    `STATE_DIR/orchestrator/<sid>/events.jsonl`, or None if the file is
    missing or holds no such event (E2 freshness floor, debate-1780564679
    D2a).

    The orchestrator stamps `iteration_started` with `lib.logging.now_iso`
    (UTC, '%Y-%m-%dT%H:%M:%SZ', SECOND resolution). We parse it back via
    `calendar.timegm` (UTC — never `time.mktime`, which applies the local tz
    offset and would skew the floor). The epoch is whole-second; the freshness
    comparison in `latest_fresh_evaluator_verdict` is `>=` (same-second
    inclusive) so a verdict written in the same wall-clock second as the
    iteration start counts as fresh.

    Mirrors `count_orchestrator_iterations`' replay; stays lib-tier (no
    engine import) per commit_layer_adjacency. Fail-soft → None.
    """
    if not sid or "/" in sid or ".." in sid:
        return None
    from .paths import STATE_DIR
    events_path = STATE_DIR / "orchestrator" / sid / "events.jsonl"
    if not events_path.exists():
        return None
    import calendar
    import time as _time
    latest: float | None = None
    try:
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") != "iteration_started":
                    continue
                ts_raw = ev.get("ts")
                if not isinstance(ts_raw, str):
                    continue
                try:
                    epoch = float(calendar.timegm(
                        _time.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ")
                    ))
                except (ValueError, TypeError):
                    continue
                if latest is None or epoch > latest:
                    latest = epoch
    except OSError:
        return None
    return latest


def latest_fresh_evaluator_verdict(sid: str, since_ts: float | None) -> str | None:
    """Most recent (tail-wins) E2 evaluator verdict in
    `STATE_DIR/evaluator/<sid>/axis_scores.jsonl` fresher than the current
    iteration, or None (debate-1780564679 D2b).

    FAIL-CLOSED (C4/C5): `since_ts is None` returns None — an unresolvable
    freshness floor is NEVER treated as 0.0 (which would let a stale verdict
    pass). The caller maps None under require_evaluator=True to 'iterate', so
    a missing/unresolvable verdict can never complete a run.

    Selection: records whose 'verdict' VALUE is in {approved, iterate,
    escalate} and whose float 'ts' >= since_ts (same-second inclusive per
    D2a); the verdict of the MAX-ts record wins (ties → later-in-file, tail-
    wins). Filtering on the VALUE (not the event-type string) accepts the
    producer event names 'verdict' (harness-evaluate), 'evaluator_verdict'
    (autopilot Phase 3.5 default producer) and 'fallback' (legacy E2)
    uniformly.

    Reads only via `lib.axis_scores_log.read_axis_events` (server-stamped ts,
    schema_version-gated). No engine dependency. Fail-soft → None.
    """
    if since_ts is None:
        return None
    if not sid or "/" in sid or ".." in sid:
        return None
    try:
        from .axis_scores_log import read_axis_events
        events = read_axis_events(sid)
    except Exception:
        return None
    valid = {"approved", "iterate", "escalate"}
    best_ts: float | None = None
    best_verdict: str | None = None
    for rec in events:
        if not isinstance(rec, dict):
            continue
        verdict = rec.get("verdict")
        if verdict not in valid:
            continue
        ts_raw = rec.get("ts")
        if not isinstance(ts_raw, (int, float)) or isinstance(ts_raw, bool):
            continue
        ts = float(ts_raw)
        if ts < since_ts:
            continue
        if best_ts is None or ts >= best_ts:
            best_ts = ts
            best_verdict = verdict
    return best_verdict


# ---- self-check (mirrors module pattern of lib/ambiguity_score.py) ----

def _self_check() -> None:
    """Inline assertions covering decide_completion truth table + helper edge cases."""
    asserts_run = 0

    def _assert(cond: bool, msg: str) -> None:
        nonlocal asserts_run
        asserts_run += 1
        if not cond:
            raise AssertionError(f"completion_gate self-check FAIL: {msg}")

    # ---- A. decide_completion truth table ----
    # Legacy path: validators+tests pass, no evaluator → complete
    _assert(
        decide_completion(0, validators_passed=True, tests_passed=True) == "complete",
        "legacy clean → complete",
    )
    # Failure within cap → iterate
    _assert(
        decide_completion(0, validators_passed=False, tests_passed=True) == "iterate",
        "failure iter 0 → iterate",
    )
    _assert(
        decide_completion(2, validators_passed=False, tests_passed=True) == "iterate",
        "failure iter 2 (within cap=3) → iterate",
    )
    # Max iter reached on failure → escalate
    _assert(
        decide_completion(3, validators_passed=False, tests_passed=True) == "escalate",
        "iter==max on failure → escalate",
    )
    _assert(
        decide_completion(99, validators_passed=False, tests_passed=False) == "escalate",
        "iter>>max → escalate",
    )
    # Blocking question always escalates
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            blocking_question_count=1,
        ) == "escalate",
        "blocking question → escalate",
    )
    # E2 'escalate' short-circuits
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            evaluator_verdict="escalate",
        ) == "escalate",
        "E2 escalate verdict → escalate",
    )
    # E2 'approved' + clean tests → complete
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            evaluator_verdict="approved",
        ) == "complete",
        "E2 approved + clean → complete",
    )
    # E2 'approved' + failing tests → NOT complete (falls through)
    _assert(
        decide_completion(
            0, validators_passed=False, tests_passed=True,
            evaluator_verdict="approved",
        ) == "iterate",
        "E2 approved + failing validators → iterate",
    )
    # E2 'iterate' → does not complete
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            evaluator_verdict="iterate",
        ) == "iterate",
        "E2 iterate verdict → iterate",
    )
    # Custom max_iterations
    _assert(
        decide_completion(
            5, validators_passed=False, tests_passed=False,
            max_iterations=10,
        ) == "iterate",
        "iter 5 with max=10 → iterate",
    )
    _assert(
        decide_completion(
            10, validators_passed=False, tests_passed=False,
            max_iterations=10,
        ) == "escalate",
        "iter==max with max=10 → escalate",
    )

    # ---- B. count_orchestrator_iterations edge cases ----
    _assert(count_orchestrator_iterations("") is None, "empty sid → None")
    _assert(count_orchestrator_iterations("../etc") is None, "path-traversal sid → None")
    _assert(
        count_orchestrator_iterations("nonexistent-sid-9999") is None,
        "missing events.jsonl → None",
    )

    # ---- C. require_evaluator E2 platform enforcement (debate-1780564679) ----
    # Default require_evaluator=False is logically identical to the prior gate:
    # the section-A assertions above already cover that. These cover True.
    # Missing verdict (None) can NEVER complete on Tier-1 alone (the gap closed).
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            evaluator_verdict=None, require_evaluator=True,
        ) == "iterate",
        "require_evaluator + None verdict below cap → iterate (NOT complete)",
    )
    # D4 bounded termination: at the cap a missing verdict escalates.
    _assert(
        decide_completion(
            3, validators_passed=True, tests_passed=True,
            evaluator_verdict=None, require_evaluator=True,
        ) == "escalate",
        "require_evaluator + None verdict at cap → escalate (D4 termination)",
    )
    # A fresh approved verdict + clean tests still completes under enforcement.
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            evaluator_verdict="approved", require_evaluator=True,
        ) == "complete",
        "require_evaluator + approved + clean → complete",
    )
    # Explicit non-None verdicts route as usual under enforcement.
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            evaluator_verdict="iterate", require_evaluator=True,
        ) == "iterate",
        "require_evaluator + iterate verdict → iterate",
    )
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            evaluator_verdict="escalate", require_evaluator=True,
        ) == "escalate",
        "require_evaluator + escalate verdict → escalate",
    )
    # approved verdict but FAILING validators → not complete (clamp preserved).
    _assert(
        decide_completion(
            0, validators_passed=False, tests_passed=True,
            evaluator_verdict="approved", require_evaluator=True,
        ) == "iterate",
        "require_evaluator + approved + failing validators → iterate",
    )
    # require_evaluator=False keeps the legacy None→complete (regression guard).
    _assert(
        decide_completion(
            0, validators_passed=True, tests_passed=True,
            evaluator_verdict=None, require_evaluator=False,
        ) == "complete",
        "require_evaluator=False + None + clean → complete (legacy preserved)",
    )

    # ---- D. iteration_started_ts / latest_fresh_evaluator_verdict guards ----
    # Pure input-guard edge cases (I/O-backed freshness behavior is covered by
    # fixture tests in tests/test_completion_gate.py).
    _assert(iteration_started_ts("") is None, "iteration_started_ts empty sid → None")
    _assert(iteration_started_ts("../x") is None, "iteration_started_ts traversal → None")
    _assert(
        iteration_started_ts("nonexistent-sid-9999") is None,
        "iteration_started_ts missing events.jsonl → None",
    )
    # since_ts=None MUST fail closed regardless of sid (C4/C5).
    _assert(
        latest_fresh_evaluator_verdict("any-sid", None) is None,
        "latest_fresh_evaluator_verdict since_ts=None → None (fail-closed)",
    )
    _assert(
        latest_fresh_evaluator_verdict("", 0.0) is None,
        "latest_fresh_evaluator_verdict empty sid → None",
    )
    _assert(
        latest_fresh_evaluator_verdict("../x", 0.0) is None,
        "latest_fresh_evaluator_verdict traversal sid → None",
    )

    print(f"OK: {asserts_run} assertions passed")


if __name__ == "__main__":
    _self_check()

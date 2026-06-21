#!/usr/bin/env python3
"""End-to-end fixture: surviving Ouroboros half (ac_tree + wonder).

De-wired 2026-06-21 (debate-1782013078-bd06ee, SPLIT verdict): the orphaned
half — lib/seed_lock.py + lib/reflect_feedback.py — was retired (operator
go-ahead, Part(1)). The S (Seed freeze) and RF (Reflect->next-gen addendum)
steps of the original full loop, plus test_e2e_seed_tamper_detection, are
removed with them. This fixture now exercises only the KEPT/ratified half —
ac_tree (T) + wonder (W) — preserved as a SEPARATE operator-signed retraction
question (Part(2), deferred). De-wire was chosen over full delete precisely so
ac_tree/wonder integration coverage survives until that question is decided.

Exercised flow (T -> evaluate fail -> W):

1. **T** (AC Tree): build leaves with mixed gate+advisory -> evaluate
2. **Evaluate fail**: leaves designed so aggregate returns 'iterate' twice in a
   row with the SAME fingerprint (2-strike)
3. **W** (Wonder): record 2 strikes -> wonder.triggered -> write_reflection
4. **event_taxonomy**: every emitted event type is in KNOWN_EVENT_TYPES
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _isolate(td: Path):
    os.environ["CLAUDE_HOME"] = str(td)


def test_e2e_ac_tree_wonder_loop():
    """T -> evaluate fail -> W integration (surviving Ouroboros half)."""
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))

        # All event_types collected here for taxonomy validation at the end.
        events: list[tuple[str, dict]] = []
        def emit(t: str, p: dict):
            events.append((t, p))

        # ---- Step 1: T (AC Tree build) ----
        from lib.ac_tree import GateLeaf, AdvisoryLeaf, evaluate_emit

        # Construct leaves that will return 'iterate' (deterministic failure pattern)
        leaves = [
            GateLeaf(predicate=lambda ctx: True, description="completeness gate"),
            AdvisoryLeaf(predicate=lambda ctx: 2, axis="cohesion", description="low cohesion"),
            AdvisoryLeaf(predicate=lambda ctx: 3, axis="coupling", description="ok coupling"),
        ]

        # ---- Step 2: Evaluate (1st strike — iterate) ----
        verdict_1 = evaluate_emit(leaves, ctx=None, emit_fn=emit)
        assert verdict_1 == "iterate"  # advisory score 2 <= 2 -> iterate

        # Verify ac.leaf_evaluated event emitted per leaf
        leaf_eval_events = [p for t, p in events if t == "ac.leaf_evaluated"]
        assert len(leaf_eval_events) == 3
        assert any(p["axis"] == "gate" for p in leaf_eval_events)
        assert any(p["axis"] == "cohesion" for p in leaf_eval_events)

        # ---- Step 3a: Wonder — 1st strike record ----
        from lib import wonder
        fp = wonder.compute_fingerprint("iterate", "cohesion", "low cohesion")
        strike_1 = wonder.record_strike("e2e-orch-1", fp)
        assert strike_1.count == 1
        assert strike_1.triggered is False  # below 2-Strike threshold

        # ---- Step 3b: 2nd evaluate same leaves (still iterate, same fingerprint) ----
        # Clear leaf events for cleaner inspection
        events.clear()
        verdict_2 = evaluate_emit(leaves, ctx=None, emit_fn=emit)
        assert verdict_2 == "iterate"

        # ---- Step 3c: Wonder — 2nd strike → triggered ----
        strike_2 = wonder.record_strike("e2e-orch-1", fp)
        assert strike_2.count == 2
        assert strike_2.triggered is True  # 2-Strike Rule
        assert wonder.should_trigger_wonder(strike_2.count) is True

        # ---- Step 3d: Wonder — write strategic reflection ----
        reflection_result = wonder.write_reflection(
            "e2e-orch-1", fp,
            "Strategic re-think: cohesion score stuck at 2. Mechanical fix has failed.",
            emit_fn=emit,
        )
        assert reflection_result.depth_after == 1
        assert reflection_result.exhausted is False
        assert Path(reflection_result.reflection_path).exists()

        # Verify wonder.triggered emitted
        wonder_events = [p for t, p in events if t == "wonder.triggered"]
        assert len(wonder_events) == 1
        assert wonder_events[0]["fingerprint"] == fp

        # ---- Step 4: event_taxonomy validation — all emitted types are KNOWN ----
        from lib.event_taxonomy import KNOWN_EVENT_TYPES
        emitted_types = {t for t, _ in events}
        # After clear(): 2nd-evaluate ac.leaf_evaluated + write_reflection wonder.triggered.
        expected_emits = {"ac.leaf_evaluated", "wonder.triggered"}
        assert expected_emits.issubset(emitted_types)
        # ALL emitted types must be in KNOWN_EVENT_TYPES (no typos / unregistered names)
        unknown = emitted_types - KNOWN_EVENT_TYPES
        assert not unknown, f"unknown event types emitted: {unknown}"


def test_e2e_wonder_depth_exhausted_event():
    """Depth cap: 5 reflections → wonder.depth_exhausted emitted."""
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        events = []
        fp = "0" * 16
        for i in range(wonder.WONDER_DEPTH_CAP):
            wonder.write_reflection(
                "e2e-cap", fp, f"reflection {i}",
                emit_fn=lambda t, p: events.append((t, p)),
            )
        depth_events = [p for t, p in events if t == "wonder.depth_exhausted"]
        assert len(depth_events) == 1
        assert depth_events[0]["depth"] == wonder.WONDER_DEPTH_CAP


TESTS = [
    test_e2e_ac_tree_wonder_loop,
    test_e2e_wonder_depth_exhausted_event,
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

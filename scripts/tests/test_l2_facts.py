#!/usr/bin/env python3
"""Tests for lib.l2_facts (Wave 16 S2 L2).

Per converged debate session debate-1779328283-9076f2 (14-LOCK sha1
59cc1bab06a1af2019763d414cf345a2db7626df):

  (a) canonicalize uniform across scalar+container (D15 LOCK + SC2 fix)
  (b) content-hash id stable across calls with same (s,p,o) (D9)
  (c) object_datatype detection for all 7 enum values (D2)
  (d) confidence = 1 - 1/(n+1) closed-form (D2 + gen-1)
  (e) writer whitelist runtime block (D5) — non-whitelisted caller raises
  (f) reader fail-open vs writer fail-closed asymmetry (D5/D6)
  (g) append + query roundtrip + latest-wins de-dup (D9 idempotency)
  (h) retract separate file + query suppression (D7)
  (i) add_evidence + evidence_for + evidence_l1_to_fact reverse lookup (D14)
  (j) p99 query <75ms @ 2k facts (D12 contract)
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _reset_modules() -> None:
    for m in list(sys.modules):
        if m.startswith(("lib.paths", "lib.l2_facts", "lib.l2_promoter")):
            del sys.modules[m]


def _with_home(fn):
    def wrap():
        with tempfile.TemporaryDirectory() as td:
            saved = os.environ.get("CLAUDE_HOME")
            os.environ["CLAUDE_HOME"] = td
            try:
                _reset_modules()
                fn()
            finally:
                if saved is None:
                    os.environ.pop("CLAUDE_HOME", None)
                else:
                    os.environ["CLAUDE_HOME"] = saved
    wrap.__name__ = fn.__name__
    return wrap


@_with_home
def test_canonicalize_uniform_across_types():
    from lib.l2_facts import canonicalize
    # Critical SC2 case: scalar None vs dict containing None must use SAME
    # encoder. Pre-fix: repr(None)='None' vs json.dumps(None)='null'.
    assert canonicalize(None) == "null"
    assert canonicalize(True) == "true"
    assert canonicalize(False) == "false"
    assert canonicalize(0) == "0"
    assert canonicalize(1.5) == "1.5"
    assert canonicalize("x") == '"x"'
    # Container path
    assert canonicalize({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonicalize([3, 1, 2]) == "[3,1,2]"
    # Nested None canonicalizes to 'null' (same as scalar) → hash coherence
    assert canonicalize({"x": None}) == '{"x":null}'
    # Unicode preserved per ensure_ascii=False
    assert canonicalize("한") == '"한"'


@_with_home
def test_content_hash_stable_across_calls():
    from lib.l2_facts import _compute_fact_id, canonicalize
    oc = canonicalize({"x": 1, "y": "a"})
    id1 = _compute_fact_id("subj", "pred", oc)
    id2 = _compute_fact_id("subj", "pred", oc)
    assert id1 == id2
    assert len(id1) == 16
    # different subject → different id
    id3 = _compute_fact_id("other", "pred", oc)
    assert id1 != id3


@_with_home
def test_object_datatype_detection_7_values():
    from lib.l2_facts import _detect_object_datatype
    assert _detect_object_datatype(None) == "none"
    assert _detect_object_datatype(True) == "bool"
    assert _detect_object_datatype(False) == "bool"
    assert _detect_object_datatype(1) == "int"
    assert _detect_object_datatype(1.5) == "float"
    assert _detect_object_datatype("x") == "str"
    assert _detect_object_datatype([1, 2]) == "list"
    assert _detect_object_datatype({"a": 1}) == "dict"


@_with_home
def test_confidence_closed_form():
    from lib.l2_facts import _compute_confidence
    assert _compute_confidence(1) == 0.5
    assert abs(_compute_confidence(2) - 2 / 3) < 1e-9
    assert _compute_confidence(3) == 0.75
    # monotonic non-decreasing
    prev = 0.0
    for n in range(1, 50):
        c = _compute_confidence(n)
        assert c >= prev
        assert c < 1.0
        prev = c


@_with_home
def test_writer_whitelist_blocks_forbidden_caller():
    """Direct simulation: spawn a fake module name in forbidden set."""
    from lib import l2_facts
    # Patch _caller_module_name to simulate a forbidden caller
    orig = l2_facts._caller_module_name
    l2_facts._caller_module_name = lambda skip=2: "engine.debate.orchestrator"
    try:
        try:
            l2_facts.append({
                "subject": "s", "predicate": "p", "object": "o",
                "object_datatype": "str", "ts_unix_ms": 1, "support_count": 1,
                "event_type": "debate", "correlation_id": "c",
                "source_module": "engine.debate.orchestrator",
            })
            raise AssertionError("expected L2WriterNotAllowedError")
        except l2_facts.L2WriterNotAllowedError as e:
            assert "forbidden set" in str(e)
    finally:
        l2_facts._caller_module_name = orig


@_with_home
def test_writer_whitelist_blocks_unresolvable_caller():
    """Unresolvable caller (None ModuleSpec) — fail closed for writes."""
    from lib import l2_facts
    orig = l2_facts._caller_module_name
    l2_facts._caller_module_name = lambda skip=2: None
    try:
        try:
            l2_facts.append({
                "subject": "s", "predicate": "p", "object": "o",
                "object_datatype": "str", "ts_unix_ms": 1, "support_count": 1,
                "event_type": "debate", "correlation_id": "c",
                "source_module": "unknown",
            })
            raise AssertionError("expected L2WriterNotAllowedError")
        except l2_facts.L2WriterNotAllowedError as e:
            assert "unresolvable" in str(e)
    finally:
        l2_facts._caller_module_name = orig


@_with_home
def test_writer_whitelist_blocks_non_listed():
    from lib import l2_facts
    orig = l2_facts._caller_module_name
    l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"  # reader, not writer
    try:
        try:
            l2_facts.append({
                "subject": "s", "predicate": "p", "object": "o",
                "object_datatype": "str", "ts_unix_ms": 1, "support_count": 1,
                "event_type": "debate", "correlation_id": "c",
                "source_module": "handlers.session.init",
            })
            raise AssertionError("expected L2WriterNotAllowedError")
        except l2_facts.L2WriterNotAllowedError as e:
            assert "writer whitelist" in str(e)
    finally:
        l2_facts._caller_module_name = orig


@_with_home
def test_reader_fails_open_for_unresolvable_caller():
    """D6 — readers fail-open on unresolvable caller (sandbox ergonomics)."""
    from lib import l2_facts
    orig = l2_facts._caller_module_name
    l2_facts._caller_module_name = lambda skip=2: None
    try:
        # Should not raise
        result = l2_facts.query()
        assert result == []
    finally:
        l2_facts._caller_module_name = orig


@_with_home
def test_reader_blocks_forbidden_caller():
    from lib import l2_facts
    orig = l2_facts._caller_module_name
    l2_facts._caller_module_name = lambda skip=2: "engine.debate.foo"
    try:
        try:
            l2_facts.query()
            raise AssertionError("expected L2ReaderNotAllowedError")
        except l2_facts.L2ReaderNotAllowedError:
            pass
    finally:
        l2_facts._caller_module_name = orig


@_with_home
def test_append_query_roundtrip_latest_wins():
    from lib import l2_facts
    orig = l2_facts._caller_module_name
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    try:
        rec = {
            "subject": "X", "predicate": "p", "object": "val1",
            "object_datatype": "str", "ts_unix_ms": 100, "support_count": 3,
            "event_type": "debate", "correlation_id": "X",
            "source_module": "lib.l2_promoter",
        }
        id1 = l2_facts.append(rec)
        # Same (subject,predicate,object) → same id
        id2 = l2_facts.append(rec)
        assert id1 == id2
        # Different object → different id
        rec2 = dict(rec, object="val2", support_count=5)
        id3 = l2_facts.append(rec2)
        assert id3 != id1
    finally:
        l2_facts._caller_module_name = orig

    # Query
    l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"
    try:
        all_facts = l2_facts.query()
        # 2 distinct ids — even though 3 physical lines (latest-wins de-dup)
        assert len({f["id"] for f in all_facts}) == 2
    finally:
        l2_facts._caller_module_name = orig


@_with_home
def test_retract_suppresses_in_query():
    from lib import l2_facts
    orig = l2_facts._caller_module_name
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    try:
        fid = l2_facts.append({
            "subject": "Y", "predicate": "p", "object": "v",
            "object_datatype": "str", "ts_unix_ms": 1, "support_count": 3,
            "event_type": "debate", "correlation_id": "Y",
            "source_module": "lib.l2_promoter",
        })
        assert l2_facts.retract(fid, reason="test")
    finally:
        l2_facts._caller_module_name = orig

    l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"
    try:
        assert l2_facts.query() == []
        # include_retracted=True surfaces it
        assert len(l2_facts.query(include_retracted=True)) == 1
    finally:
        l2_facts._caller_module_name = orig


@_with_home
def test_evidence_add_and_reverse_lookup():
    from lib import l2_facts
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    try:
        l2_facts.add_evidence("fact1", "corr-A", "L1-aaa")
        l2_facts.add_evidence("fact1", "corr-A", "L1-bbb")
        l2_facts.add_evidence("fact2", "corr-B", "L1-aaa")
    finally:
        l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"

    edges_f1 = l2_facts.evidence_for("fact1")
    assert len(edges_f1) == 2
    # Reverse lookup: L1-aaa cited by both fact1 and fact2
    refs = l2_facts.evidence_l1_to_fact("L1-aaa")
    assert sorted(refs) == ["fact1", "fact2"]


@_with_home
def test_latest_for_returns_most_recent_match():
    from lib import l2_facts
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    try:
        # Three facts with same (subject, predicate) but different objects
        for i, val in enumerate(["a", "b", "c"]):
            l2_facts.append({
                "subject": "Z", "predicate": "ev",
                "object": val, "object_datatype": "str",
                "ts_unix_ms": 100 + i, "support_count": 3,
                "event_type": "debate", "correlation_id": "Z",
                "source_module": "lib.l2_promoter",
            })
    finally:
        l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"

    latest = l2_facts.latest_for("Z", "ev")
    assert latest is not None
    # Most recent ts (object=c was appended last)
    assert latest["ts_unix_ms"] == 102


@_with_home
def test_p99_query_under_75ms_at_2k():
    """D12 LOCK — p99 < 75ms at 2k facts."""
    from lib import l2_facts
    l2_facts._caller_module_name = lambda skip=2: "lib.l2_promoter"
    try:
        # Pre-load 2000 facts
        for i in range(2000):
            l2_facts.append({
                "subject": f"S{i}", "predicate": "p",
                "object": f"v{i}", "object_datatype": "str",
                "ts_unix_ms": i, "support_count": 3,
                "event_type": "debate", "correlation_id": f"C{i}",
                "source_module": "lib.l2_promoter",
            })
    finally:
        l2_facts._caller_module_name = lambda skip=2: "handlers.session.init"

    # Measure p99 over 50 queries
    samples = []
    for _ in range(50):
        t0 = time.perf_counter()
        l2_facts.query()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    p99 = samples[-1]  # 50 samples → max ≈ p98; conservative
    assert p99 < 75.0, f"p99={p99:.2f}ms exceeds 75ms SLO at 2k facts"


TESTS = [
    test_canonicalize_uniform_across_types,
    test_content_hash_stable_across_calls,
    test_object_datatype_detection_7_values,
    test_confidence_closed_form,
    test_writer_whitelist_blocks_forbidden_caller,
    test_writer_whitelist_blocks_unresolvable_caller,
    test_writer_whitelist_blocks_non_listed,
    test_reader_fails_open_for_unresolvable_caller,
    test_reader_blocks_forbidden_caller,
    test_append_query_roundtrip_latest_wins,
    test_retract_suppresses_in_query,
    test_evidence_add_and_reverse_lookup,
    test_latest_for_returns_most_recent_match,
    test_p99_query_under_75ms_at_2k,
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

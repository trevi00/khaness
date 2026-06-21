#!/usr/bin/env python3
"""Tests for lib.wonder (v15.26 C-beta)."""
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


def test_compute_fingerprint_stable():
    from lib import wonder
    fp1 = wonder.compute_fingerprint("iterate", "cohesion", "missing-doc")
    fp2 = wonder.compute_fingerprint("iterate", "cohesion", "missing-doc")
    assert fp1 == fp2
    assert len(fp1) == 16


def test_compute_fingerprint_differs_on_inputs():
    from lib import wonder
    fp1 = wonder.compute_fingerprint("iterate", "cohesion", "missing-doc")
    fp2 = wonder.compute_fingerprint("iterate", "coupling", "missing-doc")
    fp3 = wonder.compute_fingerprint("escalate", "cohesion", "missing-doc")
    assert fp1 != fp2 != fp3


def test_record_strike_increments():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp = "a" * 16
        r1 = wonder.record_strike("orch-x", fp)
        r2 = wonder.record_strike("orch-x", fp)
        r3 = wonder.record_strike("orch-x", fp)
        assert r1.count == 1
        assert r2.count == 2
        assert r3.count == 3


def test_should_trigger_at_threshold():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp = "b" * 16
        r1 = wonder.record_strike("orch-y", fp)
        r2 = wonder.record_strike("orch-y", fp)
        assert r1.triggered is False
        assert r2.triggered is True  # 2-Strike Rule


def test_different_fingerprints_independent():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp1 = "c" * 16
        fp2 = "d" * 16
        wonder.record_strike("orch-z", fp1)
        r = wonder.record_strike("orch-z", fp2)
        assert r.count == 1
        assert r.triggered is False


def test_write_reflection_increments_depth():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp = "e" * 16
        assert wonder.depth("orch-w") == 0
        r = wonder.write_reflection("orch-w", fp, "first reflection summary")
        assert r.depth_after == 1
        assert wonder.depth("orch-w") == 1
        assert Path(r.reflection_path).exists()


def test_depth_exhausted_at_cap():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp = "f" * 16
        for i in range(wonder.WONDER_DEPTH_CAP):
            r = wonder.write_reflection("orch-cap", fp, f"reflection {i}")
        assert wonder.depth_exhausted("orch-cap") is True
        assert r.exhausted is True


def test_emit_fn_called_on_wonder_triggered():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        events = []
        wonder.write_reflection(
            "orch-emit", "1" * 16, "test", emit_fn=lambda t, p: events.append((t, p)),
        )
        assert any(t == "wonder.triggered" for t, _ in events)


def test_emit_depth_exhausted_when_cap_hit():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        events = []
        for i in range(wonder.WONDER_DEPTH_CAP):
            wonder.write_reflection(
                "orch-exh", "2" * 16, f"r{i}", emit_fn=lambda t, p: events.append((t, p)),
            )
        assert any(t == "wonder.depth_exhausted" for t, _ in events)


def test_should_trigger_wonder_pure_function():
    from lib import wonder
    assert wonder.should_trigger_wonder(1) is False
    assert wonder.should_trigger_wonder(2) is True
    assert wonder.should_trigger_wonder(3) is True


def test_invalid_sid_raises():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        try:
            wonder.record_strike("../escape", "a" * 16)
            assert False
        except ValueError:
            pass


def test_invalid_fingerprint_length_raises():
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        try:
            wonder.record_strike("orch-bad", "short")
            assert False
        except ValueError:
            pass


# ---- S1 extension tests (debate-1779255461-3fd149, wave 12) ----
# StructuredPayload TypedDict + write_reflection structured_payload kwarg.

def test_write_reflection_no_payload_byte_identical():
    """gen-3 C2 byte-identity: structured_payload=None must produce the
    SAME body as the legacy call signature. Captured-output regression."""
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp = "b" * 16
        # Inject a deterministic ts by monkey-patching time.time
        import lib.wonder as wmod
        saved_time = wmod.time.time
        wmod.time.time = lambda: 1700000000.0
        try:
            res = wonder.write_reflection("orch-byte", fp, "legacy summary text",
                                          structured_payload=None)
            body = Path(res.reflection_path).read_text(encoding="utf-8")
        finally:
            wmod.time.time = saved_time
        expected = (
            "---\n"
            "orch_sid: orch-byte\n"
            f"fingerprint: {fp}\n"
            "depth: 1\n"
            "ts: 1700000000\n"
            "---\n\n"
            "legacy summary text\n"
        )
        assert body == expected, f"byte-identity broken:\n--got--\n{body!r}\n--want--\n{expected!r}"


def test_write_reflection_with_payload_emits_nested_mapping():
    """structured_payload provided → frontmatter includes structured_payload:
    nested mapping with axis, target_skill_hint, gotcha_body sub-keys."""
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp = "c" * 16
        import lib.wonder as wmod
        saved_time = wmod.time.time
        wmod.time.time = lambda: 1700000001.0
        try:
            payload = wonder.StructuredPayload(
                axis="completeness",
                target_skill_hint="skills/_common/foo.md",
                gotcha_body="reflection insight body",
            )
            res = wonder.write_reflection("orch-yes", fp, "summary",
                                          structured_payload=payload)
            body = Path(res.reflection_path).read_text(encoding="utf-8")
        finally:
            wmod.time.time = saved_time
        # Frontmatter must include the structured_payload: nested mapping
        assert "structured_payload:\n" in body
        assert "  axis: completeness\n" in body
        assert "  target_skill_hint: skills/_common/foo.md\n" in body
        assert "  gotcha_body: reflection insight body\n" in body
        # Body still ends with the free-form summary
        assert body.endswith("summary\n")


def test_write_reflection_payload_target_hint_none_emits_yaml_null():
    """target_skill_hint=None must serialize as YAML literal `null`."""
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp = "d" * 16
        payload = wonder.StructuredPayload(
            axis="stability",
            target_skill_hint=None,
            gotcha_body="x",
        )
        res = wonder.write_reflection("orch-null", fp, "s", structured_payload=payload)
        body = Path(res.reflection_path).read_text(encoding="utf-8")
        assert "  target_skill_hint: null\n" in body


def test_validate_structured_payload_rejects_non_dict():
    from lib import wonder
    for bad in ("string", 42, ["list"], None):
        try:
            wonder._validate_structured_payload(bad)
            assert False, f"should have raised for {bad!r}"
        except ValueError:
            pass


def test_validate_structured_payload_rejects_missing_keys():
    from lib import wonder
    try:
        wonder._validate_structured_payload({"axis": "x", "gotcha_body": "y"})
        assert False
    except ValueError as e:
        assert "missing required keys" in str(e)


def test_validate_structured_payload_rejects_extra_keys():
    from lib import wonder
    try:
        wonder._validate_structured_payload({
            "axis": "x", "target_skill_hint": None,
            "gotcha_body": "y", "extra": "field",
        })
        assert False
    except ValueError as e:
        assert "unexpected keys" in str(e)


def test_validate_structured_payload_rejects_empty_strings():
    from lib import wonder
    try:
        wonder._validate_structured_payload({
            "axis": "", "target_skill_hint": None, "gotcha_body": "y",
        })
        assert False
    except ValueError:
        pass
    try:
        wonder._validate_structured_payload({
            "axis": "x", "target_skill_hint": None, "gotcha_body": "",
        })
        assert False
    except ValueError:
        pass


def test_validate_structured_payload_rejects_newlines():
    """v1 single-line constraint — no embedded \\n / \\r in any field."""
    from lib import wonder
    try:
        wonder._validate_structured_payload({
            "axis": "x", "target_skill_hint": None,
            "gotcha_body": "line1\nline2",
        })
        assert False
    except ValueError as e:
        assert "single-line" in str(e)
    try:
        wonder._validate_structured_payload({
            "axis": "ok", "target_skill_hint": "path\nwith\nnewlines",
            "gotcha_body": "y",
        })
        assert False
    except ValueError as e:
        assert "single-line" in str(e)


def test_validate_structured_payload_rejects_wrong_type():
    from lib import wonder
    try:
        wonder._validate_structured_payload({
            "axis": 42, "target_skill_hint": None, "gotcha_body": "y",
        })
        assert False
    except ValueError:
        pass
    try:
        wonder._validate_structured_payload({
            "axis": "x", "target_skill_hint": 42, "gotcha_body": "y",
        })
        assert False
    except ValueError:
        pass


def test_write_reflection_invalid_payload_raises():
    """write_reflection MUST propagate ValueError from _validate_structured_payload."""
    with tempfile.TemporaryDirectory() as td:
        _isolate(Path(td))
        from lib import wonder
        fp = "e" * 16
        try:
            wonder.write_reflection("orch-bad-payload", fp, "s",
                                    structured_payload={"axis": "x"})  # missing keys
            assert False
        except ValueError:
            pass


TESTS = [
    test_compute_fingerprint_stable,
    test_compute_fingerprint_differs_on_inputs,
    test_record_strike_increments,
    test_should_trigger_at_threshold,
    test_different_fingerprints_independent,
    test_write_reflection_increments_depth,
    test_depth_exhausted_at_cap,
    test_emit_fn_called_on_wonder_triggered,
    test_emit_depth_exhausted_when_cap_hit,
    test_should_trigger_wonder_pure_function,
    test_invalid_sid_raises,
    test_invalid_fingerprint_length_raises,
    # S1 extension tests
    test_write_reflection_no_payload_byte_identical,
    test_write_reflection_with_payload_emits_nested_mapping,
    test_write_reflection_payload_target_hint_none_emits_yaml_null,
    test_validate_structured_payload_rejects_non_dict,
    test_validate_structured_payload_rejects_missing_keys,
    test_validate_structured_payload_rejects_extra_keys,
    test_validate_structured_payload_rejects_empty_strings,
    test_validate_structured_payload_rejects_newlines,
    test_validate_structured_payload_rejects_wrong_type,
    test_write_reflection_invalid_payload_raises,
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

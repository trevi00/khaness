#!/usr/bin/env python3
"""Tests for lib.observers.evidence_fab (v15.10 D1).

Coverage map (debate-1778946602-jj7vxk D1 spec, every clause hit):
  - empty / malformed envelope → CLEAN
  - arm (a): missing file_path triggers FABRICATION_CONFIRMED
  - arm (a): existing file_path with no replay_cmd → CLEAN
  - arm (b): test_result='passed' + replay rc=0 → CLEAN
  - arm (b): test_result='passed' + replay rc!=0 twice → FABRICATION_CONFIRMED
  - arm (b): first attempt fails, second succeeds → FLAKE_OBSERVED
  - precedence: arm (a) wins over arm (b)
  - precedence: FABRICATION_CONFIRMED > FLAKE_OBSERVED across entries
  - tolerance: malformed evidence entry shape silently skipped
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.observers.evidence_fab import EvidenceVerdict, detect  # noqa: E402
from lib.replay import constants as RC  # noqa: E402

# Zero backoff for fast test execution; reset in main() defensively.
RC.REPLAY_BACKOFF_SEC = 0


def _existing(tmp: Path, name: str = "marker.txt") -> str:
    p = tmp / name
    p.write_text("ok", encoding="utf-8")
    return str(p)


def test_empty_envelope_is_clean():
    assert detect({}) == EvidenceVerdict.CLEAN
    assert detect({"evidence": []}) == EvidenceVerdict.CLEAN
    assert detect(None) == EvidenceVerdict.CLEAN
    assert detect("not-a-dict") == EvidenceVerdict.CLEAN
    assert detect({"evidence": "not-a-list"}) == EvidenceVerdict.CLEAN


def test_arm_a_missing_file_path_is_fabrication():
    envelope = {
        "evidence": [
            {"file_path": "C:/this/path/should/not/exist__evfab_test.txt"},
        ]
    }
    assert detect(envelope) == EvidenceVerdict.FABRICATION_CONFIRMED


def test_arm_a_existing_file_with_no_replay_is_clean():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        envelope = {"evidence": [{"file_path": _existing(tmp)}]}
        assert detect(envelope) == EvidenceVerdict.CLEAN


def test_arm_b_passed_with_rc_zero_is_clean():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        envelope = {
            "evidence": [
                {
                    "file_path": _existing(tmp),
                    "test_result": "passed",
                    "replay_cmd": [sys.executable, "-c", "import sys; sys.exit(0)"],
                }
            ]
        }
        assert detect(envelope) == EvidenceVerdict.CLEAN


def test_arm_b_passed_with_rc_nonzero_twice_is_fabrication():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        envelope = {
            "evidence": [
                {
                    "file_path": _existing(tmp),
                    "test_result": "passed",
                    "replay_cmd": [sys.executable, "-c", "import sys; sys.exit(1)"],
                }
            ]
        }
        assert detect(envelope) == EvidenceVerdict.FABRICATION_CONFIRMED


def test_arm_b_flake_observed_first_fail_then_pass():
    """First attempt fails (file absent), second succeeds (file present).

    Uses a token file that the replay creates on its first invocation;
    second invocation finds it and exits 0. This models a true flake
    pattern (env warm-up) without hitting fabrication territory.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        token = tmp / "warmup_token"
        script = (
            "import os, sys; p=os.environ['WARMUP']; "
            "ok=os.path.exists(p); open(p,'w').close(); "
            "sys.exit(0 if ok else 1)"
        )
        envelope = {
            "evidence": [
                {
                    "file_path": _existing(tmp, "marker_b.txt"),
                    "test_result": "passed",
                    "replay_cmd": [sys.executable, "-c", script],
                }
            ]
        }
        import os
        os.environ["WARMUP"] = str(token)
        try:
            assert detect(envelope) == EvidenceVerdict.FLAKE_OBSERVED
        finally:
            os.environ.pop("WARMUP", None)


def test_arm_a_short_circuits_arm_b():
    """Arm (a) FABRICATION must win even if arm (b) would only see flake."""
    envelope = {
        "evidence": [
            {"file_path": "C:/never/exists__evfab_short.txt"},
            {
                "file_path": "C:/never/exists__evfab_short2.txt",
                "test_result": "passed",
                "replay_cmd": [sys.executable, "-c", "import sys; sys.exit(0)"],
            },
        ]
    }
    assert detect(envelope) == EvidenceVerdict.FABRICATION_CONFIRMED


def test_worst_case_across_entries():
    """FABRICATION_CONFIRMED in arm (b) for entry 2 overrides flake in entry 1.

    Both entries pass arm (a). Entry 1 flakes (fail→pass), Entry 2
    fabricates (fail→fail).
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        token = tmp / "across_token"
        script_flake = (
            "import os, sys; p=os.environ['XTOK']; "
            "ok=os.path.exists(p); open(p,'w').close(); "
            "sys.exit(0 if ok else 1)"
        )
        envelope = {
            "evidence": [
                {
                    "file_path": _existing(tmp, "m1.txt"),
                    "test_result": "passed",
                    "replay_cmd": [sys.executable, "-c", script_flake],
                },
                {
                    "file_path": _existing(tmp, "m2.txt"),
                    "test_result": "passed",
                    "replay_cmd": [sys.executable, "-c", "import sys; sys.exit(2)"],
                },
            ]
        }
        import os
        os.environ["XTOK"] = str(token)
        try:
            assert detect(envelope) == EvidenceVerdict.FABRICATION_CONFIRMED
        finally:
            os.environ.pop("XTOK", None)


def test_malformed_evidence_entries_are_skipped():
    """Non-dict, missing keys, non-string file_path — all degrade to CLEAN."""
    envelope = {
        "evidence": [
            "not-a-dict",
            42,
            None,
            {},                              # no keys at all
            {"file_path": 123},              # wrong type
            {"file_path": ""},               # empty string
        ]
    }
    assert detect(envelope) == EvidenceVerdict.CLEAN


def test_nested_envelope_shape_is_accepted():
    """Some callers pass {'envelope': {'evidence': [...]}}; both work."""
    envelope = {
        "envelope": {
            "evidence": [{"file_path": "C:/no/such/path__nested.txt"}]
        }
    }
    assert detect(envelope) == EvidenceVerdict.FABRICATION_CONFIRMED


def test_replay_timeout_is_treated_as_failure():
    """A replay that hangs past timeout returns rc=124 → fabrication on N=2."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        envelope = {
            "evidence": [
                {
                    "file_path": _existing(tmp, "m.txt"),
                    "test_result": "passed",
                    "replay_cmd": [
                        sys.executable, "-c",
                        "import time; time.sleep(5)",
                    ],
                    "timeout": 0.2,
                }
            ]
        }
        assert detect(envelope) == EvidenceVerdict.FABRICATION_CONFIRMED


TESTS = [
    test_empty_envelope_is_clean,
    test_arm_a_missing_file_path_is_fabrication,
    test_arm_a_existing_file_with_no_replay_is_clean,
    test_arm_b_passed_with_rc_zero_is_clean,
    test_arm_b_passed_with_rc_nonzero_twice_is_fabrication,
    test_arm_b_flake_observed_first_fail_then_pass,
    test_arm_a_short_circuits_arm_b,
    test_worst_case_across_entries,
    test_malformed_evidence_entries_are_skipped,
    test_nested_envelope_shape_is_accepted,
    test_replay_timeout_is_treated_as_failure,
]


def main() -> int:
    RC.REPLAY_BACKOFF_SEC = 0
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

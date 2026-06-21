#!/usr/bin/env python3
"""Tests for validators/falsy_zero.py — `X or default` falsy-zero AST lint."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _sev(findings, sev):
    return [f for f in findings if f.severity == sev]


def test_catches_original_l2_promoter_bug_as_high():
    """The exact shape that flaked l2_promoter: a name bound from min() then
    `name or int(time.time()*1000)`. Must be HIGH (numeric guard -> nondeterministic)."""
    from validators.falsy_zero import scan_source
    src = (
        "import time\n"
        "def project(members):\n"
        "    earliest_ts = min((m['ts'] for m in members), default=0)\n"
        "    return earliest_ts or int(time.time() * 1000)\n"
    )
    hi = _sev(scan_source(src), "high")
    assert len(hi) == 1 and hi[0].rule == "falsy-zero-nondeterministic"
    assert "earliest_ts" in hi[0].guard and "time.time" in hi[0].fallback


def test_inline_numeric_call_or_nondeterministic_is_high():
    from validators.falsy_zero import scan_source
    src = "import random\nx = len(items) or random.random()\n"
    hi = _sev(scan_source(src), "high")
    assert len(hi) == 1 and "len()" in hi[0].guard and "random" in hi[0].fallback


def test_numeric_guard_meaningful_fallback_is_medium():
    """sum(...) or 1 — masks a valid 0 with a DIFFERENT value (the div-by-zero guard)."""
    from validators.falsy_zero import scan_source
    src = "total = sum(weights) or 1\n"
    med = _sev(scan_source(src), "medium")
    assert len(med) == 1 and med[0].rule == "falsy-zero-numeric"


def test_x_or_falsy_constant_is_not_flagged():
    """`rec.get(k, 0) or 0` and `n or ''` mask nothing — harmless normalization."""
    from validators.falsy_zero import scan_source
    src = (
        "a = int(rec.get('n', 0) or 0)\n"
        "b = count or 0\n"
        "c = total or 0.0\n"
        "d = items or []\n"
    )
    # b/c/d guards aren't numeric anyway; a's fallback is falsy-0 -> excluded
    assert scan_source(src) == []


def test_non_numeric_guard_is_not_flagged():
    """`name or 'default'` / `cfg or {}` where the guard isn't numeric — the common,
    intentional default-substitution idiom. No false positive."""
    from validators.falsy_zero import scan_source
    src = (
        "label = user_label or 'anonymous'\n"
        "opts = passed_opts or {'k': 1}\n"
        "start = maybe or compute()\n"
    )
    assert scan_source(src) == []


def test_suppression_marker_silences():
    from validators.falsy_zero import scan_source
    src = "total = sum(w) or 1  # falsy-zero-ok: div guard\n"
    assert scan_source(src) == []
    src2 = "total = sum(w) or 1  # noqa\n"
    assert scan_source(src2) == []


def test_datetime_now_fallback_is_high():
    from validators.falsy_zero import scan_source
    src = "import datetime\nstamp = round(x) or datetime.datetime.now()\n"
    hi = _sev(scan_source(src), "high")
    assert len(hi) == 1 and "now()" in hi[0].fallback


def test_name_numeric_via_get_default_tracked():
    """A name bound from d.get(k, 0) is numeric -> `name or clock` is HIGH."""
    from validators.falsy_zero import scan_source
    src = (
        "import time\n"
        "def f(d):\n"
        "    n = d.get('n', 0)\n"
        "    return n or time.monotonic()\n"
    )
    assert len(_sev(scan_source(src), "high")) == 1


def test_syntax_error_failsoft():
    from validators.falsy_zero import scan_source
    assert scan_source("def (:\n  oops") == []


def test_live_tree_has_no_high_findings():
    """The production tree must carry ZERO high (nondeterministic) falsy-zero bugs —
    the l2_promoter fix closed the only known one. A new HIGH = a real regression."""
    from validators.falsy_zero import scan_tree
    high = _sev(scan_tree(_SCRIPTS), "high")
    assert high == [], f"unexpected HIGH falsy-zero finding(s): {[(f.file, f.line) for f in high]}"


def test_main_runs_clean_or_advisory():
    """main() never raises and prints either PASS or an advisory WARN summary."""
    import io
    import contextlib
    from validators import falsy_zero
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        falsy_zero.main()
    out = buf.getvalue()
    assert "falsy_zero" in out and ("[PASS]" in out or "[WARN]" in out)


def main() -> int:
    tests = [
        test_catches_original_l2_promoter_bug_as_high,
        test_inline_numeric_call_or_nondeterministic_is_high,
        test_numeric_guard_meaningful_fallback_is_medium,
        test_x_or_falsy_constant_is_not_flagged,
        test_non_numeric_guard_is_not_flagged,
        test_suppression_marker_silences,
        test_datetime_now_fallback_is_high,
        test_name_numeric_via_get_default_tracked,
        test_syntax_error_failsoft,
        test_live_tree_has_no_high_findings,
        test_main_runs_clean_or_advisory,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())

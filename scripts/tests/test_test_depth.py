#!/usr/bin/env python3
"""Tests for the test_depth validator (M26 surface≠real). Un-skips it in run_all.

Uses SYNTHETIC test files in a temp dir (deterministic — not dependent on the live suite's
evolving contents). Auto-discovered via main()->int.
"""
from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import validators.test_depth as vmod  # noqa: E402

_SURFACE = '''
def test_no_assert():
    do_something()  # surface-only: verifies only "did not crash"

def test_try_except_pass():
    try:
        boom()
    except ValueError:
        pass  # never asserts the raise happened -> cannot fail
'''

_DEEP = '''
def test_real_assert():
    assert add(2, 2) == 4

def test_self_assert(self):
    self.assertEqual(add(2, 2), 4)

def test_print_fail_convention():
    if add(2, 2) != 4:
        print("[FAIL] add broken")

def test_check_helper():
    _check(add(2, 2) == 4, "add")

def test_raises_ctx():
    with pytest.raises(ValueError):
        boom()

def test_explicit_raise():
    if add(2, 2) != 4:
        raise AssertionError("broken")
'''


def _scan(text: str):
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "test_x.py").write_text(text, encoding="utf-8")
        return {fn for _f, fn in vmod.find_surface_only(Path(td))}


def test_flags_surface_only():
    flagged = _scan(_SURFACE)
    assert flagged == {"test_no_assert", "test_try_except_pass"}, flagged


def test_does_not_flag_real_assertions():
    # all six depth conventions recognized -> none flagged
    assert _scan(_DEEP) == set()


def test_validator_pass_when_clean():
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "test_x.py").write_text(_DEEP, encoding="utf-8")
        buf = io.StringIO()
        with mock.patch.object(vmod, "_TESTS_DIR", Path(td)), redirect_stdout(buf):
            vmod.main()
        assert "[PASS]" in buf.getvalue() and "[WARN]" not in buf.getvalue()


def test_validator_warns_not_fails_on_surface():
    # advisory: emits [WARN], never [FAIL] (must not trip run_all's failure regex)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "test_x.py").write_text(_SURFACE, encoding="utf-8")
        buf = io.StringIO()
        with mock.patch.object(vmod, "_TESTS_DIR", Path(td)), redirect_stdout(buf):
            vmod.main()
        out = buf.getvalue()
        assert "[WARN]" in out and "[FAIL]" not in out


def test_validator_registered_in_builtin():
    from validators import _BUILTIN
    assert "test_depth" in _BUILTIN


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

#!/usr/bin/env python3
"""Tests for the exit_contract_coverage validator (M32). Un-skips it in run_all.

Synthetic CLI + test files in temp dirs (deterministic — not dependent on the live
tree). Verifies the forward-looking guard: a documented semantic exit code (3/4/5)
with no asserting test is a GAP; coverage via a literal digit OR a resolved EXIT_*
constant closes it; generic codes 0/1/2 are ignored. Auto-discovered via main()->int.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import validators.exit_contract_coverage as vmod  # noqa: E402


def _scan(cli_files: dict[str, str], test_files: dict[str, str]):
    with tempfile.TemporaryDirectory() as td:
        cli_dir = Path(td) / "cli"
        tests_dir = Path(td) / "tests"
        cli_dir.mkdir()
        tests_dir.mkdir()
        for name, src in cli_files.items():
            (cli_dir / name).write_text(src, encoding="utf-8")
        for name, src in test_files.items():
            (tests_dir / name).write_text(src, encoding="utf-8")
        return dict(vmod.find_exit_contract_gaps(cli_dir, tests_dir))


# ---- documented_semantic_codes ----

def test_documented_codes_inline_and_enum():
    assert vmod.documented_semantic_codes("...exit 3 = SPAWN, exit 4 = error") == {3, 4}
    enum = "Control:\n  exit codes:\n  3 = CONVERGED\n  4 = ERROR\n  5 = ESCALATE\n"
    assert vmod.documented_semantic_codes(enum) == {3, 4, 5}
    # 0/1/2 are not semantic -> never counted
    assert vmod.documented_semantic_codes("exit 0 ok, exit 2 usage") == set()


def test_enum_requires_exit_context():
    # a bare "3 = x" with no 'exit' mention is NOT trusted as an exit code
    assert vmod.documented_semantic_codes("the ratio 3 = three thirds") == set()


# ---- gap detection ----

_CLI_WITH_CONTRACT = '''"""mytool — does a thing.

exit codes:
  0 = ok
  3 = converged
  4 = error
"""
EXIT_OK = 0
EXIT_CONVERGED = 3
EXIT_ERROR = 4
def main():
    return EXIT_CONVERGED
'''


def test_gap_when_no_test_asserts():
    gaps = _scan({"mytool.py": _CLI_WITH_CONTRACT}, {})
    assert gaps.get("mytool.py") == [3, 4]  # both semantic codes uncovered


def test_no_gap_when_literal_asserts():
    tst = "import cli.mytool\ndef test_x():\n    assert code == 3\n    assert rc == 4\n"
    gaps = _scan({"mytool.py": _CLI_WITH_CONTRACT}, {"test_mytool.py": tst})
    assert "mytool.py" not in gaps  # both covered by literal asserts


def test_no_gap_when_named_constant_asserts():
    # test asserts via EXIT_* constants -> resolved to 3/4 -> covered
    tst = ("import cli.mytool as m\ndef test_x():\n"
           "    assert code == m.EXIT_CONVERGED\n    assert rc == m.EXIT_ERROR\n")
    gaps = _scan({"mytool.py": _CLI_WITH_CONTRACT}, {"test_mytool.py": tst})
    assert "mytool.py" not in gaps


def test_partial_coverage_flags_only_uncovered():
    tst = "import cli.mytool\ndef test_x():\n    assert code == 3\n"  # covers 3, not 4
    gaps = _scan({"mytool.py": _CLI_WITH_CONTRACT}, {"test_mytool.py": tst})
    assert gaps.get("mytool.py") == [4]


def test_cli_without_semantic_contract_ignored():
    cli = '"""plain tool.\n\nexit 0 ok, exit 2 usage only.\n"""\ndef main():\n    return 0\n'
    gaps = _scan({"plain.py": cli}, {})
    assert gaps == {}  # documents no semantic code -> never considered


def test_unrelated_test_does_not_cover():
    # a test that does NOT reference the cli stem must not count toward coverage
    tst = "def test_other():\n    assert code == 3\n"  # no 'mytool' reference
    gaps = _scan({"mytool.py": _CLI_WITH_CONTRACT}, {"test_other.py": tst})
    assert gaps.get("mytool.py") == [3, 4]


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

#!/usr/bin/env python3
"""Tests for AdvisoryAck unified ack store (Wave 19).

Per converged debate session debate-1777989789-7c3571 (gen 3,
snapshot_hash=89f6af6eee69a1f60a57fa4dbbdbe469a1742ee3) the test budget
is delta=3 — exactly:

  (a) behavioral resolve(name) + ack(key) round-trip exercising both
      registered advisories (NOT mere REGISTRY dict membership)
  (b) argparse-error-path coverage for the cli/advisory_ack alias
      (missing args, unknown advisory name)
"""
from __future__ import annotations

import importlib
import io
import sys
import tempfile
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_registry_to_tmp(tmp: Path) -> None:
    """Point both REGISTRY entries at temp paths so writes don't pollute state."""
    from lib import advisory_ack as AA
    AA.REGISTRY["debate_doubts"].ack_path = tmp / "debate_doubts.txt"
    AA.REGISTRY["strict_design"].ack_path = tmp / "strict_design.txt"


def test_resolve_and_ack_roundtrip_for_both_advisories():
    """Behavioral: resolve('<name>').ack(key) actually persists and load() returns it.

    Covers both registered advisories. Asserts (i) writes go to the
    instance's ack_path (not legacy), (ii) ack returns True on add /
    False on duplicate, (iii) load() reflects the new key, (iv) the
    other advisory's store is independent (no cross-contamination),
    (v) resolve('unknown') raises KeyError with helpful message.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _redirect_registry_to_tmp(tmp)
        from lib.advisory_ack import resolve, REGISTRY

        dd = resolve("debate_doubts")
        sd = resolve("strict_design")

        assert dd is REGISTRY["debate_doubts"]
        assert sd is REGISTRY["strict_design"]

        assert dd.ack("debate-1234-abc") is True
        assert dd.ack("debate-1234-abc") is False
        assert dd.load() == {"debate-1234-abc"}

        assert sd.ack("2026-01-01T00:00:00Z") is True
        assert sd.load() == {"2026-01-01T00:00:00Z"}
        assert dd.load() == {"debate-1234-abc"}

        try:
            resolve("nonexistent")
        except KeyError as e:
            msg = str(e)
            assert "nonexistent" in msg
            assert "debate_doubts" in msg and "strict_design" in msg
        else:
            raise AssertionError("resolve('nonexistent') should raise KeyError")


def test_alias_cli_error_paths():
    """Argparse-error-path: missing args + unknown advisory + happy delegation.

    Covers: (i) zero args → usage on stderr, rc=2; (ii) one arg → usage
    on stderr, rc=2; (iii) unknown advisory → 'unknown advisory' stderr,
    rc=2; (iv) happy path → delegates with rewritten argv to the
    per-command CLI's main (verified via monkeypatch, not stdout
    capture, because per-command mains call sys.stdout.reconfigure
    which StringIO does not implement).
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _redirect_registry_to_tmp(tmp)
        from cli.advisory_ack import main as alias_main

        err = io.StringIO()
        with redirect_stderr(err):
            rc_no_args = alias_main([])
        assert rc_no_args == 2
        assert "usage" in err.getvalue()

        err = io.StringIO()
        with redirect_stderr(err):
            rc_one_arg = alias_main(["debate_doubts"])
        assert rc_one_arg == 2
        assert "usage" in err.getvalue()

        err = io.StringIO()
        with redirect_stderr(err):
            rc_unknown = alias_main(["whoops_typo", "key"])
        assert rc_unknown == 2
        assert "unknown advisory" in err.getvalue()

        import cli.debate_doubts as DD
        captured: dict = {}
        original_main = DD.main

        def fake_main(argv):
            captured["argv"] = list(argv)
            return 0

        DD.main = fake_main
        try:
            rc_happy = alias_main(["debate_doubts", "test-sid-001"])
        finally:
            DD.main = original_main

        assert rc_happy == 0
        assert captured["argv"] == ["--acknowledge", "test-sid-001"]


def test_alias_module_does_not_import_argparse():
    """Structural invariant lock — Architect Gen 3 self_doubt mitigation.

    The Wave 19 Architect verdict approved cli_unification='per_command_with_alias'
    on the explicit condition that the alias is an ARGV-REWRITE shim, NOT a
    new argparse surface. The verdict's self_doubt note flagged that this
    relies on code-review discipline, not a structural guarantee.

    This test IS the structural guarantee: parse cli/advisory_ack.py source
    with the AST and assert no `import argparse` / `from argparse import ...`
    statement exists. Future contributors who try to add argparse for a
    list/json/help subcommand will fail this test before merging.
    """
    import ast
    source_path = _SCRIPTS / "cli" / "advisory_ack.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "argparse", (
                    f"cli/advisory_ack.py must NOT import argparse "
                    f"(Wave 19 invariant — alias is argv-rewrite shim, "
                    f"not new CLI surface). Found: import {alias.name}"
                )
        if isinstance(node, ast.ImportFrom):
            assert node.module != "argparse", (
                f"cli/advisory_ack.py must NOT import from argparse "
                f"(Wave 19 invariant). Found: from {node.module} import ..."
            )


TESTS = [
    test_resolve_and_ack_roundtrip_for_both_advisories,
    test_alias_cli_error_paths,
    test_alias_module_does_not_import_argparse,
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

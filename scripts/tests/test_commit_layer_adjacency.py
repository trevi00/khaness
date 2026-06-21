#!/usr/bin/env python3
"""Unit tests for validators/commit_layer_adjacency.py.

Tests layer classification, allowed/forbidden import directions, and the
full-tree mode that the live tree currently passes.

Run:
    cd ~/.claude/scripts && python -m tests.test_commit_layer_adjacency
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import commit_layer_adjacency as cla  # noqa: E402


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_classify_lib():
    p = _SCRIPTS / "lib" / "logging.py"
    assert cla._classify(p) == "lib"


def test_classify_handlers():
    p = _SCRIPTS / "handlers" / "session" / "init.py"
    assert cla._classify(p) == "handlers"


def test_classify_outside_returns_none():
    p = _SCRIPTS / "tests" / "test_hashline.py"
    assert cla._classify(p) is None


def test_imported_layer_recognized():
    assert cla._imported_layer("lib.logging") == "lib"
    assert cla._imported_layer("engine.cli") == "engine"


def test_imported_layer_external_returns_none():
    assert cla._imported_layer("os") is None
    assert cla._imported_layer("json.decoder") is None
    assert cla._imported_layer("") is None


def test_check_file_lib_intra_ok():
    # lib/logging.py imports from .paths (intra-lib) — must be PASS
    p = _SCRIPTS / "lib" / "logging.py"
    findings = cla._check_file(p)
    assert findings == [], f"lib intra-imports should be clean, got: {findings}"


def test_check_file_handler_to_engine_fails(tmp_root_setup=None):
    # Synthesize a violating file in a tempdir mirroring scripts/handlers/...
    # We can't write under scripts/handlers without polluting the tree, so we
    # patch _SCRIPTS classification by calling _check_file with absolute paths
    # under a tempdir; classification needs the file to be relative to _SCRIPTS,
    # so this test validates the AST/classification logic via direct construction.
    src = """from engine.cli import main\n"""
    with tempfile.TemporaryDirectory() as td:
        # Place the file in a fake handlers/ dir under a fake scripts/ root.
        fake_scripts = Path(td) / "scripts"
        bad = fake_scripts / "handlers" / "fake_handler.py"
        _write(bad, src)
        # Patch _SCRIPTS for this test
        saved = cla._SCRIPTS
        try:
            cla._SCRIPTS = fake_scripts
            findings = cla._check_file(bad)
        finally:
            cla._SCRIPTS = saved
    assert any("handlers -> engine" in f for f in findings), (
        f"expected handlers->engine violation, got: {findings}"
    )


def test_check_file_engine_to_handler_ok():
    # engine importing from handlers IS allowed (engine is highest layer)
    src = """from handlers.session.init import main\n"""
    with tempfile.TemporaryDirectory() as td:
        fake_scripts = Path(td) / "scripts"
        ok = fake_scripts / "engine" / "fake_engine.py"
        _write(ok, src)
        saved = cla._SCRIPTS
        try:
            cla._SCRIPTS = fake_scripts
            findings = cla._check_file(ok)
        finally:
            cla._SCRIPTS = saved
    assert findings == [], f"engine->handlers should be allowed, got: {findings}"


def test_check_file_lib_to_validators_fails():
    src = """from validators.hashline import main\n"""
    with tempfile.TemporaryDirectory() as td:
        fake_scripts = Path(td) / "scripts"
        bad = fake_scripts / "lib" / "fake_lib.py"
        _write(bad, src)
        saved = cla._SCRIPTS
        try:
            cla._SCRIPTS = fake_scripts
            findings = cla._check_file(bad)
        finally:
            cla._SCRIPTS = saved
    assert any("lib -> validators" in f for f in findings), (
        f"expected lib->validators violation, got: {findings}"
    )


def test_classify_cli():
    # cli is now the top tier (harness-full-review rank 2).
    p = _SCRIPTS / "cli" / "observe.py"
    assert cla._classify(p) == "cli"


def test_check_file_cli_to_lib_ok():
    # cli importing any lower layer IS allowed (cli is the ceiling).
    src = """from lib.logging import log\nfrom engine.debate import run\n"""
    with tempfile.TemporaryDirectory() as td:
        fake_scripts = Path(td) / "scripts"
        ok = fake_scripts / "cli" / "fake_cli.py"
        _write(ok, src)
        saved = cla._SCRIPTS
        try:
            cla._SCRIPTS = fake_scripts
            findings = cla._check_file(ok)
        finally:
            cla._SCRIPTS = saved
    assert findings == [], f"cli->lower should be allowed, got: {findings}"


def test_check_file_lib_to_cli_fails():
    # The closed blind spot: a lower layer importing cli is the most severe
    # reverse edge and was previously invisible (cli unmodeled -> target None).
    src = """from cli.observe import main\n"""
    with tempfile.TemporaryDirectory() as td:
        fake_scripts = Path(td) / "scripts"
        bad = fake_scripts / "lib" / "fake_lib.py"
        _write(bad, src)
        saved = cla._SCRIPTS
        try:
            cla._SCRIPTS = fake_scripts
            findings = cla._check_file(bad)
        finally:
            cla._SCRIPTS = saved
    assert any("lib -> cli" in f for f in findings), (
        f"expected lib->cli violation (blind spot closed), got: {findings}"
    )


def test_full_tree_currently_clean():
    # Live invariant: after W0 fix, the real tree should be clean.
    buf = io.StringIO()
    saved_argv = sys.argv[:]
    sys.argv = ["commit_layer_adjacency", "--all"]
    try:
        with contextlib.redirect_stdout(buf):
            cla.main()
    finally:
        sys.argv = saved_argv
    out = buf.getvalue()
    assert "[PASS]" in out and "[FAIL]" not in out, f"expected clean PASS, got:\n{out}"


TESTS = [
    test_classify_lib,
    test_classify_handlers,
    test_classify_outside_returns_none,
    test_imported_layer_recognized,
    test_imported_layer_external_returns_none,
    test_check_file_lib_intra_ok,
    test_check_file_handler_to_engine_fails,
    test_check_file_engine_to_handler_ok,
    test_check_file_lib_to_validators_fails,
    test_classify_cli,
    test_check_file_cli_to_lib_ok,
    test_check_file_lib_to_cli_fails,
    test_full_tree_currently_clean,
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
    total = len(TESTS)
    if failed:
        print(f"\n[FAIL] {failed}/{total} tests failed")
        return 1
    print(f"\n[OK] {total} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

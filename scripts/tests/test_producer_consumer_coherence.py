#!/usr/bin/env python3
"""Tests for validators/producer_consumer_coherence.py — the dead-seam auditor.

Drives the full scan() pipeline over a SYNTHETIC scripts tree (monkeypatched roots)
so each check is exercised on controlled input: telemetry reader/writer mismatch (bug#2),
marker_keys consumed-but-unwritten (bug#1), 0-caller export (bug#3), the .md-wired clear,
and the in-line `# coherence-ok:` allowlist. Plus a live-tree regression guard that HIGH==0.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _build_tree(root: Path) -> None:
    """Synthetic scripts/ tree under `root` with one of each seam class."""
    (root / "lib").mkdir(parents=True)
    (root / "cli").mkdir(parents=True)
    (root / "commands").mkdir(parents=True)  # _HOME/commands (md wiring)
    # paths shim so TELEMETRY_DIR Name resolves in AST (value irrelevant — AST only)
    (root / "lib" / "logging.py").write_text(
        "def log_telemetry(category, record):\n    pass\n", encoding="utf-8")
    # a producer writing category 'live' (string literal) + 'const_cat' (module const)
    (root / "lib" / "producer.py").write_text(
        "from lib.logging import log_telemetry\n"
        "CAT = 'const_cat'\n"
        "def emit():\n"
        "    log_telemetry('live', {})\n"
        "    log_telemetry(CAT, {})\n"
        "    rec = {}\n"
        "    rec['wired_marker'] = True\n",  # literal write-key
        encoding="utf-8")
    # consumer: reads live.jsonl (clean), const_cat.jsonl (clean via const), dead.jsonl (HIGH)
    (root / "lib" / "consumer.py").write_text(
        "from lib.paths import TELEMETRY_DIR\n"
        "def read_live():\n"
        "    return (TELEMETRY_DIR / 'live.jsonl', TELEMETRY_DIR / 'const_cat.jsonl',\n"
        "            TELEMETRY_DIR / 'dead.jsonl')\n",
        encoding="utf-8")
    # marker consumer: 'wired_marker' has a writer (clean); 'orphan_marker' has none (HIGH)
    (root / "lib" / "markers.py").write_text(
        "def count(rec):\n"
        "    return _m(rec, marker_keys=('wired_marker',)) + _m(rec, marker_keys=('orphan_marker',))\n"
        "def _m(rec, marker_keys=()):\n"
        "    return 0\n",
        encoding="utf-8")
    # caller graph: used_fn is called; unused_fn is referenced nowhere (MED);
    # md_fn is wired only in commands/*.md (must be cleared)
    (root / "lib" / "graph.py").write_text(
        "def used_fn():\n    return 1\n"
        "def unused_fn():\n    return 2\n"
        "def md_fn():\n    return 3\n"
        "def _driver():\n    return used_fn()\n",
        encoding="utf-8")
    (root / "commands" / "wire.md").write_text(
        "Call `lib.graph.md_fn()` after the verdict.\n", encoding="utf-8")
    # paths stub (TELEMETRY_DIR Name target)
    (root / "lib" / "paths.py").write_text("TELEMETRY_DIR = None\n", encoding="utf-8")


def _patched(root: Path):
    import validators.producer_consumer_coherence as pcc
    pcc._SCRIPTS = root
    pcc._HOME = root  # commands/ live directly under root in the fixture
    return pcc


def test_telemetry_mismatch_is_high():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "scripts"
        _build_tree(root)
        pcc = _patched(root)
        r = pcc.scan(include_med=False)
        joined = "\n".join(r["high"])
        assert "dead.jsonl" in joined, r["high"]
        assert "live.jsonl" not in joined        # literal producer clears it
        assert "const_cat.jsonl" not in joined   # module-const producer clears it


def test_marker_key_unwritten_is_high():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "scripts"
        _build_tree(root)
        pcc = _patched(root)
        r = pcc.scan(include_med=False)
        joined = "\n".join(r["high"])
        assert "orphan_marker" in joined, r["high"]
        assert "wired_marker" not in joined      # has a literal writer


def test_zero_caller_is_med_and_md_wired_cleared():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "scripts"
        _build_tree(root)
        pcc = _patched(root)
        r = pcc.scan(include_med=True)
        med = "\n".join(r["med"])
        # quote-wrapped to avoid 'used_fn' matching the 'unused_fn' finding substring
        assert "'unused_fn'" in med, r["med"]
        assert "'used_fn'" not in med            # called by _driver
        assert "'md_fn'" not in med              # wired in commands/wire.md (affordance)


def test_allowlist_suppresses_to_warn():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "scripts"
        _build_tree(root)
        # allowlist the dead.jsonl read
        c = (root / "lib" / "consumer.py").read_text(encoding="utf-8")
        c = c.replace("TELEMETRY_DIR / 'dead.jsonl')",
                      "TELEMETRY_DIR / 'dead.jsonl')  # coherence-ok: legacy, removed next release")
        (root / "lib" / "consumer.py").write_text(c, encoding="utf-8")
        pcc = _patched(root)
        r = pcc.scan(include_med=False)
        assert not any("dead.jsonl" in h for h in r["high"]), r["high"]
        assert any("dead.jsonl" in w for w in r["warn"]), r["warn"]


def test_empty_reason_allowlist_still_fails():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "scripts"
        _build_tree(root)
        c = (root / "lib" / "consumer.py").read_text(encoding="utf-8")
        c = c.replace("TELEMETRY_DIR / 'dead.jsonl')",
                      "TELEMETRY_DIR / 'dead.jsonl')  # coherence-ok:")
        (root / "lib" / "consumer.py").write_text(c, encoding="utf-8")
        pcc = _patched(root)
        r = pcc.scan(include_med=False)
        assert any("dead.jsonl" in h and "EMPTY reason" in h for h in r["high"]), r["high"]


def test_scan_shape():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "scripts"
        _build_tree(root)
        pcc = _patched(root)
        r = pcc.scan(include_med=False)
        assert set(r.keys()) == {"high", "med", "info", "warn"}
        assert r["med"] == []  # MED only when include_med=True


def test_live_tree_high_is_zero_regression_guard():
    """The real harness tree must stay coherent: HIGH==0 (bug#1 + bug#2 fixed,
    shim-hits allowlisted). A future telemetry/marker dead-seam trips this."""
    # fresh import with real roots (other tests mutated module globals)
    for m in list(sys.modules):
        if m.endswith("producer_consumer_coherence"):
            del sys.modules[m]
    from validators import producer_consumer_coherence as pcc
    r = pcc.scan(include_med=False)
    assert len(r["high"]) == 0, f"live HIGH dead-seams: {r['high']}"


def main() -> int:
    tests = [
        test_telemetry_mismatch_is_high,
        test_marker_key_unwritten_is_high,
        test_zero_caller_is_med_and_md_wired_cleared,
        test_allowlist_suppresses_to_warn,
        test_empty_reason_allowlist_still_fails,
        test_scan_shape,
        test_live_tree_high_is_zero_regression_guard,
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

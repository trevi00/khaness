#!/usr/bin/env python3
"""Unit tests for validators/doc_code_drift (advisory doc↔code drift validator).

Hermetic: name-checks use the _module_reader injection hook (no real module
reads); the only real-FS touch is the final smoke test asserting main() runs
on the live vault without crashing.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import doc_code_drift as d  # noqa: E402
from lib import doc_drift_common as ddc  # noqa: E402 — reader hook moved here (D0); patch THIS

# Synthetic module source — re-export, __all__, class, methods, defs.
STUB = (
    "from .helpers import reexported_fn\n"
    "import os\n"
    "class SearchIndex:\n"
    "    def search(self, q): ...\n"
    "def should_dispatch(fingerprint, sid, *, strike_count): ...\n"
    "def load_counter(sid): ...\n"
    '__all__ = ["alled_name"]\n'
)


def test_collect_symbols_reexport_and_all_aware():
    calls, types = d.collect_module_symbols(STUB)
    assert {"should_dispatch", "load_counter", "search", "SearchIndex"} <= calls
    assert "reexported_fn" in calls, "ImportFrom alias must count (re-export aware)"
    assert "alled_name" in calls, "__all__ literal must count"
    assert "SearchIndex" in types and "should_dispatch" not in types


def test_extract_fenced_block_not_silently_dead():
    # The Critic's killer case: ~34/44 cards put signatures in fenced ```python.
    card = "## Public surface\n\n```python\ndef main() -> None\n```\n\n## Next\n"
    calls, _ = d.extract_card_claims(card)
    assert "main" in calls


def test_extract_prose_backtick_calls():
    card = "## Public surface\n\n`record_strike(orch_sid)` / `load_counter(sid)`\n\n## X\n"
    calls, _ = d.extract_card_claims(card)
    assert {"record_strike", "load_counter"} <= calls


def test_extract_method_style_and_return_type():
    card = ("## Public surface\n\n```python\nappend(entry: dict)\n```\n\n"
            "`recompute() -> CascadeResult`\n\n## X\n")
    calls, types = d.extract_card_claims(card)
    assert "append" in calls and "recompute" in calls
    assert "CascadeResult" in types  # TitleCase after -> ; not a builtin


def test_fp_guard_prose_has_no_claims():
    card = "## Public surface\n\nThis dispatcher decides when to dispatch (a counter bump).\n\n## X\n"
    calls, types = d.extract_card_claims(card)
    assert calls == set(), f"prose words must not be call-claims, got {calls}"
    assert types == set()


def test_fp_guard_builtin_return_type_not_flagged():
    card = "## Public surface\n\n`promote_all() -> dict`\n\n## X\n"
    _, types = d.extract_card_claims(card)
    assert types == set(), "builtin return types must not be type-claims"


def test_check_card_warns_missing_keeps_present():
    # ## Path points at a REAL module file (exists), but _module_reader returns STUB.
    card = (
        "## Path\n`~/.claude/scripts/lib/strike_dispatcher.py`\n\n"
        "## Public surface\n\n`record_strike(x)` / `should_dispatch(y)` / `-> CascadeResult`\n\n## X\n"
    )
    ddc._module_reader = lambda p: STUB
    try:
        warns = d.check_card(Path("card.md"), card, {"type": "artifact", "status": "active"})
    finally:
        ddc._module_reader = None
    j = " ".join(warns)
    assert "record_strike" in j, "absent name must WARN"
    assert "should_dispatch" not in j, "present name must NOT WARN"
    assert "CascadeResult" in j, "absent return type must WARN (F5)"


def test_check_card_skips_deprecated():
    card = "## Path\n`~/.claude/scripts/lib/strike_dispatcher.py`\n## Public surface\n`nope(x)`\n"
    out = d.check_card(Path("c.md"), card, {"type": "artifact", "status": "deprecated"})
    assert out == []


def test_check_card_skips_non_artifact():
    card = "## Public surface\n`nope(x)`\n"
    assert d.check_card(Path("c.md"), card, {"type": "concept"}) == []


def test_check_path_refs_backtick_resolution():
    txt = "see `validators/staging_guard.py` (phantom) and `lib/staging_guard.py` (real) here"
    warns = d.check_path_refs(Path("note.md"), txt)
    j = " ".join(warns)
    assert "validators/staging_guard.py" in j, "nonexistent path must WARN"
    assert "lib/staging_guard.py`" not in j, "existing path must NOT WARN"


def test_safety_no_exec_no_network_no_clock():
    src = Path(d.__file__).read_text(encoding="utf-8")
    for bad in ["exec(", "__import__", "importlib", "import_module", "urllib",
                "requests", "import time", "import random", "subprocess", "eval("]:
        assert bad not in src, f"forbidden construct present: {bad}"


def test_graduated_mode_fails_on_drift():
    # C8 part-2 (Track1 debate-1780722434-e5h19n): in graduated (blocking) mode
    # drift => [FAIL]+exit 1; advisory mode stays exit 0 (WARN-only). This is
    # the gate that makes 'graduation' actually change blocking semantics.
    import contextlib
    import io
    saved_grad, saved_scan = d._is_graduated, d.scan
    drift = {"artifact_cards": 1, "notes": 1,
             "name_warns": ["[WARN] x: drift"], "path_warns": []}
    clean = {"artifact_cards": 1, "notes": 1, "name_warns": [], "path_warns": []}

    def _rc():  # capture stdout so the intentional [FAIL] marker never leaks
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return d.main()
    try:
        d._is_graduated = lambda: True
        d.scan = lambda: drift
        assert _rc() == 1, "graduated + drift must FAIL (exit 1)"
        d.scan = lambda: clean
        assert _rc() == 0, "graduated + 0 drift must PASS (exit 0)"
        d._is_graduated = lambda: False
        d.scan = lambda: drift
        assert _rc() == 0, "advisory + drift must stay exit 0 (WARN-only)"
    finally:
        d._is_graduated, d.scan = saved_grad, saved_scan


def test_scan_actually_covers_real_vault_not_silently_dead():
    # Guards the exact failure that slipped past a weak `main()==0` check:
    # parse_frontmatter takes a PATH (not text) and returns (fm,body)|None, so a
    # wrong call left the validator scanning 0 notes. Build a SYNTHETIC vault and
    # assert scan() covers every note — portable, no dependency on a populated
    # personal atlas (the live product ships an empty vault).
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td)
        for i in range(3):
            (vault / f"note{i}.md").write_text(
                f"---\ntype: concept\n---\n## Summary\nnote {i}\n", encoding="utf-8")
        for i in range(2):
            (vault / f"card{i}.md").write_text(
                f"---\ntype: artifact\n---\n## Public surface\n- `foo{i}()`\n## Path\nlib/x.py\n",
                encoding="utf-8")
        orig = d.ATLAS_DIR
        d.ATLAS_DIR = vault
        try:
            r = d.scan()
        finally:
            d.ATLAS_DIR = orig
        assert r["notes"] == 5, f"scanner covered {r['notes']}/5 notes — silently dead?"
        assert r["artifact_cards"] == 2, f"only {r['artifact_cards']}/2 artifact cards scanned"
    assert d.main() == 0  # runs on the live (possibly empty) vault without crashing


def main() -> int:
    tests = [
        test_collect_symbols_reexport_and_all_aware,
        test_extract_fenced_block_not_silently_dead,
        test_extract_prose_backtick_calls,
        test_extract_method_style_and_return_type,
        test_fp_guard_prose_has_no_claims,
        test_fp_guard_builtin_return_type_not_flagged,
        test_check_card_warns_missing_keeps_present,
        test_check_card_skips_deprecated,
        test_check_card_skips_non_artifact,
        test_check_path_refs_backtick_resolution,
        test_safety_no_exec_no_network_no_clock,
        test_graduated_mode_fails_on_drift,
        test_scan_actually_covers_real_vault_not_silently_dead,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"[FAIL] {failed}/{len(tests)} failed")
        return 1
    print(f"[OK] {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

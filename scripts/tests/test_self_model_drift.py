#!/usr/bin/env python3
"""Tests for validators/self_model_drift.py (advisory; harness-advancement #4).

Hermetic: F-MUTMIRROR drift is exercised via the shared lib.doc_drift_common
._module_reader injection hook (CLAUDE.md lives at _HOME.parent, OUTSIDE the
junctioned isolated home, so the real file is unreadable under run_units
isolation — never read it in a test). The silently-dead guard reads real
commands/skills bodies (those dirs ARE junctioned under isolation).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import self_model_drift as s  # noqa: E402
from lib import doc_drift_common as ddc  # noqa: E402 (inject via this shared hook)


# ── pure extractors (env-independent) ──
def test_parse_tools_field():
    assert s._parse_tools_field("Read, Grep, Bash") == {"Read", "Grep", "Bash"}
    assert s._parse_tools_field(["Read", "Grep"]) == {"Read", "Grep"}
    assert s._parse_tools_field("") == set()


def test_extra_tools_creep_only():
    # privilege creep detected
    assert s._extra_tools({"Read", "Grep", "Bash"}, frozenset({"Read", "Grep"})) == {"Bash"}
    # one-way: a MISSING allowed tool is NOT warned (only reduces privilege)
    assert s._extra_tools({"Read"}, frozenset({"Read", "Grep", "WebSearch"})) == set()


def test_extract_script_refs_triple_guard():
    refs = s._extract_script_refs(
        "use `lib/foo.py` and `python -m cli.bar` and `tests/test_x.py` "
        "and bare lib mention and `enable-skill` token and `handlers/h.py`"
    )
    assert ("py", "lib/foo.py") in refs
    assert ("py", "handlers/h.py") in refs
    assert ("mod", "cli.bar") in refs
    assert all(r != ("py", "tests/test_x.py") for r in refs), "tests/ dropped from prefix"
    assert all("enable-skill" not in r[1] for r in refs), "non-path backtick token ignored"


def test_ref_resolves():
    assert s._ref_resolves("py", "validators/self_model_drift.py")
    assert s._ref_resolves("mod", "validators.self_model_drift")
    assert not s._ref_resolves("py", "lib/__nonexistent_zzz__.py")
    assert not s._ref_resolves("mod", "cli.__nonexistent_zzz__")


def test_canonical_tokens_in_vocab_intersected():
    full = ("| `enable-skill` | `apply-user-preference` | `enable-cron-job` | "
            "`configure-critic-policy` | `promote-to-core` | `graduate-validator` |")
    assert s._canonical_tokens_in(full) == s._CANONICAL_TOKENS
    assert s._canonical_tokens_in("only `enable-skill`") == {"enable-skill"}
    # paraphrased label + stray backtick path → no canonical token pollutes the set
    assert s._canonical_tokens_in("critic policy 변경 and `<project>/atlas/`") == set()


# ── silently-dead guard: the checks must MATCH real content ──
def test_scriptref_not_silently_dead():
    """F-SCRIPTREF must extract >0 refs from REAL command/skill bodies (commands/
    + skills/ are junctioned under run_units isolation), proving the regex is
    wired to real content — the gen-1 doc_code_drift fatal-flaw class."""
    total = 0
    for sub in ("commands", "skills"):
        root = s._HOME / sub
        if not root.is_dir():
            continue
        for md in root.rglob("*.md"):
            t = ddc._read_source(md)
            if t:
                total += len(s._extract_script_refs(t))
    assert total > 0, "F-SCRIPTREF extracted 0 refs from real commands/skills — silently dead?"


# ── drift FIRES (injected fixtures, hermetic) ──
def test_mutmirror_fires_on_missing_token():
    def reader(p: Path):
        name = p.name
        if name == "HARNESS-GUIDE.md":  # mirror missing one token → must WARN
            return "| `enable-skill` | `apply-user-preference` | `enable-cron-job` | `configure-critic-policy` |"
        # canonical + atlas mirror carry all 6
        return ("| `enable-skill` | `apply-user-preference` | `enable-cron-job` | "
                "`configure-critic-policy` | `promote-to-core` | `graduate-validator` |")
    saved = ddc._module_reader
    ddc._module_reader = reader
    try:
        warns = s.check_mut_mirror()
    finally:
        ddc._module_reader = saved
    j = " ".join(warns)
    assert "HARNESS-GUIDE.md" in j and "promote-to-core" in j, f"missing-token drift must WARN: {warns}"
    # ONLY the drifting mirror warns; the canonical + atlas note (both 5/5) stay
    # silent. (The WARN message mentions 'canonical CLAUDE.md table' as the
    # explanation, so assert on WARN COUNT — not a brittle 'CLAUDE.md' substring.)
    assert len(warns) == 1, f"only the drifting mirror should warn, got: {warns}"


def test_mutmirror_silent_when_all_in_sync():
    def reader(p: Path):
        return ("| `enable-skill` | `apply-user-preference` | `enable-cron-job` | "
                "`configure-critic-policy` | `promote-to-core` | `graduate-validator` |")
    saved = ddc._module_reader
    ddc._module_reader = reader
    try:
        assert s.check_mut_mirror() == [], "all-in-sync mirrors must produce zero WARN"
    finally:
        ddc._module_reader = saved


def test_scan_returns_three_keys_no_crash():
    r = s.scan()
    assert set(r) == {"tools_warns", "scriptref_warns", "mutmirror_warns"}
    assert all(isinstance(v, list) for v in r.values())


def test_graduated_mode_fails_on_drift():
    # C8 part-2 (Track1 debate-1780722434-e5h19n): graduated (blocking) mode
    # FAILs on drift (exit 1); advisory mode stays exit 0 (WARN-only).
    import contextlib
    import io
    saved_grad, saved_scan = s._is_graduated, s.scan
    drift = {"tools_warns": ["[WARN] creep"], "scriptref_warns": [], "mutmirror_warns": []}
    clean = {"tools_warns": [], "scriptref_warns": [], "mutmirror_warns": []}

    def _rc():  # capture stdout so the intentional [FAIL] marker never leaks
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            return s.main()
    try:
        s._is_graduated = lambda: True
        s.scan = lambda: drift
        assert _rc() == 1, "graduated + drift must FAIL (exit 1)"
        s.scan = lambda: clean
        assert _rc() == 0, "graduated + 0 drift must PASS (exit 0)"
        s._is_graduated = lambda: False
        s.scan = lambda: drift
        assert _rc() == 0, "advisory + drift must stay exit 0 (WARN-only)"
    finally:
        s._is_graduated, s.scan = saved_grad, saved_scan


# ── hermetic source (no import/exec of scanned modules) ──
def test_validator_source_is_hermetic():
    for mod_path in (
        _SCRIPTS / "validators" / "self_model_drift.py",
        _SCRIPTS / "lib" / "doc_drift_common.py",
    ):
        src = mod_path.read_text(encoding="utf-8")
        for bad in ("exec(", "__import__", "importlib", "import_module", "eval(",
                    "subprocess", "urllib", "requests", "import time", "import random"):
            assert bad not in src, f"{mod_path.name} must not contain {bad!r} (hermetic)"


def main() -> int:
    tests = [
        test_parse_tools_field,
        test_extra_tools_creep_only,
        test_extract_script_refs_triple_guard,
        test_ref_resolves,
        test_canonical_tokens_in_vocab_intersected,
        test_scriptref_not_silently_dead,
        test_mutmirror_fires_on_missing_token,
        test_mutmirror_silent_when_all_in_sync,
        test_scan_returns_three_keys_no_crash,
        test_graduated_mode_fails_on_drift,
        test_validator_source_is_hermetic,
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

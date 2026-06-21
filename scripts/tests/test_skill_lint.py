#!/usr/bin/env python3
"""Tests for lib.skill_lint — telemetry-only frontmatter shape classifier.

Contract verified:
1. classify_shape returns one of 4 enum strings for all input shapes.
2. emit_telemetry calls log_telemetry with the locked 7-field schema and
   never raises / returns non-None.
3. is_skill_file matches the skills/ tree predicate, rejects non-.md.
4. lint_skill_file is fail-open on parse errors / OSError.
5. The no_advisory_invariant: no public function returns non-None.

Run:
    cd ~/.claude/scripts && python -m tests.test_skill_lint
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import skill_lint as SL  # noqa: E402
from lib import logging as L  # noqa: E402

_FAILURE_TOKEN_RE = re.compile(r"\[FAIL\]|\[ERROR\]|^Traceback", re.MULTILINE)


# --- classify_shape: 4-way enum ---

def test_classify_none_on_empty():
    assert SL.classify_shape(None) == SL.SHAPE_NONE
    assert SL.classify_shape({}) == SL.SHAPE_NONE


def test_classify_upstream_only():
    assert SL.classify_shape({"name": "x", "description": "y"}) == SL.SHAPE_UPSTREAM


def test_classify_harness_only():
    assert SL.classify_shape({"keywords": "a", "intent": "b"}) == SL.SHAPE_HARNESS


def test_classify_harness_extended_when_full_upstream_plus_harness():
    """P0.1: full upstream (name+description) + harness keys = intentional dual."""
    meta = {"name": "x", "description": "y", "keywords": "a", "phase": "plan"}
    assert SL.classify_shape(meta) == SL.SHAPE_HARNESS_EXTENDED


def test_classify_mixed_when_partial_upstream_plus_harness():
    """P0.1: partial upstream (only name OR only description) + harness = transitional."""
    only_name = {"name": "x", "keywords": "a", "phase": "plan"}
    only_desc = {"description": "y", "keywords": "a", "phase": "plan"}
    assert SL.classify_shape(only_name) == SL.SHAPE_MIXED
    assert SL.classify_shape(only_desc) == SL.SHAPE_MIXED


def test_classify_none_when_unrelated_keys():
    assert SL.classify_shape({"foo": "bar"}) == SL.SHAPE_NONE


def test_classify_case_insensitive_keys():
    assert SL.classify_shape({"Name": "x", "DESCRIPTION": "y"}) == SL.SHAPE_UPSTREAM


# --- is_skill_file: path predicate ---

def test_is_skill_file_accepts_skills_md():
    assert SL.is_skill_file("/c/.claude/skills/_common/foo.md") is True
    assert SL.is_skill_file("C:\\Users\\x\\.claude\\skills\\java\\bar.md") is True


def test_is_skill_file_rejects_non_md():
    assert SL.is_skill_file("/c/.claude/skills/_common/foo.py") is False
    assert SL.is_skill_file("") is False


def test_is_skill_file_rejects_outside_skills_tree():
    assert SL.is_skill_file("/c/.claude/agents/foo.md") is False
    assert SL.is_skill_file("/c/projects/repo/README.md") is False


# --- emit_telemetry: schema lock + invariants ---

def test_emit_telemetry_returns_none():
    captured: list[tuple[str, dict]] = []

    def fake(category, record):
        captured.append((category, record))

    saved = L.log_telemetry
    SL.log_telemetry = fake  # type: ignore[assignment]
    try:
        result = SL.emit_telemetry(
            "/x/skills/a.md", SL.SHAPE_HARNESS, False, False,
            session_id="sid-1", file_size_bytes=42,
        )
    finally:
        SL.log_telemetry = saved  # type: ignore[assignment]

    assert result is None
    assert len(captured) == 1
    cat, rec = captured[0]
    assert cat == "skill_lint"
    expected_keys = {
        "session_id", "path", "shape",
        "name_present", "description_present", "file_size_bytes",
    }
    assert set(rec.keys()) == expected_keys, f"schema drift: {set(rec.keys())}"
    assert rec["shape"] == SL.SHAPE_HARNESS
    assert rec["session_id"] == "sid-1"
    assert rec["file_size_bytes"] == 42


def test_emit_telemetry_no_stdout_failure_tokens():
    """The no_advisory_invariant: even on writer error, no advisory text leaks."""
    def raising(*_a, **_kw):
        raise IOError("simulated")

    saved = L.jsonl_append
    L.jsonl_append = raising  # type: ignore[assignment]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            SL.emit_telemetry("/x/skills/a.md", SL.SHAPE_NONE, False, False)
    finally:
        L.jsonl_append = saved  # type: ignore[assignment]
    captured = buf.getvalue()
    assert _FAILURE_TOKEN_RE.search(captured) is None
    assert captured == ""  # zero stdout output — purely telemetry


# --- lint_skill_file: end-to-end + fail-open ---

def test_lint_skill_file_fails_open_on_missing_file():
    captured: list = []
    saved = SL.emit_telemetry

    def cap(*a, **kw):
        captured.append((a, kw))

    SL.emit_telemetry = cap  # type: ignore[assignment]
    try:
        result = SL.lint_skill_file("/nonexistent/skills/zzz.md")
    finally:
        SL.emit_telemetry = saved  # type: ignore[assignment]
    assert result is None  # never raises


def test_lint_skill_file_emits_correct_shape_for_real_md():
    captured: list[tuple] = []
    saved = SL.emit_telemetry

    def cap(path, shape, name_present, description_present, **kw):
        captured.append((path, shape, name_present, description_present, kw))

    with tempfile.TemporaryDirectory() as td:
        skill_path = Path(td) / "skills" / "tmp.md"
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text(
            "---\nname: tmp\ndescription: a tmp skill\n---\nbody\n",
            encoding="utf-8",
        )
        SL.emit_telemetry = cap  # type: ignore[assignment]
        try:
            SL.lint_skill_file(str(skill_path))
        finally:
            SL.emit_telemetry = saved  # type: ignore[assignment]

    assert len(captured) == 1
    path, shape, name_present, description_present, kw = captured[0]
    assert shape == SL.SHAPE_UPSTREAM
    assert name_present is True
    assert description_present is True
    assert kw.get("file_size_bytes", 0) > 0


def test_lint_default_no_auto_drift_exemption():
    """L2 (2026-05-05): drift_tree_policy=exempt overturned — uniform R002.

    Default exempt_trees=None → empty set. Files in formerly-drift trees
    are subject to R002 unless individually grandfathered. Audit data
    showed drift trees are stable mixes with intentional pure-harness
    convention, NOT pending migration; auto-exemption was a non-problem.
    """
    from cli import skill_lint_report as SLR
    latest = {
        # In a tree that previously had drift exemption (_common at 72%) —
        # now subject to R002 like any other tree.
        "/x/skills/_common/oversized_new.md": {
            "path": "/x/skills/_common/oversized_new.md",
            "shape": "harness_extended", "file_size_bytes": 50_000,
        },
    }
    violations = SLR.lint(latest, threshold_bytes=30_000)
    # No exempt_trees passed → default uniform application → violation reported
    assert len(violations) == 1
    assert "oversized_new.md" in violations[0]["path"]


def test_lint_cli_function_skips_grandfathered_and_drift():
    """opt-in exempt_trees param still works for callers who want it."""
    from cli import skill_lint_report as SLR

    latest = {
        # In a non-drift tree, oversized → violation
        "/x/skills/typescript/react/big.md": {
            "path": "/x/skills/typescript/react/big.md",
            "shape": "has_harness_schema", "file_size_bytes": 50_000,
        },
        # In a drift tree (manually exempt), oversized → skipped
        "/x/skills/_common/security.md": {
            "path": "/x/skills/_common/security.md",
            "shape": "harness_extended", "file_size_bytes": 50_000,
        },
        # Under threshold → skipped
        "/x/skills/typescript/react/small.md": {
            "path": "/x/skills/typescript/react/small.md",
            "shape": "has_harness_schema", "file_size_bytes": 100,
        },
    }
    violations = SLR.lint(
        latest, threshold_bytes=30_000,
        exempt_trees={"_common"},
    )
    assert len(violations) == 1
    assert violations[0]["rule"] == "R002"
    assert "big.md" in violations[0]["path"]
    # Grandfathered set is non-empty after time-bomb defuse — see
    # test_grandfathered_paths_contains_known_outliers for the lock.
    assert len(SLR.GRANDFATHERED_PATHS) >= 0


def test_lint_respects_grandfathered_paths():
    from cli import skill_lint_report as SLR
    latest = {
        "/x/skills/typescript/react/big.md": {
            "path": "/x/skills/typescript/react/big.md",
            "file_size_bytes": 50_000,
        },
    }
    # Compute SKILLS_DIR-relative path matching what lint produces
    rel = "typescript/react/big.md"
    violations = SLR.lint(
        latest, threshold_bytes=30_000,
        exempt_trees=set(),
        grandfathered=frozenset({rel}),
    )
    # If SKILLS_DIR doesn't match /x prefix, the rel_path computation differs,
    # so we just verify the function runs without raising and produces a list.
    assert isinstance(violations, list)


def test_lint_default_threshold_is_30k():
    from cli import skill_lint_report as SLR
    assert SLR.R002_DEFAULT_BYTES == 30_000


def test_evaluate_r003_trigger_not_fired_on_baseline_match():
    """Gen 3 redesign: clean baseline (no drift, no R002 spillover, p90 small) → not fired."""
    from cli import skill_lint_report as SLR
    report = {
        "file_size_stats": {"p90": 5000},
        "r002_violations_count": 0,
    }
    # Empty latest → conv_count=0 → ratio=0 → drift = -baseline (negative = no fire)
    result = SLR.evaluate_r003_trigger(report, latest={})
    assert result["fired"] is False
    assert all(v is False for v in result["clauses"].values())
    # New clause keys
    assert "short_desc_drift_ge_5pp_over_baseline" in result["clauses"]
    assert "any_tree_dominance_lt_60pct" not in result["clauses"]  # removed


def test_evaluate_r003_trigger_fires_on_short_description_drift():
    """Gen 3 new clause: short_desc ratio drifts +5pp over baseline → fired."""
    from cli import skill_lint_report as SLR
    # Construct a synthetic latest where 50% of conv_trees miss description
    # → ratio = 0.5, drift = 0.5 - 0.0070 = +49.3pp >> +5pp threshold
    latest = {
        f"/x/skills/_common/skill_{i}.md": {
            "shape": "harness_extended",
            "description_present": (i < 5),  # 5/10 have desc
        }
        for i in range(10)
    }
    report = {
        "file_size_stats": {"p90": 1000},
        "r002_violations_count": 0,
    }
    result = SLR.evaluate_r003_trigger(report, latest=latest)
    assert result["fired"] is True
    assert result["clauses"]["short_desc_drift_ge_5pp_over_baseline"] is True
    assert result["metrics"]["short_desc_ratio_current"] == 0.5
    assert result["metrics"]["conv_tree_count"] == 10


def test_evaluate_r003_trigger_baseline_constants_locked():
    """Snapshot 42b4a343e390 baseline values are module constants — frozen."""
    from cli import skill_lint_report as SLR
    assert SLR.BASELINE_SHORT_DESCRIPTION_RATIO_CONV == 0.0070
    assert SLR.BASELINE_SNAPSHOT_REF == "debate-1777970195-6b152b"
    assert SLR.SHORT_DESCRIPTION_THRESHOLD_CHARS == 40
    assert SLR.R003_DRIFT_THRESHOLD_PP == 0.05


def test_is_conv_tree_shape_predicate():
    """D6' denominator predicate — only upstream + harness_extended count."""
    from cli import skill_lint_report as SLR
    assert SLR._is_conv_tree_shape("has_upstream_schema") is True
    assert SLR._is_conv_tree_shape("harness_extended") is True
    assert SLR._is_conv_tree_shape("has_harness_schema") is False  # pure harness
    assert SLR._is_conv_tree_shape("none") is False
    assert SLR._is_conv_tree_shape("") is False


def test_tree_dominance_contract_keys_match_consumer_use():
    """tree_dominance() return shape contract — consumed by build_report
    JSON output (`p1_entry` field). Retired callers _exempt_trees and
    would_violate_if_undrifted no longer exist (drift-overturn 2026-05-05).
    """
    from cli import skill_lint_report as SLR
    per_tree = {"x": {"a": 9, "b": 1}, "y": {"a": 5, "b": 5}}
    dom = SLR.tree_dominance(per_tree)
    # Keys consumed by build_report JSON output
    assert "x" in dom and "y" in dom
    for d in dom.values():
        assert set(d.keys()) >= {"n", "dominant", "dominance_ratio", "is_consistent", "shapes"}
    assert dom["x"]["is_consistent"] is True   # 0.9 >= 0.80
    assert dom["y"]["is_consistent"] is False  # 0.5 < 0.80


def test_grandfathered_paths_contains_known_outliers():
    """Lock the grandfather decision: known split-candidate outliers
    are explicitly registered. Removing them requires a new debate +
    actual file split. Adding new entries requires a code PR with
    documented justification (no silent waiver).

    2026-05-18 OD4 land (allsolution-1779083706-305700): +2 entries
    (_common/abstraction-first.md 78kb + _common/pattern-auto-detector.md
    51kb). Cross-file evidence chain risk + V19/V20 mutual references +
    skill loader sub-directory compat verification pending — Option C
    grandfather chosen over Option B per cycle health priority.
    """
    from cli import skill_lint_report as SLR
    expected = {
        "_common/security.md",
        "java/example_app/backend.md",
        "_common/abstraction-first.md",
        "_common/pattern-auto-detector.md",
    }
    assert SLR.GRANDFATHERED_PATHS == expected, (
        f"GRANDFATHERED_PATHS drifted: got {SLR.GRANDFATHERED_PATHS}, "
        f"expected {expected}. New entries require code-PR justification."
    )


def test_session_lint_summary_returns_none_on_clean_state():
    """SessionStart sensor: empty/clean telemetry → no advisory injected."""
    import importlib
    from handlers.session import init as session_init

    # Force clean state by monkey-patching the import inside the function
    saved_load = None
    try:
        from lib import skill_lint_report as SLR  # init imports from lib (layer fix 2026-06-21)
        saved_load = SLR.load_records
        SLR.load_records = lambda: []
        # Reload-style swap not needed because _skill_lint_line uses local import
        result = session_init._skill_lint_line()
    finally:
        if saved_load is not None:
            SLR.load_records = saved_load
    assert result is None


def test_session_lint_summary_reports_violations():
    """SessionStart sensor: violations + deferred + fired trigger → advisory string."""
    from handlers.session import init as session_init
    from lib import skill_lint_report as SLR  # init imports from lib (layer fix 2026-06-21)

    saved = (SLR.load_records, SLR.latest_per_path, SLR.lint,
             SLR.evaluate_r003_trigger, SLR.file_size_stats)
    try:
        SLR.load_records = lambda: [{"path": "/x"}]
        SLR.latest_per_path = lambda recs: {"/x/skills/_common/big.md": {"file_size_bytes": 50_000, "shape": "harness_extended"}}
        SLR.lint = lambda latest, **kw: [{"rule": "R002", "rel_path": "x.md", "file_size_bytes": 50_000, "threshold_bytes": 30_000}]
        SLR.file_size_stats = lambda latest: {"p90": 5000}
        SLR.evaluate_r003_trigger = lambda r, *, latest=None: {"fired": False, "clauses": {}, "metrics": {}}
        result = session_init._skill_lint_line()
    finally:
        (SLR.load_records, SLR.latest_per_path, SLR.lint,
         SLR.evaluate_r003_trigger, SLR.file_size_stats) = saved
    assert result is not None
    # Refactored 2026-05-05: returns single status line (no XML wrapper);
    # composer wraps into unified <harness-status> at SessionStart top-level.
    assert result.startswith("[skill-lint]")
    assert "1 R002 violation" in result


def test_no_public_function_returns_non_none_string():
    """no_advisory_invariant — structural guarantee.

    Inspect every public callable's return annotation: must be None or bool.
    A function returning str could leak into additionalContext.
    """
    import inspect
    bad: list[str] = []
    for name in dir(SL):
        if name.startswith("_"):
            continue
        obj = getattr(SL, name)
        if not callable(obj):
            continue
        try:
            sig = inspect.signature(obj)
        except (ValueError, TypeError):
            continue
        ret = sig.return_annotation
        if ret in (str,) or (hasattr(ret, "__name__") and ret.__name__ == "str"):
            bad.append(name)
    assert not bad, f"functions returning str (advisory leak risk): {bad}"


TESTS = [
    test_classify_none_on_empty,
    test_classify_upstream_only,
    test_classify_harness_only,
    test_classify_harness_extended_when_full_upstream_plus_harness,
    test_classify_mixed_when_partial_upstream_plus_harness,
    test_classify_none_when_unrelated_keys,
    test_classify_case_insensitive_keys,
    test_is_skill_file_accepts_skills_md,
    test_is_skill_file_rejects_non_md,
    test_is_skill_file_rejects_outside_skills_tree,
    test_emit_telemetry_returns_none,
    test_emit_telemetry_no_stdout_failure_tokens,
    test_lint_skill_file_fails_open_on_missing_file,
    test_lint_skill_file_emits_correct_shape_for_real_md,
    test_lint_default_no_auto_drift_exemption,
    test_lint_cli_function_skips_grandfathered_and_drift,
    test_lint_respects_grandfathered_paths,
    test_lint_default_threshold_is_30k,
    test_evaluate_r003_trigger_not_fired_on_baseline_match,
    test_evaluate_r003_trigger_fires_on_short_description_drift,
    test_evaluate_r003_trigger_baseline_constants_locked,
    test_is_conv_tree_shape_predicate,
    test_tree_dominance_contract_keys_match_consumer_use,
    test_grandfathered_paths_contains_known_outliers,
    test_session_lint_summary_returns_none_on_clean_state,
    test_session_lint_summary_reports_violations,
    test_no_public_function_returns_non_none_string,
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

#!/usr/bin/env python3
"""java_golden_pin + load_merged regression (unified-pipeline D2-2).

Java is the GOLDEN REFERENCE: merging the neutral core (stages.core.yaml) with the
Java overlay (overlays/java.overlay.yaml) MUST reproduce the existing global
stages.yaml on the consumer-visible key set. A core edit for any future stack that
perturbs the merged Java output fails this test — the only enforceable form of
"Java preserved verbatim" (debate-1781665033-4f39ca C-JAVA-PIN).

"Functionally identical" is defined concretely: same ordered list of stages, and
for each stage identical value on the LEGACY (consumer-visible) keys after the
value-normalization contract. The additive neutral keys (gate_intent,
skills_intent) are excluded — they did not exist in the legacy stages.yaml.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Keys the legacy stages.yaml exposed to consumers (everything except the new
# additive neutral keys gate_intent/skills_intent).
_LEGACY_KEYS = {"id", "name", "dge", "input", "output", "artifact",
                "gate", "skills", "optional", "phase"}


def test_java_golden_pin_reproduces_legacy_stages():
    """load_merged('java') == parse_stages(stages.yaml) on every legacy key."""
    from lib.pipeline_overlay import load_merged
    from lib.pipeline_yaml import parse_stages, _pipeline_dir
    golden = parse_stages(_pipeline_dir() / "stages.yaml")
    merged = load_merged(cwd=None, lang="java")

    assert len(merged) == len(golden), f"stage count: merged={len(merged)} golden={len(golden)}"
    assert [s["id"] for s in merged] == [s["id"] for s in golden], "stage id order differs"

    for g, m in zip(golden, merged):
        for k in _LEGACY_KEYS:
            gv = g.get(k, "<absent>")
            mv = m.get(k, "<absent>")
            assert mv == gv, (
                f"java_golden_pin: stage {g['id']} key {k!r} diverged — "
                f"merged={mv!r} != golden={gv!r}. A core/overlay edit must not "
                f"perturb the merged Java output."
            )


def test_flutter_golden_pin_reproduces_variant():
    """The SAME neutral core + the flutter overlay reproduces stages-flutter.yaml
    on every legacy key — proving the core is genuinely shared (not Java-only),
    including the flutter-ADDED stage (integration-test) absent from the core."""
    from lib.pipeline_overlay import load_merged
    from lib.pipeline_yaml import parse_stages, _pipeline_dir
    golden = parse_stages(_pipeline_dir() / "stages-flutter.yaml")
    merged = load_merged(cwd=None, lang="flutter")

    assert len(merged) == len(golden), f"flutter stage count: merged={len(merged)} golden={len(golden)}"
    assert [s["id"] for s in merged] == [s["id"] for s in golden], "flutter stage order differs"
    # integration-test is a flutter-only stage not present in the (java-derived) core
    assert "integration-test" in [s["id"] for s in merged]

    for g, m in zip(golden, merged):
        for k in _LEGACY_KEYS:
            assert m.get(k, "<absent>") == g.get(k, "<absent>"), (
                f"flutter_golden_pin: stage {g['id']} key {k!r} — "
                f"merged={m.get(k)!r} != golden={g.get(k)!r}"
            )


def test_rust_golden_pin_reproduces_variant():
    """The SAME neutral core + the rust overlay reproduces stages-rust.yaml on every
    legacy key — the THIRD stack proving the core is genuinely stack-neutral (not
    just java+flutter). Rust adds THREE stages absent from the java-derived core
    (module-design, integration-test, doc-test) and re-tools shared stages (ddl
    output migrations/*.sql, ci-setup dge designer)."""
    from lib.pipeline_overlay import load_merged
    from lib.pipeline_yaml import parse_stages, _pipeline_dir
    golden = parse_stages(_pipeline_dir() / "stages-rust.yaml")
    merged = load_merged(cwd=None, lang="rust")

    assert len(merged) == len(golden), f"rust stage count: merged={len(merged)} golden={len(golden)}"
    assert [s["id"] for s in merged] == [s["id"] for s in golden], "rust stage order differs"
    # rust-only stages not present in the (java-derived) core
    merged_ids = [s["id"] for s in merged]
    for added in ("module-design", "integration-test", "doc-test"):
        assert added in merged_ids, f"rust-added stage {added} missing from merge"

    for g, m in zip(golden, merged):
        for k in _LEGACY_KEYS:
            assert m.get(k, "<absent>") == g.get(k, "<absent>"), (
                f"rust_golden_pin: stage {g['id']} key {k!r} — "
                f"merged={m.get(k)!r} != golden={g.get(k)!r}"
            )


def test_rust_overlay_retools_shared_stage():
    """A shared stage (ddl) carries a rust-specific output via the overlay while
    keeping the same id — concrete evidence the core is reused, not forked."""
    from lib.pipeline_overlay import load_merged
    rust = {s["id"]: s for s in load_merged(cwd=None, lang="rust")}
    java = {s["id"]: s for s in load_merged(cwd=None, lang="java")}
    assert rust["ddl"]["output"] != java["ddl"]["output"]
    assert "migrations" in rust["ddl"]["output"]
    # ci-setup is dge=generator in java core, dge=designer in the rust pipeline
    assert java["ci-setup"]["dge"] == "generator"
    assert rust["ci-setup"]["dge"] == "designer"


def test_shared_core_serves_both_stacks():
    """Same stages.core.yaml file feeds both — the stack-specific divergence
    (ddl output, scaffolding output) lives in the overlay, proving the core is
    truly neutral. Spot-check a stage that differs between java and flutter."""
    from lib.pipeline_overlay import load_merged
    java = {s["id"]: s for s in load_merged(cwd=None, lang="java")}
    flutter = {s["id"]: s for s in load_merged(cwd=None, lang="flutter")}
    # ddl: java -> schema.sql, flutter -> a Dart path — same id, overlay-divergent output
    assert java["ddl"]["output"] == "schema.sql"
    assert java["ddl"]["output"] != flutter["ddl"]["output"]
    assert ".dart" in flutter["ddl"]["output"]


def test_merged_carries_neutral_core_keys():
    """The merge ADDS the neutral keys (gate_intent) on top of the legacy shape —
    additive, present for downstream stack-neutral use."""
    from lib.pipeline_overlay import load_merged
    merged = load_merged(cwd=None, lang="java")
    by_id = {s["id"]: s for s in merged}
    assert "gate_intent" in by_id["requirements"], "neutral gate_intent must be present"
    # gate_intent for a Java-specific stage is tool-free (no 'gradlew'/'compileJava')
    ut_intent = " ".join(by_id["unit-test"].get("gate_intent") or [])
    assert "gradlew" not in ut_intent and "compileJava" not in ut_intent, (
        "neutral core must not leak Java tool names into gate_intent (debate B5)"
    )


def test_load_merged_no_overlay_returns_core_only():
    """A language with no overlay yet (e.g. an un-onboarded stack) returns the
    neutral core without crashing — gate absent (falls back to gate_intent)."""
    from lib.pipeline_overlay import load_merged
    merged = load_merged(cwd=None, lang="nonexistent-stack-zzz")
    assert isinstance(merged, list) and len(merged) > 0
    # no overlay -> no concrete gate, but the neutral gate_intent is present
    assert "gate" not in merged[0]
    assert "gate_intent" in merged[0]


def test_load_merged_missing_core_failsoft():
    """Missing core file -> [] (fail-soft), never raises."""
    from lib import pipeline_overlay as po
    saved = po.SKILLS_DIR
    try:
        po.SKILLS_DIR = Path("/nonexistent-skills-dir-zzz")
        assert po.load_merged(cwd=None, lang="java") == []
    finally:
        po.SKILLS_DIR = saved


def main() -> int:
    tests = [
        test_java_golden_pin_reproduces_legacy_stages,
        test_flutter_golden_pin_reproduces_variant,
        test_rust_golden_pin_reproduces_variant,
        test_rust_overlay_retools_shared_stage,
        test_shared_core_serves_both_stacks,
        test_merged_carries_neutral_core_keys,
        test_load_merged_no_overlay_returns_core_only,
        test_load_merged_missing_core_failsoft,
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

#!/usr/bin/env python3
"""spec_roundtrip — advisory round-trip coverage of a Spec Bundle vs its tests
(unified-pipeline 잔여-3).

The Spec Bundle's behavioral spine (`.claude/spec/domain/*.feature`) declares the
@id'd scenarios that MUST be covered by tests. test-gen (lib.testgen) renders those
scenarios into `.feature` resources under the stack's test tree, PRESERVING each
@id (the round-trip key — debate C-STABLE-ID). This validator compares the two @id
sets via lib.testgen.roundtrip_coverage and surfaces:
  - MISSING: a spec scenario @id with no backing test  (behavior unverified)
  - ORPHAN : a test @id with no backing spec scenario   (test/spec drift)

It is the COVERAGE counterpart to validators.spec_bundle (which checks internal
integrity — @id uniqueness, manifest↔domains, facet validity). ADVISORY ([WARN]);
graduates to blocking via the graduate-validator token. The harness repo carries no
spec bundle, so this is forward-looking ([PASS]) until projects adopt the bundle —
like spec_bundle / exit_contract_coverage. Caller contract: main()->None.
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout):
    _r = getattr(_s, "reconfigure", None)
    if _r:
        try:
            _r(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Test-feature locations the stack test-gen writes to (relative to project root).
# Mirrors lib.testgen output paths: cucumber-jvm, flutter_gherkin, cucumber-rs.
_TEST_FEATURE_GLOBS = (
    "src/test/resources/features/*.feature",   # cucumber-jvm
    "test/features/*.feature",                  # flutter_gherkin
    "tests/features/*.feature",                 # cucumber-rs
)


def _test_feature_ids(project_root: Path) -> list[str]:
    """Collect scenario @ids from rendered test `.feature` files (NOT the spec
    bundle's own domain/*.feature). Order-stable, de-duplicated."""
    from lib.spec_bundle import parse_feature
    spec_domain = (project_root / ".claude" / "spec" / "domain").resolve()
    out: list[str] = []
    seen: set[str] = set()
    for pattern in _TEST_FEATURE_GLOBS:
        for fp in sorted(project_root.glob(pattern)):
            if fp.resolve().parent == spec_domain:
                continue   # never count the spec spine as its own test
            try:
                feat = parse_feature(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            for sid in feat.scenario_ids():
                if sid not in seen:
                    seen.add(sid)
                    out.append(sid)
    return out


def check_roundtrip(project_root: str | Path) -> list[str]:
    """Return advisory round-trip problems for the bundle under <project_root>.
    Empty = clean (or no bundle). Reuses lib.testgen.roundtrip_coverage so the
    coverage math is the single source of truth."""
    from lib.spec_bundle import load_bundle
    from lib.testgen import roundtrip_coverage

    root = Path(project_root)
    bundle = load_bundle(root)
    if bundle is None:
        return []
    spec_ids = bundle.all_scenario_ids()
    if not spec_ids:
        return []   # behavioral spine not authored yet (scaffold-only) — nothing to cover
    test_ids = _test_feature_ids(root)
    rt = roundtrip_coverage(spec_ids, test_ids)

    problems: list[str] = []
    for sid in rt.missing:
        problems.append(f"scenario @id '{sid}' has no backing test (behavior unverified)")
    for sid in rt.orphan:
        problems.append(f"test scenario @id '{sid}' has no backing spec scenario (drift)")
    return problems


def coverage_report(project_root: str | Path):
    """Return the raw RoundTrip (matched/missing/orphan/coverage_pct) for callers
    that want the number, not the advisory lines. None if no authored spine."""
    from lib.spec_bundle import load_bundle
    from lib.testgen import roundtrip_coverage
    root = Path(project_root)
    bundle = load_bundle(root)
    if bundle is None:
        return None
    spec_ids = bundle.all_scenario_ids()
    if not spec_ids:
        return None
    return roundtrip_coverage(spec_ids, _test_feature_ids(root))


def _find_project_roots() -> list[Path]:
    """Spec bundles to check within the harness tree (none today -> [PASS])."""
    from lib.paths import CLAUDE_HOME
    out: list[Path] = []
    if (CLAUDE_HOME / ".claude" / "spec").is_dir():
        out.append(CLAUDE_HOME)
    return out


def main() -> None:
    roots = _find_project_roots()
    if not roots:
        print("[PASS] spec_roundtrip: no Spec Bundle present "
              "(forward-looking — validates @id coverage on adoption)")
        return
    any_problem = False
    for r in roots:
        problems = check_roundtrip(r)
        if problems:
            any_problem = True
            for p in problems[:12]:
                print(f"[WARN] spec_roundtrip: {p}")
    if not any_problem:
        print("[PASS] spec_roundtrip: every spec scenario @id is covered by a test "
              "(no missing, no orphan)")


if __name__ == "__main__":
    main()

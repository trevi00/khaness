#!/usr/bin/env python3
"""spec_bundle — advisory integrity check for a Spec Bundle (unified-pipeline D1-2).

When a project carries a Spec Bundle (`<root>/.claude/spec/`), this validates its
internal consistency: every Gherkin Scenario has an explicit @id, those ids are
unique (the round-trip contract — debate C-STABLE-ID), the manifest's `domains`
match the `domain/*.feature` files, and each `facets/*.schema` is a well-formed
typed facet with unique element @ids. ADVISORY ([WARN]); graduates to blocking via
the graduate-validator token. The harness repo itself has no spec/ bundle, so this
is forward-looking ([PASS]) until projects adopt the bundle — like
exit_contract_coverage / skill_structure_depth. Caller contract: main()->None.
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


def check_bundle_dir(spec_dir: Path) -> list[str]:
    """Return a list of integrity problems for the bundle under `spec_dir`
    (the `.claude/spec/` directory). Empty = clean. Pure-ish (reads files)."""
    from lib.spec_bundle import load_bundle
    from lib.spec_facets import load_facet, validate_facet

    problems: list[str] = []
    project_root = spec_dir.parent.parent  # <root>/.claude/spec -> <root>
    bundle = load_bundle(project_root)
    if bundle is None:
        return problems

    # 1. manifest domains vs domain/*.feature files
    feature_domains = set(bundle.features.keys())
    declared = set(bundle.domains)
    if declared:
        missing = declared - feature_domains
        extra = feature_domains - declared
        for d in sorted(missing):
            problems.append(f"manifest domain '{d}' has no domain/{d}.feature")
        for d in sorted(extra):
            problems.append(f"domain/{d}.feature not declared in manifest.domains")

    # 2. scenario @id present + unique across all features (round-trip key)
    seen: dict[str, str] = {}
    for dname, feat in bundle.features.items():
        for sc in feat.scenarios:
            if sc.id is None:
                problems.append(f"{dname}.feature: scenario {sc.name!r} has no @id (round-trip key)")
                continue
            if sc.id in seen:
                problems.append(f"duplicate scenario @id '{sc.id}' in {dname}.feature "
                                f"and {seen[sc.id]}.feature")
            seen[sc.id] = dname

    # 3. facets well-formed
    facets_dir = spec_dir / "facets"
    if facets_dir.is_dir():
        for fp in sorted(facets_dir.glob("*.schema")):
            facet = load_facet(fp)
            if facet is None:
                problems.append(f"facets/{fp.name}: not a parseable typed facet")
                continue
            for p in validate_facet(facet):
                problems.append(f"facets/{fp.name}: {p}")
    return problems


def _find_spec_dirs() -> list[Path]:
    """Spec bundles to check within the harness tree (none today -> [PASS])."""
    from lib.paths import CLAUDE_HOME
    out: list[Path] = []
    home_spec = CLAUDE_HOME / "spec"
    if home_spec.is_dir():
        out.append(home_spec)
    return out


def main() -> None:
    spec_dirs = _find_spec_dirs()
    if not spec_dirs:
        print("[PASS] spec_bundle: no Spec Bundle present (forward-looking — validates on adoption)")
        return
    any_problem = False
    for sd in spec_dirs:
        problems = check_bundle_dir(sd)
        if problems:
            any_problem = True
            for p in problems[:12]:
                print(f"[WARN] spec_bundle: {p}")
    if not any_problem:
        print("[PASS] spec_bundle: all Spec Bundles internally consistent "
              "(@id unique, manifest↔domains, facets valid)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""spec_bundle_emit — deterministic Spec Bundle scaffold from a project (D-INT).

The reverse-prd command (commands/harness-reverse-prd.md) invokes this to emit the
DETERMINISTIC half of a Spec Bundle from existing code, then the LLM authors the
BEHAVIORAL spine (`domain/<d>.feature` scenarios) on top — the spec-bundle format
replaces the old 2-track PRD output, so forward test-gen (lib.testgen) and the
spec_bundle validator can consume the reverse output directly.

What this produces (read-only on <root>; writes only under <out>):
  <out>/.claude/spec/
    manifest.yaml                 domains (detected from *Controller.java), personas
                                  placeholder, source_mode=reverse
    facets/logical.schema         typed logical facet (DDL -> tables, deterministic)
    facets/er.schema              typed er facet (entities + relationships)
    facets/class.schema           typed class facet (Java classes -> FQN + layer)
    facets/api.schema             typed api facet (Spring controllers -> endpoints)
    domain/<d>.feature            Gherkin SCAFFOLD per domain (Feature header + a TODO
                                  scenario) for the LLM to fill with @id'd behavior

Then validates with validators.spec_bundle. NEVER writes into <root>.

    python -m cli.spec_bundle_emit --root <project> --out <output_dir>
    python -m cli.spec_bundle_emit --root <project> --out <out> --json
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.spec_facets import (  # noqa: E402
    api_facet_from_project, class_facet_from_project, er_facet_from_project,
    logical_facet_from_project, validate_facet, write_facet,
)
from validators.spec_bundle import check_bundle_dir  # noqa: E402

_CONTROLLER_RE = re.compile(r"(\w+)Controller\.java$")


def detect_domains(root: Path) -> list[str]:
    """Detect domain names from *Controller.java files — the package directory that
    contains a controller is a behavioral domain (e.g. kr/example_service/identity ->
    'identity'). Falls back to the controller's class prefix. Deterministic."""
    domains: dict[str, None] = {}
    src = root / "src" / "main" / "java"
    if not src.is_dir():
        return []
    for cp in src.rglob("*Controller.java"):
        parent = cp.parent.name
        # prefer the package dir name; skip generic buckets
        if parent and parent not in ("controller", "controllers", "web", "api", "rest"):
            domains[parent] = None
        else:
            m = _CONTROLLER_RE.search(cp.name)
            if m:
                domains[m.group(1).lower()] = None
    return sorted(domains)


def _feature_scaffold(domain: str) -> str:
    return (
        f"@{domain}\n"
        f"Feature: {domain}\n"
        f"  # SCAFFOLD (reverse-prd): author @id'd Given-When-Then scenarios from the\n"
        f"  # real behavior of the '{domain}' domain. Mark unverifiable items with\n"
        f"  # '> ⚠️ 역설계 추정'. Each Scenario needs an explicit @id:<slug> (round-trip key).\n"
        f"\n"
        f"  @id:{domain}-TODO\n"
        f"  Scenario: TODO — replace with a real behavior\n"
        f"    Given a precondition\n"
        f"    When an action occurs\n"
        f"    Then an observable result holds\n"
    )


def emit(root: Path, out: Path, *, source_mode: str = "reverse",
        domains: list[str] | None = None) -> dict:
    """Emit a Spec Bundle scaffold. Serves BOTH directions:
      - reverse: domains detected from *Controller.java, facets from existing DDL.
      - forward: domains given explicitly (greenfield), facets emitted only once the
        pipeline's DB stage has produced DDL (idempotent — re-run after DDL adds them).
    Facets are written only when present (no DDL yet -> behavioral-only bundle).
    Authored .feature scenarios are never clobbered on re-run."""
    spec = out / ".claude" / "spec"
    (spec / "facets").mkdir(parents=True, exist_ok=True)
    (spec / "domain").mkdir(parents=True, exist_ok=True)

    if domains is None:
        domains = detect_domains(root)

    # facets (deterministic) — only the ones with signal are written. logical/er
    # need DDL (forward greenfield has none yet); class/api need Java source (a
    # greenfield with no controllers yet emits neither). All four are idempotently
    # (re-)written on re-run as the project gains DDL / code.
    logical = logical_facet_from_project(root)
    er = er_facet_from_project(root)
    klass = class_facet_from_project(root)
    api = api_facet_from_project(root)
    facets_written: list[str] = []
    for facet, fname in ((logical, "logical"), (er, "er"), (klass, "class"), (api, "api")):
        if facet.elements:
            write_facet(facet, spec / "facets" / f"{fname}.schema")
            facets_written.append(fname)

    # domain feature scaffolds (behavioral — authored by the LLM stage)
    for d in domains:
        fp = spec / "domain" / f"{d}.feature"
        if not fp.exists():   # never clobber author-filled scenarios on re-run
            fp.write_text(_feature_scaffold(d), encoding="utf-8")

    author = "forward 요구사항 stage" if source_mode == "forward" else "reverse-prd"
    manifest = {
        "schema_version": "1",
        "source_mode": source_mode,
        "domains": domains,
        "personas": [{"id": "TODO", "name": f"페르소나 ({author}가 식별)"}],
    }
    (spec / "manifest.yaml").write_text(
        f"# Spec Bundle manifest (source_mode={source_mode}). Behavioral .feature\n"
        f"# scenarios are authored by {author}; facets are deterministic from DDL.\n"
        + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    problems = check_bundle_dir(spec)
    return {
        "spec_dir": str(spec),
        "source_mode": source_mode,
        "domains": domains,
        "facets_written": facets_written,
        "logical_tables": len(logical.elements),
        "logical_valid": validate_facet(logical) == [],
        "er_entities": len(er.elements),
        "er_valid": validate_facet(er) == [],
        "class_count": len(klass.elements),
        "api_endpoints": len(api.elements),
        "validator_problems": problems,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cli.spec_bundle_emit",
                                description="Emit a deterministic Spec Bundle scaffold from a project.")
    p.add_argument("--root", required=True,
                   help="project root: reverse=existing code (read-only); forward=the project being built")
    p.add_argument("--out", required=True, help="output dir (Spec Bundle written under <out>/.claude/spec/)")
    p.add_argument("--source-mode", default="reverse", choices=["reverse", "forward"])
    p.add_argument("--domains", default="",
                   help="comma-separated explicit domains (forward greenfield); omit to detect from *Controller.java")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"[error] --root not a directory: {root}\n")
        return 2
    domains = [d.strip() for d in args.domains.split(",") if d.strip()] or None
    res = emit(root, Path(args.out), source_mode=args.source_mode, domains=domains)
    if args.json:
        import json
        sys.stdout.write(json.dumps(res, ensure_ascii=False, indent=2) + "\n")
    else:
        print(f"Spec Bundle scaffold -> {res['spec_dir']}")
        print(f"  domains: {res['domains']}")
        print(f"  facets: logical({res['logical_tables']} tables, valid={res['logical_valid']}) "
              f"er({res['er_entities']} entities, valid={res['er_valid']}) "
              f"class({res['class_count']}) api({res['api_endpoints']} endpoints)")
        prob = res["validator_problems"]
        # scaffold @id:<d>-TODO is intentionally present; report only NON-scaffold problems
        real = [p for p in prob if "-TODO" not in p]
        print(f"  validator: {len(real)} structural problems "
              f"(+ {len(prob) - len(real)} expected TODO-scaffold notes)")
        author = "forward 요구사항 stage" if res["source_mode"] == "forward" else "reverse-prd"
        print(f"  NEXT: {author} authors @id'd Given-When-Then scenarios in domain/*.feature")
    return 0


if __name__ == "__main__":
    sys.exit(main())

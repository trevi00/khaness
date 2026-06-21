#!/usr/bin/env python3
"""onboard_stack — deterministic half of new-stack onboarding (research-subsystem
debate-1781688992-250894, D1/D3/D5; sha 9d281b9f).

The research-stack-onboarder AGENT (agents/research-stack-onboarder.md) researches a
language's build tool / test framework / pipeline idioms and emits ONE typed artifact
`state/research/onboard/<lang>.yaml` (overlay-shaped + an `expected` oracle block). It
NEVER writes pipeline files. This CLI is the deterministic consumer:

  scaffold --lang <lang>   reads onboard/<lang>.yaml and writes, to the INERT staging
                           dir skills/_pipeline/candidates/ ONLY:
                             - overlays/<lang>.overlay.yaml   (the validated overlay)
                             - stages-<lang>.yaml             (full stages, merged dump)
                             - <lang>.expected.yaml           (oracle facet, operator_authored:false)
                             - tests/test_<lang>_golden_pin.py (dual-guarantee template)
                           context-loader globs only _pipeline/*.yaml, NOT candidates/,
                           so a scaffolded stack is INERT until promoted.

  verify --lang <lang>     runs the (A) STRUCTURAL guarantee against the candidate:
                           merge(core, candidate_overlay) round-trips parse(candidate
                           stages) on legacy keys. (B) the ORACLE guarantee (named
                           stage-ids + tool tokens vs <lang>.expected.yaml) is only a
                           real independence check once that file is OPERATOR-AUTHORED,
                           so it is reported but is strict-xfail until then.

  promote --lang <lang>    ACTIVATION. NEVER-auto: editing the live pipeline + the
                           _VARIANTS registry is gated by a NEW dedicated 'onboard-stack'
                           mutate token (operator hand-off). Until the CLAUDE.md §Mutation
                           'onboard-stack' row + token exist, --promote refuses the live
                           move and prints the operator steps. When an in-source _VARIANTS
                           edit IS performed (operator path), it is guarded by
                           ast.parse + import-smoke + revert-on-failure so a malformed
                           edit can never break generation for the other stacks.

Java is the golden reference; this never edits live java/flutter/rust.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import shutil
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.pipeline_overlay import _pipeline_dir, core_path, merge_core_overlay  # noqa: E402
from lib.pipeline_yaml import parse_stages  # noqa: E402

# The new mutate token gating live activation. NEVER auto-created (CLAUDE.md:128).
ONBOARD_STACK_TOKEN = "onboard-stack"
_LEGACY_KEYS = ("id", "name", "dge", "input", "output", "artifact", "gate", "skills", "optional")


def onboard_artifact_path(lang: str) -> Path:
    from lib.paths import STATE_DIR
    return STATE_DIR / "research" / "onboard" / f"{lang}.yaml"


def candidates_dir() -> Path:
    return _pipeline_dir() / "candidates"


def candidate_overlay_path(lang: str) -> Path:
    return candidates_dir() / "overlays" / f"{lang}.overlay.yaml"


def candidate_stages_path(lang: str) -> Path:
    return candidates_dir() / f"stages-{lang}.yaml"


def candidate_expected_path(lang: str) -> Path:
    return candidates_dir() / f"{lang}.expected.yaml"


def candidate_goldenpin_path(lang: str) -> Path:
    return candidates_dir() / "tests" / f"test_{lang}_golden_pin.py"


def _load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _load_core_stages() -> list[dict]:
    raw = yaml.safe_load(core_path().read_text(encoding="utf-8"))
    return raw["stages"] if isinstance(raw, dict) else (raw or [])


def validate_onboard(artifact: dict) -> list[str]:
    """Structural validation of the agent's onboard/<lang>.yaml. Returns problems."""
    problems: list[str] = []
    if not isinstance(artifact, dict):
        return ["onboard artifact is not a mapping"]
    if not artifact.get("stack"):
        problems.append("missing 'stack'")
    if not artifact.get("source_finder"):
        problems.append("missing 'source_finder'")
    tg = artifact.get("testgen")
    if not isinstance(tg, dict) or not tg.get("framework") or not tg.get("runner_cmd"):
        problems.append("'testgen' must have framework + runner_cmd")
    if not isinstance(artifact.get("applicable_stages"), list) or not artifact["applicable_stages"]:
        problems.append("'applicable_stages' must be a non-empty list")
    exp = artifact.get("expected")
    if not isinstance(exp, dict) or not isinstance(exp.get("stage_ids"), list):
        problems.append("'expected.stage_ids' (oracle) must be a list")
    return problems


def _overlay_from_artifact(artifact: dict) -> dict:
    """The overlay subset the merge consumes (stack/source_finder/testgen/
    applicable_stages/stages). 'expected' is split out as the oracle facet."""
    return {k: artifact[k] for k in
            ("stack", "source_finder", "testgen", "applicable_stages", "stages")
            if k in artifact}


def _stages_doc_from_merged(merged: list[dict]) -> dict:
    """A full stages-<lang>.yaml doc from the merged stage list (legacy keys only).

    Values are kept VERBATIM from the merged form so parse_stages of the dump
    reproduces the merged shape (the golden_pin (A) check). merge_core_overlay
    renders input/skills as a '[a, b]' FLOW STRING; dumping that as a YAML scalar
    means parse_stages reads it back as the SAME scalar string (no flow-seq
    re-detection), keeping the two sides equal. gate stays a native list (block-seq,
    no consumer) and round-trips as a list. Re-expanding input/skills to native
    lists here would make the dump a block-seq → parse_stages returns native lists →
    a spurious 'string != list' diff vs the merged flow-strings."""
    out = []
    for st in merged:
        d = {k: st[k] for k in
             ("id", "name", "dge", "input", "output", "artifact", "gate", "skills", "optional")
             if k in st}
        out.append(d)
    return {"stages": out}


def scaffold(lang: str) -> dict:
    """Read onboard/<lang>.yaml and write the candidate bundle (INERT). Read-only on
    live pipeline. Returns a summary dict."""
    art_path = onboard_artifact_path(lang)
    if not art_path.is_file():
        raise FileNotFoundError(f"no onboard artifact: {art_path} (run the research-stack-onboarder agent first)")
    artifact = _load_yaml(art_path)
    problems = validate_onboard(artifact)
    if problems:
        raise ValueError(f"invalid onboard artifact: {problems}")

    overlay = _overlay_from_artifact(artifact)
    core = yaml.safe_load(core_path().read_text(encoding="utf-8"))
    merged = merge_core_overlay(core, overlay)

    cd = candidates_dir()
    (cd / "overlays").mkdir(parents=True, exist_ok=True)
    (cd / "tests").mkdir(parents=True, exist_ok=True)

    candidate_overlay_path(lang).write_text(
        f"# {lang}.overlay.yaml — CANDIDATE (inert until promoted). Machine-derived from\n"
        f"# state/research/onboard/{lang}.yaml by cli.onboard_stack.\n"
        + yaml.safe_dump(overlay, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8")
    candidate_stages_path(lang).write_text(
        f"# stages-{lang}.yaml — CANDIDATE (inert). Merged dump for the golden_pin (A) check.\n"
        + yaml.safe_dump(_stages_doc_from_merged(merged), allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8")

    expected = artifact["expected"]
    expected.setdefault("operator_authored", False)
    candidate_expected_path(lang).write_text(
        f"# {lang}.expected.yaml — ORACLE facet (D3-B). The (B) guarantee is a REAL\n"
        f"# independence check ONLY when a human authors this file from the stack spec\n"
        f"# (set operator_authored: true after editing). Until then the golden_pin (B)\n"
        f"# assertion is strict-xfail — an LLM-derived oracle proves nothing.\n"
        + yaml.safe_dump(expected, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    candidate_goldenpin_path(lang).write_text(_goldenpin_template(lang), encoding="utf-8")
    return {
        "lang": lang,
        "candidate_overlay": str(candidate_overlay_path(lang)),
        "candidate_stages": str(candidate_stages_path(lang)),
        "expected_oracle": str(candidate_expected_path(lang)),
        "golden_pin": str(candidate_goldenpin_path(lang)),
        "merged_stage_count": len(merged),
        "operator_authored_oracle": bool(expected.get("operator_authored")),
        "inert": True,
    }


def verify_candidate(lang: str) -> dict:
    """(A) structural guarantee: merge(core, candidate_overlay) reproduces
    parse(candidate stages) on legacy keys (catches merge/dump corruption). Returns
    {structural_ok, diffs, oracle_authored}."""
    overlay = _load_yaml(candidate_overlay_path(lang))
    core = yaml.safe_load(core_path().read_text(encoding="utf-8"))
    merged = merge_core_overlay(core, overlay)
    golden = parse_stages(candidate_stages_path(lang))
    diffs: list[str] = []
    if [s.get("id") for s in merged] != [s.get("id") for s in golden]:
        diffs.append("stage id order differs")
    for m, g in zip(merged, golden):
        for k in _LEGACY_KEYS:
            if m.get(k, "<absent>") != g.get(k, "<absent>"):
                diffs.append(f"stage {g.get('id')} key {k}: {m.get(k)!r} != {g.get(k)!r}")
    exp = _load_yaml(candidate_expected_path(lang))
    return {"structural_ok": not diffs, "diffs": diffs[:10],
            "oracle_authored": bool(exp.get("operator_authored"))}


def _goldenpin_template(lang: str) -> str:
    return f'''#!/usr/bin/env python3
"""test_{lang}_golden_pin — dual-guarantee for the onboarded '{lang}' stack
(D3, research-subsystem debate). (A) STRUCTURAL: merge(core, overlay) round-trips
the stages dump on legacy keys. (B) ORACLE: named stage-ids + tool tokens vs the
operator-authored {lang}.expected.yaml — strict-xfail until a HUMAN authors that
file (operator_authored: true), because an LLM-derived oracle proves only
self-consistency, not correctness.
"""
from __future__ import annotations
import sys
from pathlib import Path
import yaml

# Robust bootstrap — works from the candidate staging dir (skills/_pipeline/
# candidates/tests/) AND from the promoted location (scripts/tests/).
_SCRIPTS = next(p / "scripts" for p in Path(__file__).resolve().parents
                if (p / "scripts" / "lib" / "pipeline_overlay.py").is_file())
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

LANG = "{lang}"


def _candidates():
    from lib.pipeline_overlay import _pipeline_dir
    return _pipeline_dir() / "candidates"


def test_structural_roundtrip():
    """(A) merge(core, candidate overlay) == parse(candidate stages) on legacy keys."""
    from lib.pipeline_overlay import merge_core_overlay, core_path
    from lib.pipeline_yaml import parse_stages
    cd = _candidates()
    overlay = yaml.safe_load((cd / "overlays" / f"{{LANG}}.overlay.yaml").read_text(encoding="utf-8"))
    core = yaml.safe_load(core_path().read_text(encoding="utf-8"))
    merged = merge_core_overlay(core, overlay)
    golden = parse_stages(cd / f"stages-{{LANG}}.yaml")
    assert [s.get("id") for s in merged] == [s.get("id") for s in golden], "stage order"
    for k in ("id", "name", "dge", "output", "gate", "skills", "optional"):
        for m, g in zip(merged, golden):
            assert m.get(k, "<a>") == g.get(k, "<a>"), f"{{LANG}} stage {{g.get('id')}} key {{k}}"


def _oracle_authored() -> bool:
    cd = _candidates()
    exp = yaml.safe_load((cd / f"{{LANG}}.expected.yaml").read_text(encoding="utf-8")) or {{}}
    return bool(exp.get("operator_authored"))


def test_oracle_named_stages_and_tokens():
    """(B) load merged stages contain the operator-authored expected stage-ids +
    tool tokens. strict-xfail until {lang}.expected.yaml is human-authored."""
    if not _oracle_authored():
        import pytest  # type: ignore
        pytest.xfail("{lang}.expected.yaml not operator-authored yet (LLM-derived oracle = no independence)")
    from lib.pipeline_overlay import merge_core_overlay, core_path
    cd = _candidates()
    overlay = yaml.safe_load((cd / "overlays" / f"{{LANG}}.overlay.yaml").read_text(encoding="utf-8"))
    core = yaml.safe_load(core_path().read_text(encoding="utf-8"))
    merged = merge_core_overlay(core, overlay)
    exp = yaml.safe_load((cd / f"{{LANG}}.expected.yaml").read_text(encoding="utf-8"))
    ids = {{s.get("id") for s in merged}}
    for sid in exp.get("stage_ids", []):
        assert sid in ids, f"expected stage-id {{sid}} missing from merged {{LANG}} pipeline"
    blob = yaml.safe_dump(merged, allow_unicode=True)
    for tok in exp.get("tool_tokens", []):
        assert tok in blob, f"expected tool token {{tok!r}} absent from merged {{LANG}} gates"


if __name__ == "__main__":
    test_structural_roundtrip()
    print("[OK] {lang} structural round-trip")
'''


def _guarded_variants_edit(lang: str, spec: dict) -> dict:
    """Append a _VARIANTS row to cli/gen_pipeline_core_overlay.py IN-SOURCE, guarded
    by ast.parse + import-smoke + revert-on-failure so a malformed edit can NEVER
    break generation for java/flutter/rust. Returns {applied, reason}. This is the
    operator path — callers gate it behind the onboard-stack token."""
    target = _SCRIPTS / "cli" / "gen_pipeline_core_overlay.py"
    original = target.read_text(encoding="utf-8")
    row = (f'    {{"stack": "{spec["stack"]}", "variant_file": "stages-{lang}.yaml",\n'
           f'     "source_finder": "{spec["source_finder"]}",\n'
           f'     "testgen": {{"framework": "{spec["testgen"]["framework"]}", '
           f'"runner_cmd": "{spec["testgen"]["runner_cmd"]}"}}}},\n')
    anchor = "_VARIANTS: tuple[dict, ...] = (\n"
    if anchor not in original:
        return {"applied": False, "reason": "anchor not found (generator shape changed)"}
    new_source = original.replace(anchor, anchor + row, 1)
    # guard (a): ast.parse
    try:
        ast.parse(new_source)
    except SyntaxError as e:
        return {"applied": False, "reason": f"ast.parse failed (reverted): {e}"}
    target.write_text(new_source, encoding="utf-8")
    # guard (b): import-smoke
    try:
        mod = importlib.import_module("cli.gen_pipeline_core_overlay")
        importlib.reload(mod)
    except Exception as e:  # guard (c): revert
        target.write_text(original, encoding="utf-8")
        return {"applied": False, "reason": f"import-smoke failed (reverted): {e}"}
    return {"applied": True, "reason": "in-source _VARIANTS row added (ast+smoke passed)"}


def promote(lang: str, *, token: str | None = None, allow_in_source: bool = False) -> dict:
    """ACTIVATION — operator hand-off. The default path is BLOCKED: live activation
    needs the onboard-stack mutate token (NEVER auto-created per CLAUDE.md:128).
    Returns a dict describing what is required; performs NO live move without the token."""
    if token != ONBOARD_STACK_TOKEN:
        return {
            "promoted": False,
            "blocked": True,
            "reason": "activation is NEVER-auto: requires the 'onboard-stack' operator mutate token",
            "operator_steps": [
                f"1. Author candidates/{lang}.expected.yaml by hand and set operator_authored: true",
                f"2. Run: python -m pytest candidates/tests/test_{lang}_golden_pin.py (must pass, oracle un-xfails)",
                "3. Add an 'onboard-stack' row to the CLAUDE.md §Mutation table (operator decision)",
                f"4. Re-run promote with --token onboard-stack to move candidates/ -> live + edit _VARIANTS",
            ],
        }
    # operator path (token present) — still guarded
    v = verify_candidate(lang)
    if not v["structural_ok"]:
        return {"promoted": False, "blocked": True, "reason": f"structural verify failed: {v['diffs']}"}
    if not v["oracle_authored"]:
        return {"promoted": False, "blocked": True,
                "reason": "oracle not operator-authored (set operator_authored: true after hand-authoring)"}
    result = {"promoted": False, "blocked": False, "steps": []}
    if allow_in_source:
        artifact = _load_yaml(onboard_artifact_path(lang))
        edit = _guarded_variants_edit(lang, _overlay_from_artifact(artifact))
        result["variants_edit"] = edit
        if not edit["applied"]:
            return {"promoted": False, "blocked": True, "reason": edit["reason"]}
    # move candidate overlay + stages live
    (_pipeline_dir() / "overlays").mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate_overlay_path(lang), _pipeline_dir() / "overlays" / f"{lang}.overlay.yaml")
    shutil.copy2(candidate_stages_path(lang), _pipeline_dir() / f"stages-{lang}.yaml")
    result["promoted"] = True
    result["steps"].append("candidate overlay + stages moved live")
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cli.onboard_stack", description="Deterministic new-stack onboarding (D1/D3/D5).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scaffold"); sc.add_argument("--lang", required=True)
    ve = sub.add_parser("verify"); ve.add_argument("--lang", required=True)
    pr = sub.add_parser("promote"); pr.add_argument("--lang", required=True)
    pr.add_argument("--token", default=None); pr.add_argument("--allow-in-source", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import json
    if args.cmd == "scaffold":
        res = scaffold(args.lang)
    elif args.cmd == "verify":
        res = verify_candidate(args.lang)
    elif args.cmd == "promote":
        res = promote(args.lang, token=args.token, allow_in_source=args.allow_in_source)
    else:
        return 2
    if args.json:
        sys.stdout.write(json.dumps(res, ensure_ascii=False, indent=2) + "\n")
    else:
        for k, v in res.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

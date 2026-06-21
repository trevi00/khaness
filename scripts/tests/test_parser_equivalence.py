#!/usr/bin/env python3
"""Parser-equivalence regression (unified-pipeline D2).

`lib/pipeline_yaml.parse_stages` was changed from a hand-rolled flat line-parser
to a real `yaml.safe_load` + value-normalization, so the neutral-core/overlay
merge can carry nested structure. This test PINS the replacement: for the keys
the 5 deterministic consumers read, the new parser must produce the SAME
string-shaped value the old flat parser produced — on the real global stages.yaml.

The old flat parser is embedded below as the reference oracle. Per the gen-3
Critic build-note, BLOCK-sequence keys the old parser is KNOWN-WRONG on (it
silently dropped `gate:` block sequences to '') are EXCLUDED from old-vs-new
equality and instead checked against the SOURCE yaml — asserting equivalence to
the old (buggy) value there would falsely fail a correct loader.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# The keys the OLD flat parser recognized (= the consumer-visible key set).
_OLD_KEYS = {"name", "output", "gate", "phase", "optional", "skills", "dge"}
# Keys the old flat parser mishandles (block sequences it drops to '') — compared
# against source, not against the old parser.
_BLOCK_EXCLUDED = {"gate"}


def _old_flat_parse(text: str) -> list[dict]:
    """The ORIGINAL hand-rolled flat line-parser, embedded as the reference oracle."""
    stages: list[dict] = []
    current: dict | None = None
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- id:"):
            if current:
                stages.append(current)
            current = {"id": stripped.split(":", 1)[1].strip()}
        elif current and ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in _OLD_KEYS:
                current[key] = val
    if current:
        stages.append(current)
    return stages


def _real_stages_path() -> Path:
    from lib.pipeline_yaml import _pipeline_dir
    return _pipeline_dir() / "stages.yaml"


def test_new_parser_matches_old_on_consumer_keys():
    """New yaml-based parse_stages reproduces the old flat parser's string shape
    for every consumer-read key (excluding block-seq gate) on the real stages.yaml."""
    from lib.pipeline_yaml import parse_stages
    path = _real_stages_path()
    text = path.read_text(encoding="utf-8")
    old = _old_flat_parse(text)
    new = parse_stages(path)

    assert len(new) == len(old), f"stage count differs: new={len(new)} old={len(old)}"
    # same ordered stage ids
    assert [s["id"] for s in new] == [s["id"] for s in old], "stage id order differs"

    for o, n in zip(old, new):
        for key in _OLD_KEYS:
            if key in _BLOCK_EXCLUDED:
                continue
            ov = o.get(key, "<absent>")
            nv = n.get(key, "<absent>")
            assert nv == ov, (
                f"stage {o['id']} key {key!r}: new={nv!r} != old={ov!r} "
                f"(value-normalization must reproduce the flat-parser string shape)"
            )


def test_gate_excluded_key_is_corrected_to_source_list():
    """gate: the old parser dropped block sequences to '' (a bug). The new parser
    must produce the REAL list from source — so it is checked against source,
    NOT against the old parser (which would falsely fail a correct loader)."""
    import yaml
    from lib.pipeline_yaml import parse_stages
    path = _real_stages_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    src_stages = raw["stages"] if isinstance(raw, dict) else raw
    new = parse_stages(path)
    for src, n in zip(src_stages, new):
        if "gate" not in src:
            continue
        src_gate = src["gate"]
        if isinstance(src_gate, list):
            # new gate is the native list straight from source (block sequence)
            assert n.get("gate") == src_gate, (
                f"stage {src.get('id')}: gate should be the source list, got {n.get('gate')!r}"
            )


def test_consumer_critical_shapes():
    """Spot-pin the exact shapes the 3 named string-shape consumers depend on:
    optional=='true', skills as '[a, b]' string (parsed by _skills_to_files),
    output as scalar string."""
    from lib.pipeline_yaml import parse_stages
    new = parse_stages(_real_stages_path())
    by_id = {s["id"]: s for s in new}
    # optional: bool -> 'true' string (monitoring is optional: true)
    assert by_id["monitoring"].get("optional") == "true"
    # skills: flow list -> '[doc-writer]' string the _skills_to_files consumer parses
    assert by_id["requirements"].get("skills") == "[doc-writer]"
    # output: scalar string
    assert by_id["requirements"].get("output") == "requirements.md"
    # round-trip through the actual consumer (_parse_skill_list parses '[a, b]')
    from lib.pipeline_stage_picker import _parse_skill_list
    assert _parse_skill_list(by_id["requirements"]["skills"]) == ["doc-writer.md"]


def main() -> int:
    tests = [
        test_new_parser_matches_old_on_consumer_keys,
        test_gate_excluded_key_is_corrected_to_source_list,
        test_consumer_critical_shapes,
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

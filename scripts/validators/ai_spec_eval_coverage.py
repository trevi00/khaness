#!/usr/bin/env python3
"""ai_spec_eval_coverage — ADVISORY validator: AI-SPEC.md eval-coverage manifest
referential integrity (kha AI-building track absorption, P1).

Design: /harness-debate debate-1780835868-980eb5 converged gen-2 (verdict=approved,
byte-identical ontology snapshot sha1 98c3bc8760e4b66686745dd7201190e6c5d03464).
accepted_decisions D2/D3 + coverage_validator_contract field.

Role (LOCK coverage_validator_contract)
    Tier-1 STRICT MECHANICAL referential-integrity ONLY over the
    `eval-coverage-manifest` block in AI-SPEC.md. For every declared
    `failure_modes[].id`, assert its `artifact_path` exists AND is non-empty
    (size > 0). Range-check the two discretion scalars (golden_set_size,
    acceptable_fail_rate). NOTHING fuzzy: this validator NEVER reads artifact
    CONTENT, NEVER infers COVERED / PARTIAL / MISSING, NEVER judges whether an
    artifact actually MITIGATES a failure mode. That semantic-adequacy verdict is
    DESCOPED (see below) — adding it here would be a Tier-2 LLM-judge task in
    disguise and would violate the governance invariant
    (kha_ai_track_eval_is_governed_not_imported: zero eval-JUDGE agents).

Manifest grammar (the parse contract; producers MUST match this byte-for-byte)
    A fenced YAML block delimited by HTML comments inside AI-SPEC.md:

        <!-- eval-coverage-manifest -->
        ```yaml
        golden_set_size: <int >= 1>
        acceptable_fail_rate: <float in [0.0, 1.0]>
        failure_modes:
          - id: <slug ^[a-z0-9][a-z0-9-]*$, unique>
            artifact_path: <repo-relative path to a test / fixture / judge-rubric>
          - id: ...
            artifact_path: ...
        ```
        <!-- /eval-coverage-manifest -->

    artifact_path resolves relative to the project root (os.getcwd(), the
    validators/__init__ caller contract).

Checks (all mechanical, advisory)
    M1  manifest block present + parses as a YAML mapping
    M2  golden_set_size is an int >= 1
    M3  acceptable_fail_rate is a real in [0.0, 1.0]
    M4  failure_modes is a non-empty list of {id, artifact_path} mappings
    M5  every id matches ^[a-z0-9][a-z0-9-]*$ and ids are unique
    M6  every artifact_path exists under the project root AND is non-empty (size>0)

Descoped capability (LOCK eval_wiring_rule / product_eval_disposition; impl-note 1)
    The gsd eval-auditor per-dimension semantic-adequacy verdict
    (COVERED / PARTIAL / MISSING) is NOT reproduced here. M6's
    "non-empty file exists" is REFERENTIAL presence only — a 1-byte stub file
    PASSES M6 but proves NOTHING about coverage adequacy. "manifest validates"
    must NEVER be read as "coverage is adequate". The adequacy half is governed
    once at the AI-SPEC §Failure-Mode-Taxonomy E1 debate gate, and ongoing
    product-LLM eval EXECUTION is user-CI scope (out of harness scope).
    This weakness is intentional and documented, not a bug.

ADVISORY tier (NOT in validators/__init__._BUILTIN): WARN-only, main()->0. The
    advisory->blocking FLIP is `graduate-validator`-token-gated (ready-flag
    streak>=N); false-MISSING / false-COVERED blast radius MUST be re-quantified
    before any such graduation. Until then this validator is inert in run_all.

Invocation
    python -m validators.ai_spec_eval_coverage              # audit cwd project
    python -m validators.ai_spec_eval_coverage --self-check # hermetic assertions
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _stream in (sys.stdin, sys.stdout):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        try:
            _reconfigure(encoding="utf-8")  # cp949 console safety (Windows)
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import yaml  # noqa: E402 (PyYAML 6.x present; used by lib.handoff_drift/phase_tree)

# Slug grammar for failure_mode ids — closed vocabulary so a paraphrased label
# cannot masquerade as an id.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Manifest delimiters (HTML comments survive markdown rendering, invisible to readers).
_OPEN = "<!-- eval-coverage-manifest -->"
_CLOSE = "<!-- /eval-coverage-manifest -->"

# Default discovery glob (kha phase layout). cwd == project root per caller contract.
_SPEC_GLOB = ".planning/**/AI-SPEC.md"


# ──────────────────────────── pure extractors ────────────────────────────
def extract_manifest(text: str) -> str | None:
    """Return the raw YAML text between the manifest delimiters (code fence
    stripped), or None if the block is absent. Pure; no I/O."""
    i = text.find(_OPEN)
    if i < 0:
        return None
    j = text.find(_CLOSE, i + len(_OPEN))
    if j < 0:
        return None
    inner = text[i + len(_OPEN):j]
    # Strip an optional ```yaml ... ``` code fence around the body.
    inner = re.sub(r"^\s*```[a-zA-Z0-9]*\s*\n", "", inner)
    inner = re.sub(r"\n\s*```\s*$", "\n", inner)
    return inner


def parse_manifest(yaml_text: str) -> dict | None:
    """yaml.safe_load → mapping, fail-soft (None on any parse error or non-mapping)."""
    try:
        data = yaml.safe_load(yaml_text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def check_manifest(manifest: dict, base_dir: Path) -> list[str]:
    """Mechanical checks M2-M6 over a parsed manifest mapping. Returns a list of
    [WARN] lines (empty == clean). NO content read, NO adequacy judgment."""
    warns: list[str] = []

    # M2 golden_set_size: int >= 1 (bool is a subclass of int — exclude it).
    gss = manifest.get("golden_set_size")
    if not isinstance(gss, int) or isinstance(gss, bool) or gss < 1:
        warns.append(f"[WARN] golden_set_size must be an int >= 1 (got {gss!r})")

    # M3 acceptable_fail_rate: real in [0.0, 1.0].
    afr = manifest.get("acceptable_fail_rate")
    if isinstance(afr, bool) or not isinstance(afr, (int, float)) or not (0.0 <= afr <= 1.0):
        warns.append(f"[WARN] acceptable_fail_rate must be a number in [0.0, 1.0] (got {afr!r})")

    # M4 failure_modes: non-empty list.
    fms = manifest.get("failure_modes")
    if not isinstance(fms, list) or not fms:
        warns.append(f"[WARN] failure_modes must be a non-empty list (got {type(fms).__name__})")
        return warns

    # M5 + M6 per entry.
    seen: set[str] = set()
    for idx, entry in enumerate(fms):
        if not isinstance(entry, dict):
            warns.append(f"[WARN] failure_modes[{idx}] must be a mapping (got {type(entry).__name__})")
            continue
        fid = entry.get("id")
        apath = entry.get("artifact_path")

        # M5 id grammar + uniqueness.
        if not isinstance(fid, str) or not _SLUG_RE.match(fid):
            warns.append(f"[WARN] failure_modes[{idx}].id must match ^[a-z0-9][a-z0-9-]*$ (got {fid!r})")
        elif fid in seen:
            warns.append(f"[WARN] failure_modes[{idx}].id duplicate: {fid!r}")
        else:
            seen.add(fid)

        # M6 artifact_path referential integrity (exists + non-empty). Presence
        # only — a non-empty stub PASSES; adequacy is descoped (see docstring).
        label = fid if isinstance(fid, str) else f"[{idx}]"
        if not isinstance(apath, str) or not apath.strip():
            warns.append(f"[WARN] failure_mode {label!r}: artifact_path missing or empty")
            continue
        resolved = (base_dir / apath).resolve()
        if not resolved.is_file():
            warns.append(f"[WARN] failure_mode {label!r}: artifact_path not a file: {apath}")
        elif resolved.stat().st_size == 0:
            warns.append(f"[WARN] failure_mode {label!r}: artifact_path is empty (0 bytes): {apath}")

    return warns


# ─────────────────────────────── scan / main ───────────────────────────────
def scan(root: Path | None = None) -> dict:
    """Discover AI-SPEC.md files under `root` (default cwd) and audit each.

    Returns {"specs": [{"path": str, "warns": [..]}], "missing_block": [str]}.
    A project with NO AI-SPEC.md is a clean no-op (not an AI phase)."""
    base = (root or Path.cwd()).resolve()
    specs: list[dict] = []
    missing_block: list[str] = []
    for spec in sorted(base.glob(_SPEC_GLOB)):
        try:
            text = spec.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(spec.relative_to(base)) if spec.is_relative_to(base) else str(spec)
        raw = extract_manifest(text)
        if raw is None:
            missing_block.append(rel)
            continue
        manifest = parse_manifest(raw)
        if manifest is None:
            specs.append({"path": rel, "warns": ["[WARN] eval-coverage-manifest is not a valid YAML mapping"]})
            continue
        # artifact_path is repo-relative → resolve against the PROJECT ROOT (base).
        specs.append({"path": rel, "warns": check_manifest(manifest, base)})
    return {"specs": specs, "missing_block": missing_block}


def _is_graduated() -> bool:
    """True iff this validator graduated advisory→blocking (Track 1
    debate-1780722434-e5h19n). Guarded + fail-soft: missing/garbled graduation
    state keeps us advisory. Lazy import keeps scan() hermetic."""
    try:
        from lib.graduation import is_graduated
        return is_graduated("ai_spec_eval_coverage")
    except Exception:
        return False


def main() -> int:
    r = scan()
    total = 0
    for spec in r["specs"]:
        for w in spec["warns"]:
            print(f"{w}  ({spec['path']})")
            total += 1
    n_specs = len(r["specs"])
    tier = "blocking" if _is_graduated() else "advisory"
    summary = (
        f"ai_spec_eval_coverage — {n_specs} AI-SPEC manifest(s) audited, "
        f"{total} coverage drift, {len(r['missing_block'])} spec(s) without a manifest "
        f"({tier})"
    )
    # Graduated (blocking) mode FAILs on any drift; advisory stays exit-0.
    if tier == "blocking" and total > 0:
        print(f"[FAIL] {summary}")
        return 1
    print(f"[PASS] {summary}")
    return 0


def _self_check() -> int:
    """Hermetic assertions on the pure extractors/checkers (synthetic fixtures)."""
    import tempfile
    n = 0

    def _a(cond: bool, msg: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            raise AssertionError(f"ai_spec_eval_coverage self-check FAIL: {msg}")

    # extract_manifest
    doc = (
        "intro\n" + _OPEN + "\n```yaml\ngolden_set_size: 5\n```\n" + _CLOSE + "\nrest\n"
    )
    raw = extract_manifest(doc)
    _a(raw is not None and "golden_set_size: 5" in raw, "manifest extracted, fence stripped")
    _a(extract_manifest("no manifest here") is None, "absent manifest → None")

    # parse_manifest fail-soft
    _a(parse_manifest("a: 1") == {"a": 1}, "yaml mapping parsed")
    _a(parse_manifest("- not\n- a mapping") is None, "non-mapping → None")
    _a(parse_manifest(": : :") is None, "garbled yaml → None (fail-soft)")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        good = base / "tests" / "fm_a.py"
        good.parent.mkdir(parents=True)
        good.write_text("assert True\n", encoding="utf-8")
        (base / "empty.py").write_text("", encoding="utf-8")

        # clean manifest
        clean = {
            "golden_set_size": 3,
            "acceptable_fail_rate": 0.1,
            "failure_modes": [{"id": "fm-a", "artifact_path": "tests/fm_a.py"}],
        }
        _a(check_manifest(clean, base) == [], "clean manifest → no warns")

        # M2/M3 scalar violations
        bad_scalars = dict(clean, golden_set_size=0, acceptable_fail_rate=1.5)
        w = check_manifest(bad_scalars, base)
        _a(any("golden_set_size" in x for x in w), "golden_set_size<1 warned")
        _a(any("acceptable_fail_rate" in x for x in w), "acceptable_fail_rate>1 warned")
        # bool must NOT pass the int check (bool is subclass of int)
        _a(any("golden_set_size" in x for x in check_manifest(dict(clean, golden_set_size=True), base)),
           "bool golden_set_size rejected")

        # M5 slug + uniqueness
        w = check_manifest(dict(clean, failure_modes=[
            {"id": "Bad_Id", "artifact_path": "tests/fm_a.py"},
            {"id": "fm-a", "artifact_path": "tests/fm_a.py"},
            {"id": "fm-a", "artifact_path": "tests/fm_a.py"},
        ]), base)
        _a(any("Bad_Id" in x for x in w), "non-slug id warned")
        _a(any("duplicate" in x for x in w), "duplicate id warned")

        # M6 referential integrity — missing + empty (1-byte-stub boundary)
        w = check_manifest(dict(clean, failure_modes=[
            {"id": "fm-missing", "artifact_path": "tests/nope.py"},
            {"id": "fm-empty", "artifact_path": "empty.py"},
        ]), base)
        _a(any("not a file" in x for x in w), "missing artifact warned")
        _a(any("empty (0 bytes)" in x for x in w), "empty artifact warned")
        # a NON-empty stub PASSES M6 (documented descope boundary)
        good.write_text("x", encoding="utf-8")  # 1 byte
        _a(check_manifest(clean, base) == [], "1-byte stub PASSES M6 (referential only, adequacy descoped)")

        # M4 empty list
        _a(any("non-empty list" in x for x in check_manifest(dict(clean, failure_modes=[]), base)),
           "empty failure_modes warned")

    print(f"[OK] ai_spec_eval_coverage self-check: {n} assertions passed")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    sys.exit(main())

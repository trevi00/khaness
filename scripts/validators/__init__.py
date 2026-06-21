"""Harness validators — ported from scripts/verify-*.py.

Each validator is a standalone module with a main() function that reads
the current working directory (os.getcwd() == project root) and prints
[PASS]/[FAIL]/[WARN] lines. Validators do not take arguments and do not
raise — failures are communicated via stdout lines.

Naming:
- Most validators map 1:1 to the original verify-<name>.py.
- `test` shadows Python's stdlib `test` module — import as
  `from validators.test import main` or `validators.get_validator("test")`,
  never `from validators import test` from outside the package.

Caller contract:
- Set os.chdir(<project_root>) before calling main(), OR run via subprocess
  with cwd=<project_root> (matches pre-refactor behavior).
- Each main() prints to stdout and returns None. Capture stdout to
  interpret PASS/FAIL/WARN lines.
"""
from __future__ import annotations

from importlib import import_module
from typing import Callable


# _BUILTIN = always-blocking validators (the original registry). GRADUATED
# names are appended at import via lib.graduation.graduated_names() — Track 1
# debate-1780722434-e5h19n gen-2 D2/C3: `VALIDATOR_NAMES = _BUILTIN +
# GRADUATED_NAMES` concat (graduate = append, demote = delete, diff-auditable),
# never an in-place tuple splice. The advisory→blocking FLIP that populates
# GRADUATED_NAMES is `graduate-validator`-token-gated (cli/graduate_validator.py);
# until a flip occurs this concat is inert and VALIDATOR_NAMES == _BUILTIN.
_BUILTIN: tuple[str, ...] = (
    "atlas_frontmatter",
    "atlas_structure",
    "ci",
    "code_blind_proceed",
    "codegen",
    "collab",
    "commit_layer_adjacency",
    "contract",
    "convention",
    "ddl",
    "er",
    "exit_contract_coverage",
    "falsy_zero",
    "flow",
    "git_flow",
    "handoff_drift",
    "harness_bridge_state_block",
    "hashline",
    "insight_index_importer_whitelist",
    "logical",
    "mutation_safety",
    "openapi",
    "prd",
    "private_content_leak",
    "skeleton",
    "skill_frontmatter",
    "skill_quality_axes",
    "skill_staging_isolation",
    "skill_structure_depth",
    "spec_bundle",
    "spec_roundtrip",
    "subagent_refs",
    "test",
    "test_depth",
    "threshold_registry_locked",
)


def _graduated() -> tuple[str, ...]:
    """Graduated validator names, fail-soft (empty on any error so a garbled
    graduation-state.json can never break the registry import)."""
    try:
        from lib.graduation import graduated_names
        return tuple(n for n in graduated_names() if n not in _BUILTIN)
    except Exception:
        return ()


VALIDATOR_NAMES: tuple[str, ...] = _BUILTIN + _graduated()


def graduation_scan_drift(name: str) -> int:
    """Total live drift count for a TRACKED advisory validator, via its in-process
    scan() dict (Track 1 D1a/D5 — structured CLEAN, not a stdout scrape). Lives
    in the validators layer because lib/graduation must not import validators;
    handlers/cli inject this as the streak tick's scan_fn. Raises on a real scan
    failure (the tick treats that as 'leave the counter untouched')."""
    if name == "doc_code_drift":
        from validators import doc_code_drift as v
        r = v.scan()
        return len(r["name_warns"]) + len(r["path_warns"])
    if name == "self_model_drift":
        from validators import self_model_drift as v
        r = v.scan()
        return len(r["tools_warns"]) + len(r["scriptref_warns"]) + len(r["mutmirror_warns"])
    if name == "producer_consumer_coherence":
        # Graduation tracks ONLY the HIGH class (deterministic dead seams: never-written
        # telemetry path + unproduced marker_keys). MED 0-caller is judgment-laden and
        # stays advisory/on-demand, never gating the streak (debate-1781768055-e7o7su).
        from validators import producer_consumer_coherence as v
        return len(v.scan()["high"])
    raise KeyError(f"not a tracked validator: {name!r}")


def get_validator(name: str) -> Callable[[], None]:
    if name not in VALIDATOR_NAMES:
        raise KeyError(
            f"Unknown validator: {name!r}. Known: {list(VALIDATOR_NAMES)}"
        )
    mod = import_module(f".{name}", package=__name__)
    fn = getattr(mod, "main", None)
    if not callable(fn):
        raise AttributeError(f"Validator {name!r} has no callable main()")
    return fn


def run_validator(name: str) -> None:
    get_validator(name)()

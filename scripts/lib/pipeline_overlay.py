"""pipeline_overlay — neutral-core + stack-overlay merge (unified-pipeline D2).

The forward pipeline is split into a STACK-NEUTRAL core (`stages.core.yaml`) and
per-stack OVERLAYS (`overlays/<lang>.overlay.yaml`). `load_merged` deep-merges the
two by stage id IN MEMORY and returns the same `list[dict]` shape the 5
deterministic consumers read (via the lib.pipeline_yaml value-normalization
contract), so a new language is one overlay file — not a 23-stage copy. This
replaces the drift-prone full-file variants (stages-flutter.yaml etc.).

Overlay schema (generalized in D2-3 after the flutter variant proved a stack
differs from the core in more than gates):

    stack: <lang>
    source_finder: <fn>            # how the reverse extractor finds sources
    testgen: {framework, ...}      # how acceptance tests are generated
    applicable_stages: [id, ...]   # the ordered stages THIS stack runs (subset /
                                   # superset of core; omit -> all core stages)
    stages:                        # per-stage field overrides; any of
      <id>:                        # name/input/output/artifact/optional/gate/skills.
        output: "..."              # an id NOT in core = a stack-ADDED stage (full def).
        gate: [...]
        skills: [...]

Merge per stage id: `{**core_stage, **overlay_override}`, in `applicable_stages`
order, then value-normalized. Java is the golden reference: merging the java
overlay reproduces the legacy stages.yaml (test_java_golden_pin); the same neutral
core + the flutter overlay reproduces stages-flutter.yaml (test_flutter_golden_pin),
proving the core is genuinely shared.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .paths import SKILLS_DIR
from .pipeline_yaml import normalize_value

# Keys whose list value renders as a '[a, b]' FLOW string (consumers parse that
# form); every other list (gate) stays a native list, matching parse_stages.
_FLOW_STRING_KEYS = ("input", "skills")
# Neutral additive keys with no consumer — kept native (list/scalar) as authored.
_NATIVE_KEYS = ("gate_intent", "skills_intent")


def _pipeline_dir() -> Path:
    return SKILLS_DIR / "_pipeline"


def core_path() -> Path:
    return _pipeline_dir() / "stages.core.yaml"


def overlay_path(lang: str) -> Path:
    return _pipeline_dir() / "overlays" / f"{lang}.overlay.yaml"


def _load_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _core_stage_list(core: object) -> list[dict]:
    if isinstance(core, dict):
        s = core.get("stages")
        return s if isinstance(s, list) else []
    return core if isinstance(core, list) else []


def _normalize_field(key: str, value: object) -> object:
    """Render a merged field to the consumer-visible shape parse_stages produces."""
    if key in _NATIVE_KEYS:
        return value
    if key in _FLOW_STRING_KEYS:
        return normalize_value(value, is_flow_seq=isinstance(value, list))
    # gate stays a native list (block-seq, no consumer); scalars/bools normalized.
    return normalize_value(value, is_flow_seq=False)


def merge_core_overlay(core: object, overlay: object) -> list[dict[str, object]]:
    """Pure deep-merge by stage id. Returns list[dict] in consumer-normalized shape.

    For each id in `applicable_stages` (default: all core stages in core order),
    the merged stage is the core stage updated by the overlay's per-stage override
    ({**core, **override}); an id absent from core is a stack-added stage taken
    wholly from the override."""
    core_stages = _core_stage_list(core)
    core_by_id = {s["id"]: s for s in core_stages if isinstance(s, dict) and "id" in s}
    ov = overlay if isinstance(overlay, dict) else {}
    overrides = ov.get("stages") if isinstance(ov.get("stages"), dict) else {}
    applicable = ov.get("applicable_stages")
    if not isinstance(applicable, list) or not applicable:
        applicable = [s["id"] for s in core_stages if isinstance(s, dict) and "id" in s]

    out: list[dict[str, object]] = []
    for sid in applicable:
        base = dict(core_by_id.get(sid, {}))
        override = overrides.get(sid) if isinstance(overrides.get(sid), dict) else {}
        merged = {**base, **override}
        merged["id"] = sid
        out.append({k: _normalize_field(k, v) for k, v in merged.items()})
    return out


def load_merged(cwd: str | Path | None, lang: str | None) -> list[dict[str, object]]:
    """Load stages.core.yaml + overlays/<lang>.overlay.yaml and merge by stage id,
    returning the list[dict] shape lib.pipeline_yaml.parse_stages returns. No
    overlay for `lang` -> the neutral core (all stages, gate_intent only).
    Fail-soft: missing core -> []."""
    core = _load_yaml(core_path())
    if core is None:
        return []
    overlay = _load_yaml(overlay_path(lang)) if lang else None
    return merge_core_overlay(core, overlay or {})


def has_overlay(lang: str | None) -> bool:
    """True iff a stack overlay file exists for `lang` (drives the picker cutover —
    stacks with an overlay use load_merged, others stay on legacy parse_stages)."""
    return bool(lang) and overlay_path(lang).is_file()

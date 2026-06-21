"""stages.yaml parser — shared by skill-matcher (pipeline detection) and
context-loader (pipeline status injection).

Resolution priority:
  1. {cwd}/.claude/stages.yaml (project override, only if it has stages)
  2. ~/.claude/skills/_pipeline/stages-{lang}.yaml (stack variant)
  3. ~/.claude/skills/_pipeline/stages.yaml (global default)

Parser (unified-pipeline D2): the original hand-rolled flat line-parser was
REPLACED by a real `yaml.safe_load` so the neutral-core + overlay merge
(lib/pipeline_overlay.load_merged) can carry NESTED overlay structure the flat
parser provably could not. To keep the 5 deterministic consumers byte-untouched,
`parse_stages` applies a VALUE-NORMALIZATION CONTRACT that reproduces the flat
parser's string-shaped output for the keys consumers read:
  - YAML bool  -> 'true'/'false' lowercase string  (consumers: optional == 'true')
  - FLOW seq   -> '[a, b]' string form              (consumer: skills _skills_to_files)
  - BLOCK seq  -> native list                       (gate has NO consumer; old parser
                                                      dropped it to '' — a bug; the real
                                                      list is correct and harmless)
  - other scalar -> str(v)                          (old parser produced strings)
Flow vs block is recovered from the PyYAML node tree (`compose`), since
`safe_load` alone collapses both to a list. See tests/test_parser_equivalence.py.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .paths import SKILLS_DIR


# Additive delta (unified-pipeline D2): input/artifact/gate_intent/skills_intent
# join the original 7. Existing keys untouched; consumers use .get(k, '') so the
# new keys are invisible to them. The lock test (test_pipeline_yaml.py::
# test_known_stage_keys_locked) is updated in the same commit.
KNOWN_STAGE_KEYS: frozenset[str] = frozenset({
    "name", "output", "gate", "phase", "optional", "skills", "dge",
    "input", "artifact", "gate_intent", "skills_intent",
})


def _pipeline_dir() -> Path:
    return SKILLS_DIR / "_pipeline"


def resolve_stages_path(
    cwd: str | Path | None,
    language: str | None = None,
) -> Path | None:
    """Find the appropriate stages.yaml file to load."""
    pipeline_dir = _pipeline_dir()

    if cwd:
        project_path = Path(cwd) / ".claude" / "stages.yaml"
        if project_path.is_file():
            try:
                if "- id:" in project_path.read_text(encoding="utf-8"):
                    return project_path
            except Exception:
                pass

    if language:
        variant = pipeline_dir / f"stages-{language}.yaml"
        if variant.is_file():
            return variant

    global_path = pipeline_dir / "stages.yaml"
    return global_path if global_path.is_file() else None


# ── value normalization (the D2 contract) ──
def _stages_list(data: object) -> list:
    """Extract the stages list from either shape: a `{stages: [...]}` mapping
    (the global default) OR a top-level YAML list (project overrides / tests).
    The old flat parser was format-agnostic (it scanned for `- id:` anywhere);
    we preserve that by accepting both."""
    if isinstance(data, dict):
        s = data.get("stages")
        return s if isinstance(s, list) else []
    if isinstance(data, list):
        return data
    return []


def _flow_seq_map(text: str) -> dict[tuple[int, str], bool]:
    """Recover which (stage_index, key) values are FLOW sequences ('[a, b]') vs
    BLOCK sequences. `safe_load` collapses both to a list, so we read flow_style
    off the composed node tree. Handles both the `stages:` mapping and the
    top-level-list shapes. Fail-soft: any error → {} (lists then render as
    native, never affecting scalar/bool correctness)."""
    out: dict[tuple[int, str], bool] = {}
    try:
        root = yaml.compose(text)
    except Exception:
        return out
    if root is None:
        return out
    # Find the sequence node holding the stages, under either shape.
    seq_node = None
    cls = root.__class__.__name__
    if cls == "SequenceNode":
        seq_node = root
    elif cls == "MappingNode":
        for k_node, v_node in getattr(root, "value", []) or []:
            if getattr(k_node, "value", None) == "stages":
                seq_node = v_node
                break
    if seq_node is None or seq_node.__class__.__name__ != "SequenceNode":
        return out
    for idx, stage_node in enumerate(getattr(seq_node, "value", []) or []):
        for sk_node, sv_node in getattr(stage_node, "value", []) or []:
            key = getattr(sk_node, "value", None)
            if not isinstance(key, str):
                continue
            if sv_node.__class__.__name__ == "SequenceNode":
                out[(idx, key)] = bool(getattr(sv_node, "flow_style", False))
    return out


def _scalar_str(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def normalize_value(v: object, *, is_flow_seq: bool) -> object:
    """Coerce a YAML-native value to the flat-parser string shape consumers expect.

    bool -> 'true'/'false'; FLOW sequence -> '[a, b]' string; BLOCK sequence ->
    native list (no consumer); other scalar -> str(v). Pure."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        if is_flow_seq:
            return "[" + ", ".join(_scalar_str(x) for x in v) + "]"
        return v
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def parse_stages(path: Path) -> list[dict[str, object]]:
    """Parse stages.yaml into a list of stage dicts via real YAML load.

    Each stage carries 'id' plus the keys it declares that are in
    KNOWN_STAGE_KEYS. Values are normalized (see module docstring) so the 5
    deterministic consumers see the same string shapes the old flat parser
    produced. Missing keys are simply absent — callers use .get(key, '').
    Fail-soft: unreadable/invalid file → [].
    """
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except Exception:
        return []
    raw_stages = _stages_list(data)
    if not raw_stages:
        return []

    flow = _flow_seq_map(text)
    keep = KNOWN_STAGE_KEYS | {"id"}
    out: list[dict[str, object]] = []
    for idx, st in enumerate(raw_stages):
        if not isinstance(st, dict):
            continue
        stage: dict[str, object] = {}
        for k, v in st.items():
            if not isinstance(k, str) or k not in keep:
                continue
            stage[k] = normalize_value(v, is_flow_seq=flow.get((idx, k), False))
        out.append(stage)
    return out


def parse_output_list(output: str) -> list[str]:
    """Split a stage's 'output' field — accepts either a single path or '[a, b]'."""
    if not output:
        return []
    if output.startswith("[") and output.endswith("]"):
        return [
            v.strip().strip("'\"")
            for v in output[1:-1].split(",")
            if v.strip()
        ]
    return [output]

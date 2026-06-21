"""HANDOFF.md phase-tree drift detection (W21+ relocation from cli/handoff_render).

Pure logic that lives under `lib/` so handlers + cli + engine can all
reuse it. The `cli/handoff_render.py` CLI is now a thin argparse wrapper
around this module; `handlers/post_tool/reviewer.py` calls
`emit_drift_advisory()` to surface drift on PostToolUse Edit/Write of
HANDOFF.md.

Format normalization (HANDOFF.md yaml block -> phase_tree dataclass):
  - root field aliases: phase_id -> id, phase_goal -> goal,
    parent_phase -> parent_id
  - sub_phase flat keys: any top-level `step_*` key collapses into a
    `steps` dict so phase_tree.Phase can ingest the legacy schema

Anchor markers (HTML comments, idempotent in-place rewriting):
  <!-- BEGIN: phase-tree-visualization -->
  ```
  <rendered tree>
  ```
  <!-- END: phase-tree-visualization -->
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .phase_tree import Status, _dict_to_phase, deepest_in_progress, render_tree_markdown


YAML_FENCE_RE = re.compile(
    r"^##\s+Current Phase Block[^\n]*\n+```yaml\n(.*?)\n```",
    re.DOTALL | re.MULTILINE,
)
ANCHOR_BEGIN = "<!-- BEGIN: phase-tree-visualization -->"
ANCHOR_END = "<!-- END: phase-tree-visualization -->"
_ANCHORED_RE = re.compile(
    re.escape(ANCHOR_BEGIN) + r"\n(.*?)\n" + re.escape(ANCHOR_END),
    re.DOTALL,
)


def _coalesce_step_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize HANDOFF.md yaml shape -> phase_tree dataclass shape."""
    out: dict[str, Any] = dict(data)
    aliases = (
        ("phase_id", "id"),
        ("phase_goal", "goal"),
        ("parent_phase", "parent_id"),
    )
    for src, dst in aliases:
        if src in out and dst not in out:
            out[dst] = out.pop(src)

    steps: dict[str, str] = dict(out.get("steps") or {})
    for k in list(out.keys()):
        if k.startswith("step_"):
            steps[k] = str(out.pop(k))
    if steps:
        out["steps"] = steps

    sub = out.get("sub_phases")
    if isinstance(sub, list):
        out["sub_phases"] = [
            _coalesce_step_keys(item) if isinstance(item, dict) else item
            for item in sub
        ]
    return out


def extract_yaml_block(handoff_text: str) -> str:
    m = YAML_FENCE_RE.search(handoff_text)
    if not m:
        raise ValueError(
            "HANDOFF.md: '## Current Phase Block' yaml fenced block not found"
        )
    return m.group(1)


def render_from_handoff(handoff_text: str) -> str:
    yaml_text = extract_yaml_block(handoff_text)
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise ValueError("phase yaml must be a mapping")
    root = _dict_to_phase(_coalesce_step_keys(data))
    return render_tree_markdown(root)


def parse_handoff_tree(handoff_text: str):
    """Parse a HANDOFF/PHASES text's '## Current Phase Block' into a phase_tree.Phase
    tree (same path as render_from_handoff, but returns the TREE not rendered md).
    Path-agnostic — handoff_text may come from any file (W4: <project>/atlas/mirror/
    PHASES.md reuses this verbatim). Raises on missing/invalid yaml block."""
    yaml_text = extract_yaml_block(handoff_text)
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise ValueError("phase yaml must be a mapping")
    return _dict_to_phase(_coalesce_step_keys(data))


def _step_status_token(v: str) -> str | None:
    """Leading Status token of a step value — 'DONE (kha-core...)' -> 'done',
    'pending' -> 'pending', 'PARTIAL ...' -> 'in_progress' (convention alias, cf.
    promote_sub_phase _infer_status_from_value). None when the value does NOT begin
    with a recognized status word (genuinely free-text). Enables n/m on the REAL
    convention format (descriptive step values), which the live demo showed never
    produced n/m under the strict whole-value check (debate-1781493074 follow-up)."""
    s = str(v).strip()
    if not s:
        return None
    head = s.split(None, 1)[0].strip(":-").lower()
    if head in {st.value for st in Status}:
        return head
    if head == "partial":
        return Status.IN_PROGRESS.value
    return None


def current_node_suffix(handoff_text: str) -> str:
    """One-line '현재: <id> ▸ <step> (<n>/<m>)' for the DEEPEST in_progress node of a
    work-tree (debate-1781493074-c16jtw W3/W7), or '' on no-in_progress / parse
    failure. READ-ONLY (W8). The (n/m) progress suffix is emitted when ANY step
    carries a recognizable leading Status token (the convention's 'DONE (...)' /
    'PENDING (...)' form); a node whose steps are ALL genuinely free-text degrades
    to just '현재: <id>' (W7). Caller folds the return into the work-resume line."""
    try:
        root = parse_handoff_tree(handoff_text)
        node = deepest_in_progress(root)
        if node is None:
            return ""
        base = f"현재: {node.id}"
        steps = node.steps or {}
        if not steps:
            return base
        tokens = {k: _step_status_token(v) for k, v in steps.items()}
        if not any(t is not None for t in tokens.values()):
            return base  # all genuinely free-text -> no n/m (W7)
        total = len(steps)
        done = sum(1 for t in tokens.values() if t == Status.DONE.value)
        cur = next((k for k, t in tokens.items() if t != Status.DONE.value), None)
        cur_part = f" ▸ {cur}" if cur else ""
        return f"{base}{cur_part} ({done}/{total})"
    except Exception:
        return ""


def code_blind_readiness(handoff_text: str) -> tuple[bool, str]:
    """M16: can the harness resume this work CODE-BLIND from brain + HANDOFF alone?

    The brain surfaces the current work node by parsing the HANDOFF `## Current Phase
    Block` yaml (current_node_suffix → parse_handoff_tree). If that yaml is PRESENT but
    UNPARSEABLE, the surface silently degrades to '' — you cannot tell where work stands
    without reading code, defeating the whole code-blind-proceed loop. The classic cause
    is a `이름: 설명` colon inside a step value (yaml maps it as a key) — see
    reference_phases_yaml_colon_breaks_brain.

    Returns (ok, reason):
      - (True,  "no phase block")        — no '## Current Phase Block' yaml (opt-out)
      - (False, "<parse error detail>")  — block present but unparseable → NOT code-blind
                                            resumable (the enforce case the validator FAILs on)
      - (True,  "parseable: 현재: ...")  — block parses; current-node surface recoverable

    Distinct from check_drift (anchored-block-vs-yaml = transient edit-cycle drift → WARN);
    an unparseable yaml is a hard breakage, not transient, so the validator FAILs on it.
    """
    try:
        extract_yaml_block(handoff_text)
    except ValueError:
        return True, "no '## Current Phase Block' yaml (opt-out)"
    try:
        parse_handoff_tree(handoff_text)
    except Exception as e:  # noqa: BLE001 — any parse failure means the brain surface breaks
        return False, (
            f"Current Phase Block yaml unparseable ({type(e).__name__}: {e}) — brain "
            f"current-node surface degrades to '' (cannot resume code-blind). Common cause: "
            f"a `이름: 설명` colon inside a step value; use `이름 — 설명`. Then re-render: "
            f"`python -m cli.handoff_render <handoff> --in-place`."
        )
    suffix = current_node_suffix(handoff_text)
    return True, f"parseable; surface={suffix or '(no in-progress node)'}"


def _build_anchored_block(tree: str) -> str:
    return f"{ANCHOR_BEGIN}\n```\n{tree}\n```\n{ANCHOR_END}"


def replace_anchored(handoff_text: str, tree: str) -> str:
    """Replace content between BEGIN/END anchors. Raises if anchors missing."""
    if not _ANCHORED_RE.search(handoff_text):
        raise ValueError(
            f"HANDOFF.md missing anchor markers ({ANCHOR_BEGIN} / {ANCHOR_END}). "
            "Add an empty fenced block between them under any heading first."
        )
    replacement = _build_anchored_block(tree)
    return _ANCHORED_RE.sub(lambda _m: replacement, handoff_text, count=1)


def check_drift(handoff_text: str, tree: str) -> bool:
    """True if anchored block differs from a freshly-rendered tree (or absent)."""
    m = _ANCHORED_RE.search(handoff_text)
    if not m:
        return True
    return m.group(0) != _build_anchored_block(tree)


def is_anchor_present(handoff_text: str) -> bool:
    """True if the BEGIN/END phase-tree-visualization markers are both present.

    Validators use this to distinguish 'no anchor block, opt-out' (PASS) from
    'anchor block exists but stale' (WARN). check_drift() conflates these by
    returning True for both, so a public helper is needed for the WARN gate.
    """
    return bool(_ANCHORED_RE.search(handoff_text))


def detect_promotable_sub_phases(handoff_text: str) -> list[str]:
    """Return sub_phase ids that satisfy phase_tree.should_promote().

    HANDOFF Phase Tree Convention (CLAUDE.md): a sub_phase with >=5 steps AND
    at least one step whose value carries a nested marker (>=3 commas /
    >=2 semicolons in the value string) is a candidate for promotion to a
    child phase block.

    This is a HANDOFF-health signal independent of drift. Both surface in
    the same validator (handoff_drift) since they read the same yaml block.

    Returns [] on parse error or no candidates (fail-soft like check_drift).
    """
    try:
        from .phase_tree import should_promote
        yaml_text = extract_yaml_block(handoff_text)
        import yaml as _yaml
        data = _yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return []
        normalized = _coalesce_step_keys(data)
        root = _dict_to_phase(normalized)
        return [sp.id for sp in root.sub_phases if should_promote(sp)]
    except Exception:
        return []


# ---------- Promotion: yaml flat step_* → nested sub_phases (vision #4) ----------

import json  # noqa: E402

_SUB_PHASE_ID_RE = re.compile(r"^(\s*-\s+id:\s*)(\S+)\s*$")
_STEP_KEY_RE = re.compile(r"^\s*(step_[A-Za-z0-9_]+)\s*:\s*(.*)$")


def _infer_status_from_value(value: str) -> str:
    """Heuristic mapping from flat step value text to phase_tree.Status.

    Matches the value-prefix conventions seen in real HANDOFF.md:
      'DONE (...)'    → 'done'
      'PARTIAL (...)' → 'in_progress'  (still active; PARTIAL is mid-progress)
      'pending (...)' → 'pending'
      anything else   → 'in_progress'  (conservative default)
    """
    stripped = value.strip().strip('"').strip("'").upper()
    if stripped.startswith("DONE"):
        return "done"
    if stripped.startswith("PARTIAL"):
        return "in_progress"
    if stripped.startswith("PENDING"):
        return "pending"
    return "in_progress"


def promote_sub_phase(handoff_text: str, sub_phase_id: str) -> str:
    """Transform flat `step_*` keys of `sub_phase_id` into nested sub_phases.

    Surgical text replacement — preserves all surrounding text verbatim
    (including yaml comments outside the target sub_phase). PyYAML round-trip
    is intentionally NOT used because safe_load + safe_dump loses inline
    comments like `status: in_progress  # 2026-05-07 시작`.

    Algorithm:
      1. extract_yaml_block(handoff_text) — locate the machine-readable block
      2. Find `- id: <sub_phase_id>` line by regex match
      3. Walk forward to find the sub_phase block boundary (next sibling
         `- id:` at same indent OR back to root-level indent)
      4. Within the block, separate step_* lines from other lines
      5. Emit a new block: other lines verbatim + `sub_phases:` + per-step
         nested entry (id + status inferred from value prefix + notes carrying
         the original value as a JSON-quoted string for yaml safety)
      6. Splice the new block into handoff_text via string.replace(yaml_block,...)

    Raises ValueError if:
      - yaml block missing (extract_yaml_block raises)
      - target sub_phase_id not found
      - target has zero `step_*` keys (nothing to promote)

    Returns the modified handoff_text. Caller writes back via Path.write_text.
    """
    yaml_block = extract_yaml_block(handoff_text)
    block_lines = yaml_block.splitlines()

    # ---- Locate target sub_phase by id ----
    target_idx: int | None = None
    sub_phase_indent: int = 0
    for i, line in enumerate(block_lines):
        m = _SUB_PHASE_ID_RE.match(line)
        if m and m.group(2) == sub_phase_id:
            target_idx = i
            sub_phase_indent = len(line) - len(line.lstrip())
            break
    if target_idx is None:
        raise ValueError(f"sub_phase id {sub_phase_id!r} not found in HANDOFF yaml block")

    # ---- Find end of this sub_phase block ----
    # Boundary: next non-empty line at indent <= sub_phase_indent (next sibling
    # `- id:` is at the same indent as our `- id:`).
    end_idx = len(block_lines)
    for j in range(target_idx + 1, len(block_lines)):
        line = block_lines[j]
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= sub_phase_indent:
            end_idx = j
            break

    inner_lines = block_lines[target_idx:end_idx]  # includes the `- id:` header

    # ---- Separate step_* keys from other property lines ----
    other_lines: list[str] = []
    step_entries: list[tuple[str, str]] = []  # [(step_key, raw_value)]
    for line in inner_lines:
        m = _STEP_KEY_RE.match(line)
        # Only catch step_* lines whose indent is > sub_phase_indent (so we
        # don't capture a `step_*:` that's actually inside an unrelated nested
        # structure — defensive, current HANDOFF schema doesn't nest this deep)
        if m and (len(line) - len(line.lstrip()) > sub_phase_indent):
            step_entries.append((m.group(1), m.group(2)))
        else:
            other_lines.append(line)

    if not step_entries:
        raise ValueError(
            f"sub_phase {sub_phase_id!r} has no step_* keys to promote"
        )

    # ---- Build replacement block ----
    # In yaml list-of-mapping form `  - id: foo`, the dash is at column
    # `sub_phase_indent`, the `id` key starts at `sub_phase_indent + 2`,
    # and sibling keys (status, step_*) align with `id`. So children of the
    # list item live at `sub_phase_indent + 2`. The new `sub_phases:` key
    # is a sibling of those, so it goes at the same depth.
    inner_indent = sub_phase_indent + 2
    space = " " * inner_indent
    child_indent = " " * (inner_indent + 2)
    notes_indent = " " * (inner_indent + 4)

    def _normalize_value(raw: str) -> str:
        """Strip yaml quoting layer if present so json.dumps doesn't double-quote."""
        s = raw.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
            return s[1:-1]
        return s

    replacement: list[str] = list(other_lines)
    replacement.append(f"{space}sub_phases:")
    for step_key, raw_value in step_entries:
        status = _infer_status_from_value(raw_value)
        replacement.append(f"{child_indent}- id: {step_key}")
        replacement.append(f"{child_indent}  status: {status}")
        replacement.append(f"{child_indent}  notes:")
        # JSON-quote to handle yaml-dangerous chars (':', '#', etc.). Strip
        # any pre-existing yaml quoting first to avoid embedded literal quotes.
        normalized = _normalize_value(raw_value)
        replacement.append(
            f"{notes_indent}- {json.dumps(normalized, ensure_ascii=False)}"
        )

    # ---- Splice replacement into the yaml block ----
    new_block_lines = block_lines[:target_idx] + replacement + block_lines[end_idx:]
    new_yaml_text = "\n".join(new_block_lines)

    # Preserve trailing newline if original had one (safe_load is whitespace-tolerant
    # but we want byte-stable text-surgery semantics).
    if yaml_block.endswith("\n") and not new_yaml_text.endswith("\n"):
        new_yaml_text += "\n"

    # Splice into full handoff_text. Use replace with count=1 since the block
    # marker pattern (`## Current Phase Block ... ```yaml ... ```) appears
    # exactly once.
    return handoff_text.replace(yaml_block, new_yaml_text, 1)


def emit_drift_advisory(handoff_path: str | Path) -> str | None:
    """PostToolUse helper — return advisory text if drift, else None.

    Fail-open: any exception (file unreadable, yaml parse error, missing
    anchor block, etc.) returns None. Drift surfacing is best-effort and
    must NEVER block the hook output stream.

    Returns a `<phase-tree-drift>` xml-style advisory ready for
    PostToolUse `additionalContext` injection.
    """
    try:
        path = Path(handoff_path)
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        tree = render_from_handoff(text)
        if not check_drift(text, tree):
            return None
        return (
            "<phase-tree-drift>\n"
            "[HANDOFF.md drift] yaml block과 anchored phase-tree block 불일치.\n"
            "  fix: `python -m cli.handoff_render <handoff> --in-place`\n"
            "  check: `python -m cli.handoff_render <handoff> --check`\n"
            "</phase-tree-drift>"
        )
    except Exception:
        return None


def status_line_for_session(cwd: str | Path) -> str | None:
    """SessionStart helper — returns single status line if drift detected.

    Returns None on clean state (no HANDOFF, no drift, parse error, etc.) so
    the harness-status block stays silent — caller treats None as the absence
    of any signal. Same fail-open semantic as `emit_drift_advisory`.
    """
    try:
        path = Path(cwd) / "HANDOFF.md"
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        tree = render_from_handoff(text)
        if not check_drift(text, tree):
            return None
        return (
            f"[phase-tree-drift] HANDOFF.md anchored block과 yaml 불일치 — "
            f"`python -m cli.handoff_render {path} --in-place`"
        )
    except Exception:
        return None

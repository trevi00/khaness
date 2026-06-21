"""pipeline_stage_picker — next pipeline stage detection (Round 6 W2 P1).

Extracted from handlers/prompt/skill_match.py. Given a project cwd, walk the
configured pipeline stages, identify which stages have completed (their
declared `output` artifacts exist), and return the NEXT stage's recommended
skills + DGE role + stage name.

## Contract
- detect_pipeline_skills(cwd) -> (skill_names: list[str], dge_role: str, stage_name: str)
- Returns ([], "", "") when no pipeline detected.

## Search heuristic
For each stage, check whether any declared output file exists in:
- cwd
- .claude/, .claude/design/, .claude/design/db/, .claude/design/api/
- etc/sql/
- src/

Special case: if `src/` is mentioned in output and src/ is non-empty, treat
as found (skeleton-stage heuristic).
"""
from __future__ import annotations

import os
import re

from .pipeline_yaml import (
    resolve_stages_path,
    parse_stages,
    parse_output_list,
)
from .tech_stack import read_language


SEARCH_DIRS_REL = (
    "",
    ".claude",
    os.path.join(".claude", "design"),
    os.path.join(".claude", "design", "db"),
    os.path.join(".claude", "design", "api"),
    os.path.join("etc", "sql"),
    "src",
)


def _stage_done(cwd: str, stage: dict) -> bool:
    """Check if a stage's output artifacts exist in expected dirs."""
    output = stage.get("output", "")
    if not output:
        return False
    outputs = parse_output_list(output)
    search_dirs = [os.path.join(cwd, d) if d else cwd for d in SEARCH_DIRS_REL]

    for out_file in outputs:
        for search_dir in search_dirs:
            if os.path.exists(os.path.join(search_dir, out_file)):
                return True

    # src/ heuristic — non-empty src dir counts as code stage done
    if "src/" in output:
        src_dir = os.path.join(cwd, "src")
        if os.path.isdir(src_dir) and os.listdir(src_dir):
            return True

    return False


def _parse_skill_list(skills_raw: str) -> list[str]:
    """Convert skills field ('[backend, mybatis]' or 'backend mybatis') to ['backend.md', ...]."""
    skill_names: list[str] = []
    cleaned = skills_raw.strip("[]")
    for s in re.split(r"[,\s]+", cleaned):
        s = s.strip().strip("'\"")
        if s:
            skill_names.append(f"{s}.md")
    return skill_names


def detect_pipeline_skills(cwd: str) -> tuple[list[str], str, str]:
    """Return (skill_names, dge_role, stage_name) for the next pipeline stage."""
    if not cwd or not os.path.isdir(cwd):
        return [], "", ""

    lang = read_language(cwd)
    stages_path = resolve_stages_path(cwd, lang)
    if not stages_path:
        return [], "", ""
    # Cutover (unified-pipeline D2-3): a stack WITH an overlay uses the neutral
    # core + overlay merge (load_merged); a project's own .claude/stages.yaml
    # override still wins (honored via legacy parse); a stack without an overlay
    # yet stays on its legacy variant. Behavior is identical for java/flutter/rust
    # (proven by test_{java,flutter,rust}_golden_pin); this just routes them
    # through the single core instead of a drift-prone full-file copy.
    from pathlib import Path as _Path
    from .pipeline_overlay import has_overlay, load_merged
    is_project_override = _Path(stages_path) == _Path(cwd) / ".claude" / "stages.yaml"
    if (not is_project_override) and has_overlay(lang):
        stages = load_merged(cwd, lang)
    else:
        stages = parse_stages(stages_path)
    if not stages:
        return [], "", ""

    # Walk required (non-optional) stages, mark completed.
    last_done_idx = -1
    for i, stage in enumerate(stages):
        if stage.get("optional", "false") == "true":
            continue
        if _stage_done(cwd, stage):
            last_done_idx = i

    # Next = last_done + 1, capped at last stage.
    next_idx = last_done_idx + 1
    if next_idx >= len(stages):
        next_idx = len(stages) - 1

    next_stage = stages[next_idx]
    skills_raw = next_stage.get("skills", "")
    dge = next_stage.get("dge", "")
    stage_name = next_stage.get("name", next_stage.get("id", ""))

    return _parse_skill_list(skills_raw), dge, stage_name

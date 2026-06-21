"""pipeline_status — pipeline stage progression checker + summary renderer.

Extracted from `handlers/prompt/context_load.detect_pipeline_stage`. Operates
on stages parsed by `lib/pipeline_yaml`.

Public API:
- `compute_stage_results(stages, project_root)`:
  Returns (results, current_idx) where results is a list of
  (name, status, phase) tuples (status ∈ {"DONE","SKIP","TODO"}) and
  `current_idx` is the index of the last completed required stage (or -1).
- `render_pipeline_summary(stages, project_root)`:
  Returns the multi-line ASCII summary string used by the UserPromptSubmit
  hook, or None if `stages` is empty.

Pure function: reads `parse_output_list` from pipeline_yaml + walks the
filesystem under `project_root` to check stage output existence.
"""
from __future__ import annotations

import os
from typing import Sequence

from .pipeline_yaml import parse_output_list


def _build_search_dirs(project_root: str) -> list[str]:
    """Conventional locations where stage outputs might land."""
    return [
        project_root,
        os.path.join(project_root, ".claude"),
        os.path.join(project_root, ".claude", "design"),
        os.path.join(project_root, ".claude", "design", "db"),
        os.path.join(project_root, ".claude", "design", "api"),
        os.path.join(project_root, "etc", "sql"),
        os.path.join(project_root, "src"),
    ]


def _stage_done(output: str, search_dirs: Sequence[str], project_root: str) -> bool:
    """A stage is done when any of its declared outputs exists in any search
    directory. Special-case: 'src/ 디렉토리 구조' counts as done if src/ has files.
    """
    outputs = parse_output_list(output)
    if not outputs:
        return False
    for out_file in outputs:
        for search_dir in search_dirs:
            if os.path.exists(os.path.join(search_dir, out_file)):
                return True
    if "src/" in output:
        src_dir = os.path.join(project_root, "src")
        if os.path.isdir(src_dir) and os.listdir(src_dir):
            return True
    return False


def compute_stage_results(
    stages: Sequence[dict],
    project_root: str,
) -> tuple[list[tuple[str, str, str]], int]:
    """Compute (name, status, phase) for each stage + index of last DONE stage.

    Status:
      - "DONE": output exists.
      - "SKIP": optional stage with no output.
      - "TODO": required stage with no output.
    """
    search_dirs = _build_search_dirs(project_root)
    results: list[tuple[str, str, str]] = []
    current_idx = -1
    for i, stage in enumerate(stages):
        output = stage.get("output", "")
        optional = stage.get("optional", "false") == "true"
        found = _stage_done(output, search_dirs, project_root)

        status = "DONE" if found else ("SKIP" if optional else "TODO")
        name = stage.get("name", stage.get("id", ""))
        results.append((name, status, stage.get("phase", "")))

        if found and not optional:
            current_idx = i
    return results, current_idx


def render_pipeline_summary(
    stages: Sequence[dict],
    project_root: str,
) -> str | None:
    """Render the multi-line pipeline status summary used by context_load."""
    if not stages:
        return None
    results, current_idx = compute_stage_results(stages, project_root)
    if not results:
        return None

    lines: list[str] = []
    next_stage: str | None = None
    for i, (name, status, phase) in enumerate(results):
        icon = "v" if status == "DONE" else ("-" if status == "SKIP" else " ")
        marker = " <-- CURRENT" if i == current_idx + 1 and status == "TODO" else ""
        lines.append("[%s] %s (%s)%s" % (icon, name, phase, marker))
        if i == current_idx + 1 and status == "TODO" and next_stage is None:
            next_stage = name

    done_count = sum(1 for _, s, _ in results if s == "DONE")
    total_required = sum(1 for _, s, _ in results if s != "SKIP")

    summary = "Pipeline: %d/%d stages\n" % (done_count, total_required)
    summary += "\n".join(lines)
    if next_stage:
        summary += "\n\nNext: %s" % next_stage
    return summary

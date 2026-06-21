"""autopilot_phase1_merge — Phase 1 integration merge dispatch payload.

Per debate-1778302432-1ce6ea (4-gen converged 2026-05-09) D3:

  build_merge_dispatch_payload(*, sid, worker_branches,
                               integration_branch, base_ref) -> dict

PURE-DATA builder. Returns a Task-tool dispatch payload + response-schema
hint; does NOT invoke the Agent tool itself (lib layer cannot — only
claude-code Agent context can dispatch Task tool). Caller in
orchestrator/autopilot Phase 1 wrapper consumes the payload, spawns the
``harness-git-master`` subagent, and parses the agent's free-form final
message against ``expected_keys``.

Mirrors the established pattern at
``scripts/engine/orchestrator.py::build_research_dispatch_payload``
(L200-245) — the same lib→engine layer discipline applies (CLAUDE.md
"단방향 의존 4계층").

The merge protocol itself is locked at debate-1778161608-713bdc gen 4 F4
(``cherry_pick_sequential``) and codified in
``agents/harness-git-master.md`` ``team_merge_mode`` block: HALT on
conflict + ``merge_conflict`` advisory + explicit NO theirs/ours.
"""
from __future__ import annotations

import json
import re
from typing import Any

SUBAGENT_TYPE = "harness-git-master"

EXPECTED_KEYS: tuple[str, ...] = (
    "integration_branch",
    "head_sha",
    "merged_workers",
    "conflicted_worker",
    "conflicted_paths",
)

RESPONSE_SCHEMA_HINT: dict[str, str] = {
    "integration_branch": "str",
    "head_sha": "str",
    "merged_workers": "list[str]",
    "conflicted_worker": "str | None",
    "conflicted_paths": "list[str]",
}


def _render_prompt(
    *,
    sid: str,
    worker_branches: list[str],
    integration_branch: str,
    base_ref: str,
) -> str:
    branches_block = "\n".join(f"  - {b}" for b in worker_branches)
    return (
        "You are harness-git-master in team_merge_mode "
        f"(orchestration sid={sid}).\n\n"
        "Apply the locked F4 protocol (debate-1778161608-713bdc gen 4) "
        "from agents/harness-git-master.md team_merge_mode:\n"
        "  - cherry_pick_sequential ordering\n"
        "  - HALT on first conflict; emit merge_conflict advisory\n"
        "  - NO -X theirs / -X ours auto-resolution\n"
        "  - Worker branches remain UNTOUCHED for post-hoc inspection\n\n"
        f"base_ref: {base_ref}\n"
        f"integration_branch: {integration_branch}\n"
        "worker_branches:\n"
        f"{branches_block}\n\n"
        "Emit your final message as a single fenced ```json block matching "
        "this schema:\n"
        "  {\n"
        '    "integration_branch": "<branch ref>",\n'
        '    "head_sha": "<integration HEAD sha>",\n'
        '    "merged_workers": ["<branch>", ...],\n'
        '    "conflicted_worker": "<branch>" | null,\n'
        '    "conflicted_paths": ["<path>", ...]\n'
        "  }\n"
    )


def build_merge_dispatch_payload(
    *,
    sid: str,
    worker_branches: list[str],
    integration_branch: str,
    base_ref: str,
) -> dict[str, Any]:
    if not sid or not isinstance(sid, str):
        raise ValueError("sid must be non-empty str")
    if not worker_branches:
        raise ValueError("worker_branches must be non-empty")
    if not all(isinstance(b, str) and b for b in worker_branches):
        raise ValueError("worker_branches entries must be non-empty str")
    if not integration_branch or not isinstance(integration_branch, str):
        raise ValueError("integration_branch must be non-empty str")
    if not base_ref or not isinstance(base_ref, str):
        raise ValueError("base_ref must be non-empty str")

    prompt_text = _render_prompt(
        sid=sid,
        worker_branches=worker_branches,
        integration_branch=integration_branch,
        base_ref=base_ref,
    )
    return {
        "subagent_type": SUBAGENT_TYPE,
        "prompt_text": prompt_text,
        "response_schema_hint": dict(RESPONSE_SCHEMA_HINT),
        "expected_keys": list(EXPECTED_KEYS),
        "sid": sid,
        "worker_branches": list(worker_branches),
        "integration_branch": integration_branch,
        "base_ref": base_ref,
    }


# INVARIANT: ralph re-entry happens in parent Agent context, never in worker
# subprocess (per debate-1778307906-23b7b3 D4). On pane FAIL the autopilot
# Phase 3 invokes Skill('harness-ralph') with RALPH_CWD=<worktree_path> read
# by engine.ralph.run_validators(cwd=...); no nested ralph subprocess.


# ---------- Caller-side response parser (D3 wave (b)) ----------
#
# build_merge_dispatch_payload returns pure data; the actual Task-tool
# dispatch happens in the caller's claude-code Agent context (cannot be
# done from lib — see orchestrator.py L219 for the same lib→engine layer
# discipline). The agent's free-form final message must be parsed back
# into the typed contract — that parser lives here as pure data
# transformation (extracting + validating JSON), NOT as Task dispatch.
#
# Usage in caller:
#
#     payload = build_merge_dispatch_payload(...)
#     response_text = Agent(subagent_type=..., prompt=payload["prompt_text"])
#     try:
#         result = parse_merge_response(response_text)
#     except MergeResponseError as e:
#         # surface to operator; do NOT cherry-pick anything
#         emit_advisory(e.diagnostic)

_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*\n(?P<body>.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


class MergeResponseError(ValueError):
    """Raised when harness-git-master response cannot be parsed safely."""

    def __init__(self, diagnostic: str, *, raw: str | None = None) -> None:
        super().__init__(diagnostic)
        self.diagnostic = diagnostic
        self.raw = raw


def _extract_json_blob(text: str) -> str:
    matches = list(_FENCED_JSON_RE.finditer(text))
    if matches:
        return matches[-1].group("body").strip()
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    raise MergeResponseError(
        "no fenced ```json block and no bare JSON object found",
        raw=text,
    )


def _validate_shape(parsed: Any) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise MergeResponseError(
            f"expected JSON object at top level, got {type(parsed).__name__}",
        )
    missing = [k for k in EXPECTED_KEYS if k not in parsed]
    if missing:
        raise MergeResponseError(
            f"missing required keys: {missing}",
        )

    if not isinstance(parsed["integration_branch"], str) or not parsed["integration_branch"]:
        raise MergeResponseError("integration_branch must be non-empty str")
    if not isinstance(parsed["head_sha"], str) or not parsed["head_sha"]:
        raise MergeResponseError("head_sha must be non-empty str")

    mw = parsed["merged_workers"]
    if not isinstance(mw, list) or not all(isinstance(x, str) for x in mw):
        raise MergeResponseError("merged_workers must be list[str]")

    cw = parsed["conflicted_worker"]
    if cw is not None and not isinstance(cw, str):
        raise MergeResponseError("conflicted_worker must be str | None")

    cp = parsed["conflicted_paths"]
    if not isinstance(cp, list) or not all(isinstance(x, str) for x in cp):
        raise MergeResponseError("conflicted_paths must be list[str]")

    if cw is None and cp:
        raise MergeResponseError(
            "conflicted_paths must be empty when conflicted_worker is null",
        )
    return {k: parsed[k] for k in EXPECTED_KEYS}


def parse_merge_response(text: str) -> dict[str, Any]:
    """Extract + validate harness-git-master cherry_pick_sequential response.

    Returns a dict containing exactly the EXPECTED_KEYS, type-checked
    against RESPONSE_SCHEMA_HINT. Raises MergeResponseError on any
    extraction or validation failure — caller treats as merge_conflict
    advisory and does NOT cherry-pick.
    """
    if not isinstance(text, str) or not text.strip():
        raise MergeResponseError("response text is empty or non-str")
    blob = _extract_json_blob(text)
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError as e:
        raise MergeResponseError(f"invalid JSON: {e.msg}", raw=blob) from e
    return _validate_shape(parsed)


def is_clean_merge(parsed: dict[str, Any]) -> bool:
    """Convenience predicate for callers."""
    return parsed.get("conflicted_worker") is None

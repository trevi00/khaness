"""Prompt builders for Planner / Critic / Architect subagents.

Each builder returns a complete self-contained prompt string for the Agent
tool. Subagents do not see parent context, so every field they need must be
in the prompt.
"""
from __future__ import annotations

import json
from typing import Any


def _json_block(tag: str, obj: Any) -> str:
    return f"<{tag}>\n{json.dumps(obj, ensure_ascii=False, indent=2)}\n</{tag}>"


def planner_prompt(
    topic: str,
    context: str,
    prior_generation: dict[str, Any] | None = None,
    critic_feedback: list[dict[str, Any]] | None = None,
    files_to_read: list[str] | None = None,
) -> str:
    parts: list[str] = [
        f"<topic>\n{topic}\n</topic>",
        f"<context>\n{context}\n</context>",
    ]
    if prior_generation:
        parts.append(_json_block("prior_generation", prior_generation))
    if critic_feedback:
        parts.append(_json_block("critic_feedback", critic_feedback))
    if files_to_read:
        parts.append("<files_to_read>\n" + "\n".join(files_to_read) + "\n</files_to_read>")
    parts.append(
        "Produce your proposal now as ONE JSON object per the schema in your role file. "
        "No prose before or after."
    )
    return "\n\n".join(parts)


def critic_prompt(
    proposal: dict[str, Any],
    context: str,
    prior_critiques: list[dict[str, Any]] | None = None,
    files_to_read: list[str] | None = None,
) -> str:
    parts: list[str] = [
        _json_block("proposal", proposal),
        f"<context>\n{context}\n</context>",
    ]
    if prior_critiques:
        parts.append(_json_block("prior_critiques", prior_critiques))
    if files_to_read:
        parts.append("<files_to_read>\n" + "\n".join(files_to_read) + "\n</files_to_read>")
    parts.append("Attack now per your role file. JSON only.")
    return "\n\n".join(parts)


def architect_prompt(
    proposal: dict[str, Any],
    critique: dict[str, Any] | None,
    context: str,
) -> str:
    parts: list[str] = [_json_block("proposal", proposal)]
    if critique:
        parts.append(_json_block("critique", critique))
    else:
        parts.append(
            "<critique>\n(no critique — fast-path: gen 1 without Critic)\n</critique>"
        )
    parts.append(f"<context>\n{context}\n</context>")
    parts.append("Render verdict now per your role file. JSON only.")
    return "\n\n".join(parts)

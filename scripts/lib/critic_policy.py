"""critic_policy — asymmetric Mutation gate for Critic invoke/skip (v15.10 D4).

Per debate-1778946602-jj7vxk D4 (and CLAUDE.md L0 Mutation table row 14):

  Skip-list  : agents that are pure read or mechanical execution — Critic is
               not invoked because there is nothing for E1 to grade.
  Invoke-list: judgment-class agents — Critic is REQUIRED, silently disabling
               it would be a runtime-policy change.

Mutation tiers (asymmetric):
  - invoke → skip : silently disabling E1 on a judgment-class agent.
                    GATED behind `configure-critic-policy` token (enable-skill
                    tier, see CLAUDE.md L0 Mutation table).
  - skip → invoke : safe direction — turning Critic ON where it had been off.
                    Allowed under `apply-user-preference`.

Persistence:
  Policy lives at `~/.claude/config/critic-policy.yaml` (created lazily on
  first override). Schema:
      version: 1
      overrides:
        <agent_type>: invoke | skip

Public API:
  - resolve(agent_type) -> Decision   ("invoke" | "skip")
  - apply_override(agent_type, target_decision, *, token) -> bool
       token == "configure-critic-policy" required for invoke→skip;
       "apply-user-preference" sufficient for skip→invoke. Wrong/missing
       token raises PermissionError.
  - load_policy()  -> dict   (raw YAML-loaded; tolerant of missing file)
  - DEFAULT_SKIP / DEFAULT_INVOKE — frozensets exported for tests / docs

Note on YAML dep: writes plain `key: value` lines; reads via _safe_yaml_load
which only parses the documented subset. Avoids adding PyYAML to the harness
dependency surface.

apply_override() is the WRITE-GATE enforcement point — any caller that flips the
persisted critic flag MUST route through it to hit the token gate (invoke→skip
raises PermissionError without `configure-critic-policy`). Direct YAML edits will
be detected on next resolve() but cannot be retroactively gated (treat as
out-of-band operator action, matches mutation_safety convention).

⚠️ ENFORCEMENT SCOPE (deep-audit pass-2 — do not over-read this gate):
  resolve(agent_type) == "skip" does NOT today cause any Critic to be skipped.
  There is no automatic critic-of-agent process — handlers/pre_tool/
  critic_policy_advisor.py reads resolve() but is ADVISORY: it injects context,
  writes ORCH_CRITIC_DECISION for the post_tool ledger audit, and NEVER blocks
  the dispatch (see that file's own docstring). So the `configure-critic-policy`
  token currently gates the RECORDED/ADVISORY decision, not a live E1-disable.
  The gate is in place so that IF an orchestrator later wires resolve() to a real
  Critic-skip, the protection already exists — but the L0 "Critic disable ... 차단"
  row must be read as "gates the policy that an enforcement point WOULD consume",
  not "the harness currently enforces Critic-disable protection at spawn time".
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from .advisory_ack import AdvisoryAck, REGISTRY, _register
from .paths import CLAUDE_HOME, STATE_DIR


Decision = Literal["invoke", "skip"]


# --- Default classifications (D4 spec verbatim) ----------------------------------

DEFAULT_SKIP: frozenset[str] = frozenset({
    "Explore",
    "Researcher",
    "codebase-mapper",
    "executor",
    "code-fixer",
    "doc-writer",
    "validator-runner",
})

DEFAULT_INVOKE: frozenset[str] = frozenset({
    "harness-planner",
    "harness-architect",
    "design-reviewer",
})


# --- Token constants --------------------------------------------------------------

TOKEN_GATE_INVOKE_TO_SKIP: str = "configure-critic-policy"
TOKEN_GATE_SKIP_TO_INVOKE: str = "apply-user-preference"


# --- Policy file ------------------------------------------------------------------

POLICY_PATH: Path = CLAUDE_HOME / "config" / "critic-policy.yaml"


def _safe_yaml_load(text: str) -> dict:
    """Parse a tiny YAML subset:
        version: <int>
        overrides:
          <key>: <value>

    Tolerant of blank lines and `#` comments. Anything else is silently dropped.
    No external YAML dependency — keeps the harness self-contained.
    """
    out: dict = {"version": 1, "overrides": {}}
    in_overrides = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "overrides:":
            in_overrides = True
            continue
        if line.startswith("version:"):
            in_overrides = False
            try:
                out["version"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if in_overrides and line.startswith((" ", "\t")):
            stripped = line.strip()
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                key = k.strip()
                val = v.strip()
                if key and val in ("invoke", "skip"):
                    out["overrides"][key] = val
    return out


def _safe_yaml_dump(policy: dict) -> str:
    lines: list[str] = []
    lines.append(f"version: {int(policy.get('version', 1))}")
    lines.append("overrides:")
    overrides = policy.get("overrides", {}) or {}
    for k in sorted(overrides):
        v = overrides[k]
        if v in ("invoke", "skip"):
            lines.append(f"  {k}: {v}")
    return "\n".join(lines) + "\n"


def load_policy() -> dict:
    """Return the parsed YAML — empty/missing file → minimal default shape."""
    if not POLICY_PATH.exists():
        return {"version": 1, "overrides": {}}
    try:
        return _safe_yaml_load(POLICY_PATH.read_text(encoding="utf-8"))
    except OSError:
        return {"version": 1, "overrides": {}}


def _save_policy(policy: dict) -> None:
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(_safe_yaml_dump(policy), encoding="utf-8")


def _default_decision(agent_type: str) -> Decision:
    """Decision when no override is present — invoke-list wins over skip-list."""
    if agent_type in DEFAULT_INVOKE:
        return "invoke"
    if agent_type in DEFAULT_SKIP:
        return "skip"
    # Unknown agent — default conservative: invoke (Critic on). The
    # invoke→skip gate ensures this can only be flipped with the proper token.
    return "invoke"


def resolve(agent_type: str) -> Decision:
    """Return the effective decision for `agent_type` (override > default)."""
    policy = load_policy()
    overrides = policy.get("overrides", {}) or {}
    explicit = overrides.get(agent_type)
    if explicit in ("invoke", "skip"):
        return explicit  # type: ignore[return-value]
    return _default_decision(agent_type)


def apply_override(
    agent_type: str,
    target_decision: Decision,
    *,
    token: str | None,
) -> bool:
    """Set agent_type's decision to target_decision, gated by Mutation tier.

    Returns True on persisted change; False when the override is a no-op
    (already at target_decision).

    Raises:
      ValueError      : target_decision not in {"invoke","skip"} or empty agent_type.
      PermissionError : token does not match the required tier for this
                        direction.
    """
    if target_decision not in ("invoke", "skip"):
        raise ValueError(
            f"target_decision must be 'invoke' or 'skip', got {target_decision!r}"
        )
    if not agent_type:
        raise ValueError("agent_type must be non-empty")

    current = resolve(agent_type)
    if current == target_decision:
        return False

    # Direction-dependent gate.
    if current == "invoke" and target_decision == "skip":
        required = TOKEN_GATE_INVOKE_TO_SKIP
    else:
        # skip → invoke (or any case where current was the unknown-default)
        required = TOKEN_GATE_SKIP_TO_INVOKE

    if token != required:
        raise PermissionError(
            f"flipping {agent_type!r} from {current!r} to {target_decision!r} "
            f"requires Mutation token {required!r}, got {token!r}"
        )

    policy = load_policy()
    overrides = dict(policy.get("overrides", {}) or {})
    overrides[agent_type] = target_decision
    policy["overrides"] = overrides
    _save_policy(policy)
    return True


# --- AdvisoryAck REGISTRY entry --------------------------------------------------
# Append (not edit) — keeps existing registry callers untouched.

if "critic_policy" not in REGISTRY:
    REGISTRY["critic_policy"] = _register(
        "critic_policy",
        STATE_DIR / "critic_policy_overrides_acknowledged.txt",
        doc=(
            "key_field=agent_type, key_field_type=str, tz_awareness=n/a. "
            "Source: v15.10 D4 asymmetric Mutation gate. Producer: "
            "lib.critic_policy.apply_override (called via CLI / handler). "
            "Consumer: operator review — acks signal that a specific invoke→skip "
            "override has been audited by a human. Empty until first ack."
        ),
    )


__all__ = [
    "DEFAULT_INVOKE",
    "DEFAULT_SKIP",
    "Decision",
    "POLICY_PATH",
    "TOKEN_GATE_INVOKE_TO_SKIP",
    "TOKEN_GATE_SKIP_TO_INVOKE",
    "apply_override",
    "load_policy",
    "resolve",
]

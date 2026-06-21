#!/usr/bin/env python3
"""PostToolUse hook — platform-level Agent dispatch audit log.

Closes the directive-only enforcement gap: prior to this hook, A2 wiring
lived in commands/*.md as prose directives — every wired command relied
on the LLM following the instruction to call ``record_invocation`` after
each Agent dispatch. If a future LLM skips the directive (truncation,
prompt-rewrite, model swap), the audit trail silently goes blank.

This hook makes the audit logging **platform-enforced**: every successful
Agent tool invocation produces a record_invocation entry regardless of
whether the calling skill body invoked the directive. Markdown directives
remain (they self-document the contract for human readers and serve as
defense-in-depth), but the actual append is now a hook.

Hook contract (Claude Code PostToolUse, matcher="Agent"):
- Input JSON on stdin: ``{"tool_name": "Agent", "tool_input": {...},
  "tool_response": {...}, "session_id": "..."}``.
- Output: empty (silent — audit log is observability, not feedback).
- Fail-soft: any exception is swallowed; the hook MUST NOT block the
  parent session. Failures are surfaced via telemetry counter
  ``audit-log-hook-failed`` (D2 closure 2026-05-10) so silent regression
  is still detectable on the harness_health dashboard.

Sid resolution priority (best-effort):
1. ``ORCH_SID`` env var (autopilot super-session passes it through).
2. Explicit ``sid: <X>`` / ``sid=<X>`` label in the prompt (E7 closure
   2026-05-10). When the caller embeds a clear label, prefer it over a
   prefix grep — this lets callers disambiguate when the prompt happens
   to mention multiple sids (e.g., a debate prompt referencing a parent
   orchestrator session).
3. Sid prefix grep on the prompt:
   - ``debate-<ts>-<rand>`` / ``orch-<ts>-<rand>`` / ``ralph-<ts>-<rand>`` /
     ``interview-<ts>-<rand>`` (prefix-ts-rand format).
   - ``team-<ts>`` / ``allsolution-<ts>`` / ``ultrawork-<ts>`` (prefix-ts
     format, no rand suffix — D1 closure 2026-05-10 added these so audit
     trail does not fall back to unknown-sha for these caller paths).
4. Fallback: ``unknown-<sha8 of prompt>`` — preserves cross-session grep
   target even when the caller did not embed a sid in the prompt.

Prompt size cap (E11 closure 2026-05-10): prompts over 1 MiB are sha-
hashed (for the unknown-sha fallback) on a truncated head+tail slice
rather than the full payload — keeps hook latency bounded for very
large prompts (e.g., wholesale-document Agent dispatches).

Origin discrimination (D4 closure 2026-05-10): records emitted by this
hook carry ``extra.origin = ORIGIN_HOOK``; markdown directives in
commands/ should pass ``extra.origin = ORIGIN_DIRECTIVE`` so post-hoc
grep can split the two surfaces. ``ORIGIN_MANUAL`` is reserved for ad-
hoc operator entries. The string literals are centralized in
``lib.subagent_invocation_log`` (E8 closure) so a typo cannot silently
split the audit trail.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# Sid prefixes minted by harness skills. Two distinct formats:
#   1. `<prefix>-<unix_ts>-<rand>`: debate / orch / ralph / interview.
#   2. `<prefix>-<unix_ts>` (no rand suffix): team / allsolution / ultrawork.
# Negative lookahead on the bare-ts variants prevents collision when a
# rand suffix happens to be present (would have matched variant 1 above).
_SID_PATTERN = re.compile(
    r"\b("
    r"(?:debate|orch|ralph|interview)-[0-9]{8,11}-[A-Za-z0-9]{4,12}"
    r"|(?:team|allsolution|ultrawork)-[0-9]{8,11}(?!-[A-Za-z0-9])"
    r")\b"
)

# Explicit sid label (E7 closure 2026-05-10). Matches `sid: <value>` or
# `sid=<value>` (case-insensitive, optional whitespace). Value charset
# matches the path-traversal guard regex in subagent_invocation_log.
_SID_LABEL_PATTERN = re.compile(
    r"\bsid\s*[:=]\s*([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)

# Prompt size cap (E11). Hashing a 100MB prompt every Agent dispatch
# would balloon hook latency. Cap at 1 MiB — enough head+tail to keep
# the sha8 collision-resistant for any realistic distinct-prompt set.
_PROMPT_SIZE_CAP_BYTES = 1_048_576


def _extract_sid(prompt_text: str) -> str:
    """Best-effort sid extraction from the dispatch prompt.

    Priority order (E7 2026-05-10):
    1. ORCH_SID env var.
    2. Explicit ``sid: X`` / ``sid=X`` label in prompt.
    3. Sid prefix grep (dual-hyphen wins over single-hyphen).
    4. ``unknown-<sha8>`` fallback.
    """
    env_sid = os.environ.get("ORCH_SID")
    if env_sid:
        return env_sid
    if prompt_text:
        # E7: explicit label wins over prefix grep
        label_match = _SID_LABEL_PATTERN.search(prompt_text)
        if label_match:
            candidate = label_match.group(1)
            # Defensive: charset guard + ``..`` token reject (path-traversal
            # escape). The charset alone permits "..", "../escape", etc.
            # because "." is in [A-Za-z0-9._-]; the second clause closes
            # that hole.
            if (re.match(r"^[A-Za-z0-9._-]+$", candidate)
                    and ".." not in candidate):
                return candidate
        m = _SID_PATTERN.search(prompt_text)
        if m:
            return m.group(1)
    # E11 prompt-size cap on sha hashing path
    text = prompt_text or ""
    encoded = text.encode("utf-8", "replace")
    if len(encoded) > _PROMPT_SIZE_CAP_BYTES:
        half = _PROMPT_SIZE_CAP_BYTES // 2
        encoded = encoded[:half] + encoded[-half:]
    digest = hashlib.sha1(encoded).hexdigest()[:8]
    return f"unknown-{digest}"


def _resolve_tools(subagent_type: str) -> list[str]:
    """Look up the agent's declared tools from frontmatter; fall back to []."""
    if not subagent_type:
        return []
    try:
        from lib.agent_tool_audit import expected_tools
        return sorted(expected_tools(subagent_type))
    except Exception:
        return []


def _is_valid_sid_chars(sid: str) -> bool:
    """Reject sids that would fail subagent_invocation_log's path-traversal
    guard. The guard regex is ``^[A-Za-z0-9._-]+$`` — match the same set
    here so we don't surface ValueError on hook stdin garbage."""
    if not sid:
        return False
    return bool(re.match(r"^[A-Za-z0-9._-]+$", sid))


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    if not raw.strip():
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return

    # Only act on Agent tool invocations
    tool_name = payload.get("tool_name", "")
    if tool_name != "Agent":
        return

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return

    subagent_type = tool_input.get("subagent_type", "") or ""
    prompt_text = tool_input.get("prompt", "") or ""

    if not subagent_type:
        return  # Cannot record without an agent identity

    sid = _extract_sid(prompt_text)
    if not _is_valid_sid_chars(sid):
        return  # Defensive — should never trigger given regex above

    tools = _resolve_tools(subagent_type)

    try:
        from lib.subagent_invocation_log import (
            record_invocation, ORIGIN_HOOK,
        )
        # E11 cap also applied to the prompt_sha8 extra (consistent with
        # the unknown-sid fallback path above).
        ph_encoded = (prompt_text or "").encode("utf-8", "replace")
        if len(ph_encoded) > _PROMPT_SIZE_CAP_BYTES:
            half = _PROMPT_SIZE_CAP_BYTES // 2
            ph_encoded = ph_encoded[:half] + ph_encoded[-half:]
        record_invocation(
            sid=sid,
            agent_name=subagent_type,
            tools=tools,
            role="post-tool-hook",
            extra={
                "session_id": payload.get("session_id", ""),
                "auto_recorded": True,
                "origin": ORIGIN_HOOK,  # E8: centralized constant
                "prompt_sha8": hashlib.sha1(ph_encoded).hexdigest()[:8],
            },
        )
    except Exception as exc:
        # Fail-soft contract per harness hook discipline. The audit log
        # is observability — the parent session must not break because
        # of a failed append. But we DO surface the failure via telemetry
        # (D2 closure 2026-05-10) so a silent hook regression is still
        # detectable on the harness_health dashboard.
        try:
            from lib.logging import log_telemetry
            log_telemetry(
                "audit-log-hook-failed",
                {
                    "agent": subagent_type,
                    "sid_extracted": sid,
                    "error_type": type(exc).__name__,
                    "error_repr": repr(exc)[:200],
                },
            )
        except Exception:
            # Even telemetry failed — truly silent fallback. Hook MUST
            # NOT raise, period.
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Audit hook MUST fail-OPEN (exit 0) — _extract_sid runs before main()'s
        # inner try, so a non-string prompt crashed it to exit 1; the outer guard
        # makes the whole hook fail-soft (deep-audit pass-2 rank 3).
        sys.exit(0)

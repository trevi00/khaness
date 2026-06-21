#!/usr/bin/env python3
"""guard.py - PreToolUse hook

Guards against destructive operations across all tool types.

Output schema (validated by Zod — field names must be EXACT):
  DENY:  {"hookSpecificOutput": {"hookEventName":"PreToolUse", "permissionDecision":"deny", "permissionDecisionReason":"..."}}
  WARN:  {"hookSpecificOutput": {"hookEventName":"PreToolUse", "additionalContext":"..."}}
  MODIFY: {"hookSpecificOutput": {"hookEventName":"PreToolUse", "updatedInput":{...}}}

Bash DENY: rm -rf root, force push main, DROP DATABASE, disk destruction, fork bomb
Bash WARN: rm -rf, git reset --hard, DELETE without WHERE, git checkout --
Bash MODIFY: auto-add timeout to long-running commands

Write/Edit DENY: .env, credentials, private keys, tokens
Write/Edit WARN: config files (nginx, Dockerfile, CI/CD)
"""

import sys
import json
import os
import re
from pathlib import Path

# Fix Windows encoding
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# Ensure scripts/ on sys.path so lib.* resolves (guard.py runs as standalone hook)
_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.logging import timed, log_stderr, log_telemetry  # noqa: E402

# === Hashline glob matchers ===
# Mirrors validators/hashline.py GLOBS — files where anchor consistency matters.
HASHLINE_GLOBS = (
    re.compile(r"(^|[\\/])CLAUDE\.md$", re.IGNORECASE),
    re.compile(r"(^|[\\/])AGENTS\.md$", re.IGNORECASE),
    re.compile(r"\.claude[\\/]skills[\\/].+\.md$", re.IGNORECASE),
)


def _matches_hashline_globs(file_path: str) -> bool:
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/")
    return any(rx.search(normalized) for rx in HASHLINE_GLOBS)

# === DENY patterns: hard block ===
# Pattern collections extracted to lib/guard_patterns.py (Round 6 W2 P1).
from lib.guard_patterns import (  # noqa: E402
    DENY_PATTERNS,
    WARN_PATTERNS,
    BASH_AUTOCORRECT,
    SENSITIVE_FILE_DENY,
    SENSITIVE_FILE_WARN,
    SENSITIVE_PATH_DENY,
)


def check_sensitive_file(file_path):
    """Check if file_path is a sensitive file. Returns (deny_reason, warnings)."""
    if not file_path:
        return None, []

    basename = os.path.basename(file_path)
    normalized = file_path.replace("\\", "/")

    # DENY: harness/project runtime-policy file by FULL path (.claude/settings.json).
    # Path-scoped so .vscode/settings.json and app configs are unaffected.
    # (deep-audit pass-3: the mutation-gate's claimed accidental-Write/Edit
    # protection did not actually exist for settings.json.)
    for pattern, reason in SENSITIVE_PATH_DENY:
        if pattern.search(normalized):
            return reason, []

    # DENY: secret/credential files
    for pattern in SENSITIVE_FILE_DENY:
        if pattern.search(basename):
            return f"민감 파일 수정 차단: {basename} — 시크릿/자격증명 파일은 수동으로 수정하세요.", []

    # WARN: config files
    warnings = []
    for pattern, message in SENSITIVE_FILE_WARN:
        if pattern.search(basename) or pattern.search(normalized):
            warnings.append(message)

    return None, warnings


def emit_deny(reason):
    """Emit deny via top-level decision:'block' — works for all hook types.

    Both top-level decision:'block' and hookSpecificOutput permissionDecision:'deny'
    set the same internal fields (permissionBehavior='deny' + blockingError).
    Using top-level as primary path, hookSpecificOutput as reinforcement.
    """
    output = {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def emit_warn(warning_text):
    """Emit PreToolUse warning via additionalContext."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"<pre-tool-warning>\n"
                f"[사전 경고] 실행 전 확인:\n{warning_text}\n"
                f"</pre-tool-warning>"
            ),
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def emit_updated_input(updated_input, note):
    """Emit PreToolUse updatedInput to modify tool input before execution."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": updated_input,
            "additionalContext": (
                f"<pre-tool-autocorrect>\n"
                f"[자동 보정] {note}\n"
                f"</pre-tool-autocorrect>"
            ),
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def _looks_like_bash_payload(raw: str) -> bool:
    """Best-effort Bash-intent detection from an UNPARSEABLE hook payload (M17 fail-closed).

    When json.loads(raw) fails we cannot read tool_name the normal way, but a destructive
    Bash command must still NOT slip through as a mere warning. Two escape-resistant signals:
      1. `"tool_name":"Bash"` (tolerant of \\s whitespace).
      2. a `"command":` key — UNIQUE to the Bash tool_input schema (Read/Glob/Grep/Write/Edit
         carry file_path/pattern/content, never `command`). This survives the
         `"\\u0042ash"`-escaped-tool_name evasion the tool_name regex alone misses.

    Threat model (per design review): the hook payload is PLATFORM-generated, not adversarial
    user input — so this is fail-closed ROBUSTNESS against transport/corruption bugs, not an
    exploit boundary. The warn-on-non-Bash branch is therefore safe: a payload with neither
    signal is provably not a shell command, so warning-through cannot run a destructive command.
    Over-denying a corrupted Bash-shaped payload is acceptable (guard is stateless — sys.exit(0)
    every path — so the caller just retries with a clean payload; nothing is wedged).
    """
    if not raw:
        return False
    m = re.search(r'"tool_name"\s*:\s*"([A-Za-z_]+)"', raw)
    if m and m.group(1) == "Bash":
        return True
    return bool(re.search(r'"command"\s*:', raw))


@timed("pre_tool.guard")
def main():
    raw = ""
    tool_name = ""
    try:
        raw = sys.stdin.read()
        input_data = json.loads(raw)
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # --- Write/Edit sensitive file guard ---
        if tool_name in ("Write", "Edit", "MultiEdit"):
            file_path = tool_input.get("file_path", "")
            deny_reason, warnings = check_sensitive_file(file_path)

            if deny_reason:
                emit_deny(f"[Guard] {deny_reason}")
                sys.exit(0)

            # --- Hashline anchor advisory (glob-matched files only) ---
            # Spec: validators/hashline.py docstring. Anchor schema:
            #   `# ! <ID> <description>` or `<!-- ! <ID> <description> -->`
            # Bypassed for non-matching paths (zero-cost early return).
            if _matches_hashline_globs(file_path):
                warnings = list(warnings)
                warnings.append(
                    "hashline anchor 파일 — anchor ID 변경 시 다른 파일의 "
                    "cross-reference가 깨질 수 있습니다. 검증은 "
                    "`run_validator('hashline')` 또는 PostToolUse에서 실행됩니다."
                )

            if warnings:
                warning_text = "\n".join(f"- {w}" for w in warnings)
                emit_warn(warning_text)

            sys.exit(0)

        # --- Bash command guard ---
        if tool_name != "Bash":
            sys.exit(0)

        command = tool_input.get("command", "")
        if not command:
            sys.exit(0)

        # Check DENY patterns first (hard block).
        # `solo_override`-tagged patterns downgrade to WARN when the project
        # declares `mode: solo` in `.claude/git-flow-overrides.md` (single-
        # developer repos like personal harness mirrors). Force-push and
        # filesystem destruction remain unconditional DENY.
        from lib.git_flow_override import is_solo_mode
        # Use Claude session cwd (input_data["cwd"]) instead of subprocess cwd
        # which is fixed to user-home and never reaches the repo's .claude/.
        # Matches the pattern used by all other handlers (context_load, reviewer,
        # session/init, skill_match, mode_detector, debate_trigger).
        solo = is_solo_mode(input_data.get("cwd") or os.getcwd())
        for pattern in DENY_PATTERNS:
            if pattern["regex"].search(command):
                if solo and pattern.get("solo_override"):
                    emit_warn(
                        f"{pattern['reason']} — solo override active "
                        "(.claude/git-flow-overrides.md mode=solo)"
                    )
                    sys.exit(0)
                emit_deny(f"[Guard] {pattern['reason']}")
                sys.exit(0)

        # Check auto-correct patterns (updatedInput)
        for rule in BASH_AUTOCORRECT:
            if rule["regex"].search(command):
                fixed_command = rule["fix"](command)
                if fixed_command != command:
                    updated = dict(tool_input)
                    updated["command"] = fixed_command
                    emit_updated_input(updated, rule["note"])
                    sys.exit(0)

        # Check WARN patterns (soft warning)
        warnings = []
        for pattern in WARN_PATTERNS:
            if pattern["regex"].search(command):
                warnings.append(pattern["message"])

        if warnings:
            warning_text = "\n".join(f"- {w}" for w in warnings)
            emit_warn(warning_text)

    except Exception as exc:
        # Fail-closed (worker-2 H4 finding, fixplan-meta debate Gen4; M17 extension):
        # internal guard error must NOT silently allow destructive commands. The error may
        # be the json parse ITSELF (line `json.loads(raw)`), in which case tool_name is "" —
        # so Bash intent is recovered from the raw payload (M17, debate-reviewed), closing the
        # prior fail-OPEN where an unparseable Bash payload only WARNed. Log loudly + DENY for
        # Bash (security-sensitive); WARN for others.
        import traceback as _tb
        if not tool_name and raw:
            _m = re.search(r'"tool_name"\s*:\s*"([A-Za-z_]+)"', raw)
            tool_name = _m.group(1) if _m else ""
        bash_intent = (tool_name == "Bash") or _looks_like_bash_payload(raw)
        try:
            log_telemetry("guard-internal-error", {
                "tool": tool_name or "?",
                "bash_intent": bash_intent,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
            })
        except Exception:
            pass
        log_stderr(f"[Guard] internal error: {type(exc).__name__}: {exc}")
        log_stderr(_tb.format_exc())
        try:
            if bash_intent:
                emit_deny(
                    f"[Guard] internal error blocked execution (fail-closed): "
                    f"{type(exc).__name__}: {exc}. "
                    f"Investigate logs/telemetry; do not bypass."
                )
            else:
                emit_warn(
                    f"Guard internal error ({type(exc).__name__}); proceeding with "
                    f"warning. See stderr+telemetry."
                )
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()

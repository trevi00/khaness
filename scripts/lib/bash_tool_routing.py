"""bash_tool_routing — bash 명령어에서 dedicated tool routing 감지 (Round 6 W2 P1).

Extracted from handlers/post_tool/reviewer.py. Scans a Bash command for
suboptimal patterns (grep / find / cat / sed / echo > 등) and suggests the
dedicated Claude Code tool (Grep / Glob / Read / Edit / Write).

Returns formatted <tool-routing-feedback> message or None.

vs handlers/prompt/skill_match.PROMPT_TOOL_ROUTING_HINTS:
- 본 모듈은 EXECUTED bash 명령어 패턴 (regex on shell tokens) 매칭.
- skill_match는 USER PROMPT 의도 (Korean/English 키워드) 매칭.
"""
from __future__ import annotations

import re


# Maps bash command patterns → suggested dedicated Claude Code tool.
BASH_TOOL_ROUTING_RULES: list[dict] = [
    {
        "patterns": [r"\bgrep\b", r"\brg\b"],
        "tool": "Grep",
        "message": "`grep`/`rg` 대신 Grep 도구를 사용하면 더 나은 사용자 경험과 권한 관리가 가능합니다.",
    },
    {
        "patterns": [r"\bfind\b", r"\bls\s+-[^\s]*R"],
        "tool": "Glob",
        "message": "`find`/`ls -R` 대신 Glob 도구를 사용하면 더 빠르고 효율적인 파일 검색이 가능합니다.",
    },
    {
        "patterns": [r"\bcat\b", r"\bhead\b", r"\btail\b"],
        "tool": "Read",
        "message": "`cat`/`head`/`tail` 대신 Read 도구를 사용하면 더 나은 사용자 경험을 제공합니다.",
    },
    {
        "patterns": [r"\bsed\s+-i\b", r"\bawk\b.*\bedit"],
        "tool": "Edit",
        "message": "`sed -i`/`awk` 편집 대신 Edit 도구를 사용하면 안전한 파일 수정이 가능합니다.",
    },
    {
        "patterns": [r"\becho\b.*>(?!>)", r"cat\s*<<\s*EOF.*>"],
        "tool": "Write",
        "message": "`echo >`/`cat <<EOF >` 대신 Write 도구를 사용하면 더 안전한 파일 생성이 가능합니다.",
    },
]


_HEREDOC_BODY_RE = re.compile(
    r"<<-?\s*['\"]?(?P<tag>\w+)['\"]?[\s\S]*?(?P<close>^|\n)\s*(?P=tag)\b",
    re.MULTILINE,
)

# `-m "..."` / `-m '...'` / `--message "..."` quoted bodies (commit-message
# style arguments). The body is a string literal, not a shell command.
_MSG_ARG_DOUBLE_RE = re.compile(r"(--?m(?:essage)?)\s+\"((?:[^\"\\]|\\.)*)\"")
_MSG_ARG_SINGLE_RE = re.compile(r"(--?m(?:essage)?)\s+'((?:[^'\\]|\\.)*)'")

# `echo "..."` / `echo '...'` quoted bodies — prose printed to stdout, not a
# shell command. Body is stripped regardless of trailing redirect because the
# redirect itself (`echo "..." > file`) is preserved verbatim, so the Write
# rule (`\becho\b.*>(?!>)`) still matches the surviving `echo ... > file`
# shape after strip. Placeholder text contains NO `<` / `>` characters to
# avoid accidentally triggering the Write rule.
_ECHO_QUOTED_DOUBLE_RE = re.compile(
    r"\becho\s+\"((?:[^\"\\]|\\.)*)\""
)
_ECHO_QUOTED_SINGLE_RE = re.compile(
    r"\becho\s+'((?:[^'\\]|\\.)*)'"
)


def _strip_heredoc_bodies(command: str) -> str:
    """Replace heredoc bodies (cat <<'EOF' ... EOF) with a placeholder.

    Commit messages passed via `git commit -m "$(cat <<'EOF' ... EOF)"` often
    contain literal words like "cat" / "head" / "tail" / "grep" / "find" in
    prose that trigger BASH_TOOL_ROUTING_RULES false positives.
    The heredoc body is a string literal — its contents are NOT executed
    shell commands and must not be scanned for tool routing.

    See ~/.claude/skills/_common/repeat-error-tracker.md E8.
    """
    return _HEREDOC_BODY_RE.sub(" <<HEREDOC_BODY_STRIPPED>> ", command)


def _strip_message_arg_bodies(command: str) -> str:
    """Replace `-m "..."` / `--message '...'` quoted bodies with a placeholder.

    The body of a `-m`/`--message` argument is a string literal (commit
    message, comment, description), not a sequence of shell commands. Words
    like 'grep'/'head'/'tail'/'find' inside such prose must not trigger
    BASH_TOOL_ROUTING_RULES.

    Handles double-quote and single-quote forms, with backslash escapes.
    The introducer `-m` itself is preserved so downstream regex sees a
    well-formed shell command shape.

    See ~/.claude/skills/_common/repeat-error-tracker.md E8.
    """
    command = _MSG_ARG_DOUBLE_RE.sub(r'\1 "<MSG_BODY_STRIPPED>"', command)
    command = _MSG_ARG_SINGLE_RE.sub(r"\1 '<MSG_BODY_STRIPPED>'", command)
    return command


def _strip_echo_quoted_bodies(command: str) -> str:
    """Replace `echo "..."` / `echo '...'` quoted bodies with a placeholder.

    The body of an `echo` is prose printed to stdout, not executed shell.
    Words like 'grep'/'head'/'tail'/'find' inside echo prose must not
    trigger BASH_TOOL_ROUTING_RULES.

    Body is stripped unconditionally — redirect (`>` / `>>`) AFTER the
    closing quote is preserved verbatim, so `echo "..." > file` still
    matches the Write rule via the surviving `echo ... > file` shape.

    Placeholder contains NO `<` / `>` characters so the placeholder itself
    cannot accidentally trigger the Write rule. Backslash escapes inside
    the quoted body are honored.

    See ~/.claude/skills/_common/repeat-error-tracker.md E8 (3rd-pass).
    """
    command = _ECHO_QUOTED_DOUBLE_RE.sub('echo "_ECHO_BODY_"', command)
    command = _ECHO_QUOTED_SINGLE_RE.sub("echo '_ECHO_BODY_'", command)
    return command


def detect_tool_routing_feedback(command: str | None) -> str | None:
    """Return formatted <tool-routing-feedback> if a suboptimal bash pattern matches.

    Returns None when no pattern matches, or command is empty/None.
    The first matching rule wins (rule order = priority).

    Pre-processing (E8 false-positive guards):
    1. Heredoc bodies are stripped — `cat <<'EOF' ... EOF` literals.
    2. `cat <<TAG` introducers are stripped — paired with heredoc bodies.
    3. `-m "..."` / `--message '...'` quoted bodies are stripped —
       commit-message prose is a string literal, not a shell command.
    4. `echo "..."` / `echo '...'` quoted bodies (without redirect) are
       stripped — prose printed to stdout, not executed shell. Redirected
       echo (`echo "..." > file`) keeps matching the Write rule.
    """
    if not command:
        return None

    scanned = _strip_heredoc_bodies(command)
    # Strip the `cat <<` introducer itself — it is paired with the heredoc
    # body we just removed and not a candidate for Read tool routing.
    scanned = re.sub(r"\bcat\s+<<-?\s*['\"]?\w+['\"]?", " ", scanned)
    # Strip -m "..." / --message '...' bodies (commit-message-style args).
    scanned = _strip_message_arg_bodies(scanned)
    # Strip echo "..." / echo '...' bodies (prose, not commands).
    scanned = _strip_echo_quoted_bodies(scanned)

    for rule in BASH_TOOL_ROUTING_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, scanned):
                return (
                    "<tool-routing-feedback>\n"
                    f"[도구 라우팅 피드백] {rule['message']}\n"
                    "</tool-routing-feedback>"
                )
    return None

"""2-Strike rule: repeat-error fingerprinting and strike emission.

Extracted from `handlers/post_tool/reviewer.py` in W17 (fixplan-meta debate
Gen4 follow-through). Pure I/O on a temp JSON file + sha1 fingerprinting.

Caller contract:
  fp = extract_error_fingerprint(tool_name, tool_input, tool_output)
  if not fp: return  # no error in output
  strike = track_repeat_error(tool_name, tool_input, tool_output)
  if strike: print(strike)  # 2nd+ occurrence — emit warning

Storage: `$TEMP/.claude_repeat_errors.json`. Entries older than 24h are
auto-pruned on every track call. No database, no async, no thread safety
beyond filesystem-atomic dict replace.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Any

from .atomic_json import read_json, write_json_atomic


REPEAT_ERRORS_FILE: str = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_repeat_errors.json",
)
MAX_AGE_SEC: int = 24 * 3600
STRIKE_THRESHOLD: int = 2          # 2nd occurrence triggers the warning
ESCALATED_THRESHOLD: int = 4       # louder warning when it keeps happening

_ERROR_LINE_RE = re.compile(
    r"(?m)^.*(?:error|failed|denied|rejected|not found|permission|"
    r"unauthorized|forbidden|timeout|timed out).*$",
    re.IGNORECASE,
)
_PATH_NORM_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"']+|/[^\s\"']+|\b\d+\b")

# Cheap pre-filter — used by handlers/post_tool/reviewer.py to gate the more
# expensive fingerprint extraction. Worker-1 R2 MED dedup (W22): single source
# for "does this output contain an error indicator at all?" semantic.
_ERROR_INDICATOR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\bFAILED\b"),
    re.compile(r"\bPermission denied\b", re.IGNORECASE),
    re.compile(r"\bcommand not found\b", re.IGNORECASE),
    re.compile(r"\bNo such file or directory\b", re.IGNORECASE),
    # Trailing \b dropped (W24): `)` followed by `:` would not match because
    # both are non-word characters, so \b found no boundary. Substring match
    # is the actual intent here.
    re.compile(r"\bTraceback \(most recent call last\)"),
    re.compile(r"\bfatal:\b", re.IGNORECASE),
    re.compile(r"\bexit code [1-9]\b", re.IGNORECASE),
    re.compile(r"\breturn code [1-9]\b", re.IGNORECASE),
)


def has_error_indicator(text: str) -> bool:
    """Cheap precondition check: does the text look like a tool failure?

    Caller pattern:
        if has_error_indicator(tool_output):
            track_repeat_error(tool_name, tool_input, tool_output)

    Cheaper than calling track_repeat_error which builds a fingerprint hash
    and writes to disk. Returns False for non-strings.
    """
    if not isinstance(text, str):
        return False
    return any(p.search(text) for p in _ERROR_INDICATOR_PATTERNS)


def extract_error_fingerprint(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: str,
) -> tuple[str, str] | None:
    """Build a stable fingerprint of the error so repeats are detected across
    different file paths/line numbers but the same underlying failure.

    Returns (sha1_digest_16chars, normalized_sample) or None if no error.
    """
    if not isinstance(tool_output, str) or not tool_output.strip():
        return None
    matches = _ERROR_LINE_RE.findall(tool_output)
    if not matches:
        last = next(
            (ln for ln in reversed(tool_output.splitlines()) if ln.strip()),
            "",
        )
        if not last:
            return None
        matches = [last]

    sample = " | ".join(matches[:3])[:400].lower()
    normalized = _PATH_NORM_RE.sub("<X>", sample)
    key = f"{tool_name}::{normalized}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return digest, normalized


def _load() -> dict[str, dict[str, Any]]:
    return read_json(REPEAT_ERRORS_FILE, default={})


def _save(data: dict[str, dict[str, Any]]) -> None:
    """Atomic write via lib/atomic_json. Previous direct open("w") could leave
    a half-written file if interrupted between open() and json.dump().
    """
    write_json_atomic(REPEAT_ERRORS_FILE, data)


def track_repeat_error(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: str,
) -> str | None:
    """Update the repeat-error cache and, on a 2nd+ occurrence, return a
    formatted strike-warning string. Returns None if below threshold.
    """
    fp = extract_error_fingerprint(tool_name, tool_input, tool_output)
    if not fp:
        return None
    digest, normalized = fp

    now = time.time()
    data = _load()

    # Age-based cleanup
    for k in list(data.keys()):
        try:
            if now - float(data[k].get("last_seen", 0)) > MAX_AGE_SEC:
                del data[k]
        except Exception:
            del data[k]

    entry = data.get(digest) or {
        "count": 0,
        "first_seen": now,
        "sample": normalized[:200],
    }
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last_seen"] = now
    data[digest] = entry
    _save(data)

    count = entry["count"]
    if count < STRIKE_THRESHOLD:
        return None

    if count >= ESCALATED_THRESHOLD:
        severity = "에스컬레이션"
        extra = (
            f"  {count}회 반복. 우회로 때우지 말고 근본 원인(설정·권한·스키마 등)을 먼저 확인하고, "
            "해소되면 CLAUDE.md·스킬·settings.json 중 하나에 영구 규칙으로 코드화할 것."
        )
    else:
        severity = "2-Strike"
        extra = (
            f"  {count}회 반복. 동일한 접근을 또 시도하지 말고 (a) 원인 진단 → (b) 근본 해결 → "
            "(c) 재발 방지책을 스킬/훅/memory에 반영."
        )

    return (
        f"<repeat-error-strike>\n"
        f"[{severity} Rule] 같은 유형 에러가 반복되고 있습니다.\n"
        f"  tool={tool_name}\n"
        f"  sample={entry['sample'][:160]}\n"
        f"{extra}\n"
        f"</repeat-error-strike>"
    )

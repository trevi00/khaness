"""writeback_parser — diff-only unified format parser for harness-researcher artifacts.

Per debate-1778230575-aebdd3 D1 (locked: parser_grammar=diff_only_unified_format).

Reads `state/research/strikes/<fingerprint>.md`, locates the
`## Proposed permanent change` section, extracts a fenced ```diff block,
parses it as unified diff hunks, and validates each hunk targets a permitted
skill file under `~/.claude/skills/` (NOT `_meta/`) and modifies a
`## Gotchas` section.

Insertion-spec form (per harness-researcher.md:60-67) is REJECTED back to
researcher with `RejectReason.UNSUPPORTED_GRAMMAR` — diff-only mandate.

Public surface:
  - parse_unified_diff(hunk: str) -> list[Edit]
  - parse_proposal(md_path: str) -> ParsedProposal | RejectReason
  - RejectReason enum
  - Edit / ParsedProposal dataclasses
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import path_denylist


class RejectReason(Enum):
    UNSUPPORTED_GRAMMAR = "unsupported_grammar"   # not a unified diff
    NO_PROPOSAL_SECTION = "no_proposal_section"   # missing ## Proposed permanent change
    NO_DIFF_BLOCK = "no_diff_block"               # section present but no ```diff fence
    SELF_MODIFY_DENIED = "self_modify_denied"     # target hits path_denylist
    INVALID_TARGET = "invalid_target"             # target not under skills/ or under _meta/
    NO_GOTCHAS_ANCHOR = "no_gotchas_anchor"       # diff doesn't modify ## Gotchas
    PARSE_ERROR = "parse_error"                   # malformed hunk


@dataclass(frozen=True)
class Edit:
    """One hunk of a unified diff targeting a single file."""
    target_path: str       # canonical file path (post-denylist canonicalization)
    hunk_header: str       # original `@@ -A,B +C,D @@` line
    body_lines: tuple[str, ...]  # hunk body (' ' / '+' / '-' prefixed)


@dataclass(frozen=True)
class ParsedProposal:
    """Successfully parsed harness-researcher proposal."""
    fingerprint: str
    md_path: str
    edits: tuple[Edit, ...] = field(default_factory=tuple)


# ---- Section + fence detection ----

_PROPOSAL_HEADER_RE = re.compile(
    r"^##\s+Proposed\s+permanent\s+change\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_NEXT_HEADER_RE = re.compile(r"^##\s+\S", re.MULTILINE)
_DIFF_FENCE_RE = re.compile(
    r"```diff\n(.*?)\n```",
    re.DOTALL,
)
_HUNK_HEADER_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@")
_FILE_HEADER_RE = re.compile(r"^(?:---|\+\+\+)\s+(.+?)\s*$")


def _extract_proposal_section(md_text: str) -> str | None:
    """Return the body text of `## Proposed permanent change` section."""
    m = _PROPOSAL_HEADER_RE.search(md_text)
    if not m:
        return None
    start = m.end()
    next_m = _NEXT_HEADER_RE.search(md_text, start)
    end = next_m.start() if next_m else len(md_text)
    return md_text[start:end]


def _extract_diff_block(section_text: str) -> str | None:
    """Return the contents of the first ```diff fence in the section, or None."""
    m = _DIFF_FENCE_RE.search(section_text)
    return m.group(1) if m else None


# ---- Diff parser ----

def parse_unified_diff(diff_text: str) -> list[Edit]:
    """Parse a unified diff text into a list of Edit records.

    Recognizes:
      --- a/path
      +++ b/path
      @@ -A,B +C,D @@ optional context
       context line
      -removed line
      +added line

    Multiple file pairs separated by additional `--- / +++` are supported.
    Returns Edit per hunk; raises ValueError on malformed input.
    """
    if not isinstance(diff_text, str) or not diff_text.strip():
        raise ValueError("empty or non-string diff")

    edits: list[Edit] = []
    current_target: str | None = None
    current_hunk_header: str | None = None
    current_body: list[str] = []

    def flush_hunk() -> None:
        nonlocal current_hunk_header, current_body
        if current_hunk_header is not None and current_target is not None:
            edits.append(Edit(
                target_path=current_target,
                hunk_header=current_hunk_header,
                body_lines=tuple(current_body),
            ))
        current_hunk_header = None
        current_body = []

    for line in diff_text.splitlines():
        # File header lines: --- a/path or +++ b/path
        if line.startswith("--- ") or line.startswith("+++ "):
            flush_hunk()
            m = _FILE_HEADER_RE.match(line)
            if m and line.startswith("+++ "):
                # Take the +++ side as the canonical target (post-image)
                target = m.group(1).strip()
                # Strip git-style "b/" prefix
                if target.startswith("b/"):
                    target = target[2:]
                current_target = target
            continue

        # Hunk header
        if _HUNK_HEADER_RE.match(line):
            flush_hunk()
            current_hunk_header = line
            continue

        # Hunk body (only if inside a hunk)
        if current_hunk_header is not None:
            if line and line[0] in (" ", "+", "-", "\\"):
                current_body.append(line)
            elif not line:
                current_body.append("")  # blank context line
            else:
                # Non-conforming line inside a hunk
                raise ValueError(f"malformed hunk body line: {line!r}")

    flush_hunk()

    if not edits:
        raise ValueError("no hunks parsed from diff")

    return edits


# ---- Target validation ----

_SKILL_TARGET_RE = re.compile(
    r"^.*[/\\]\.claude[/\\]skills[/\\](?!_meta[/\\]).+\.md$",
    re.IGNORECASE,
)
_GOTCHAS_HEADER_RE = re.compile(r"^[+\-\s]##\s+Gotchas\s*$", re.MULTILINE)


def _modifies_gotchas_section(edit: Edit) -> bool:
    """True if this hunk's body lines touch a `## Gotchas` section.

    Conservative: requires the literal `## Gotchas` header to appear in the
    hunk body (as added/removed/context). The harness-researcher contract
    says permanent changes go into `## Gotchas` specifically.
    """
    body_text = "\n".join(edit.body_lines)
    return bool(_GOTCHAS_HEADER_RE.search(body_text))


def _validate_target(target: str) -> RejectReason | None:
    """Return RejectReason if target is invalid; None if OK.

    Security-first ordering: SELF_MODIFY_DENIED takes precedence over
    INVALID_TARGET. A path like `skills/_meta/foo.md` would match BOTH
    (denylisted AND outside the permitted skills/(non-meta) regex), but
    surfacing the security reason first preserves auditing clarity.
    """
    if path_denylist.is_denied(target):
        return RejectReason.SELF_MODIFY_DENIED
    if not _SKILL_TARGET_RE.match(target):
        return RejectReason.INVALID_TARGET
    return None


# ---- High-level parse ----

def parse_proposal(md_path: str | Path) -> ParsedProposal | RejectReason:
    """Parse a harness-researcher strike artifact at `md_path`.

    Returns ParsedProposal on success, RejectReason on any rejection.
    """
    p = Path(md_path)
    if not p.is_file():
        return RejectReason.NO_PROPOSAL_SECTION

    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return RejectReason.PARSE_ERROR

    section = _extract_proposal_section(text)
    if section is None:
        return RejectReason.NO_PROPOSAL_SECTION

    diff = _extract_diff_block(section)
    if diff is None:
        # Section exists but contains insertion-spec form (no diff fence) →
        # that is the unsupported grammar
        return RejectReason.UNSUPPORTED_GRAMMAR

    try:
        edits = parse_unified_diff(diff)
    except ValueError:
        return RejectReason.PARSE_ERROR

    # Validate every edit target
    for edit in edits:
        reason = _validate_target(edit.target_path)
        if reason is not None:
            return reason
        if not _modifies_gotchas_section(edit):
            return RejectReason.NO_GOTCHAS_ANCHOR

    # Fingerprint = stem of <fingerprint>.md
    fingerprint = p.stem
    return ParsedProposal(
        fingerprint=fingerprint,
        md_path=str(p),
        edits=tuple(edits),
    )

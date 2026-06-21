"""writeback_apply — operator-initiated unified-diff hunk application.

Per debate-1778236168-53dedd (4 gen, converged 2026-05-08; ontology SHA-1
84ebe62e629a889fd1a731f34ba0ddfa9caf1d91):

  D1 apply_gate          : two-step token arm-then-apply, TTL 300s default
                            (env WRITEBACK_APPLY_TOKEN_TTL bounds [60,1800])
  D2 apply_algorithm     : manual context-anchored reverse-order replay;
                            difflib.restore EXPLICITLY REJECTED (lossy on
                            context-only hunks per Python stdlib docs)
  D3 audit_schema        : applied.jsonl + preimage sidecar + separate
                            mark_applied (NOT extending mark_status Literal)
  D4 rollback_path       : same CLI --rollback, token-gated, drift-check
                            current sha == post_image_sha
  D5 atomicity_model     : all-targets in-memory staged → sequential
                            os.replace; quarantine on partial-recover fail
  D6 invocation_contract : operator_initiated_only — auto-apply OUT OF
                            SCOPE per debate-1778230575-aebdd3.

This module is the core of the apply pipeline (D2 + D6). Storage helpers
(D3/D4 audit + sidecar) and CLI gate (D1) live in writeback_store + the
cli.writeback_inspect command.

Public surface:
  - APPLY_MODE                  module-level lock string
  - InvalidOperatorContext      raised when D6 contract violated
  - ApplyError                  raised on hunk-apply failure (HUNK_MISMATCH)
  - validate_operator_context() D6 enforcement
  - apply_hunk_to_text()        D2 single-hunk replay
  - apply_edits_to_text()       D2 multi-hunk reverse-order replay
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence


# ---- D6 contract lock ----

APPLY_MODE: str = "operator_initiated_only"
"""Module-level lock asserting auto-apply is OUT OF SCOPE.

Per debate-1778230575-aebdd3 (writeback infra observe-only) AND
debate-1778236168-53dedd D6: only an explicit operator-initiated
invocation through cli.writeback_inspect --apply may use this module.
Any agent/scheduler/CI caller MUST NOT bypass validate_operator_context.
"""


class InvalidOperatorContext(Exception):
    """Raised when D6 contract is violated.

    operator_context dict MUST carry non-null pid (int>0), sid (non-empty
    str), cwd (existing absolute path str). Auto-synthesized sentinels
    (pid==0, sid in (None, ''), cwd in (None, '')) → reject.
    """


class ApplyError(Exception):
    """Raised when hunk apply fails. `kind` discriminates the failure."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


# ---- D6 contract enforcement ----

def validate_operator_context(operator_context: dict) -> None:
    """Enforce D6 invocation_contract: operator_initiated_only.

    Caller must provide a dict with non-null pid (int > 0), sid
    (non-empty str), cwd (existing absolute path str). Any synthesized
    sentinel (pid==0, sid None/empty, cwd None/empty/non-absolute/missing)
    raises InvalidOperatorContext. Refuses None operator_context outright.
    """
    if not isinstance(operator_context, dict):
        raise InvalidOperatorContext(
            f"operator_context must be dict, got {type(operator_context).__name__}"
        )

    pid = operator_context.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        raise InvalidOperatorContext(
            f"pid must be positive int (real OS pid), got {pid!r}"
        )

    sid = operator_context.get("sid")
    if not isinstance(sid, str) or not sid:
        raise InvalidOperatorContext(
            f"sid must be non-empty str (operator session id), got {sid!r}"
        )

    cwd = operator_context.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise InvalidOperatorContext(
            f"cwd must be non-empty str, got {cwd!r}"
        )
    if not os.path.isabs(cwd):
        raise InvalidOperatorContext(
            f"cwd must be absolute path, got {cwd!r}"
        )
    if not os.path.isdir(cwd):
        raise InvalidOperatorContext(
            f"cwd does not exist or is not a directory: {cwd!r}"
        )


# ---- D2 manual context-anchored hunk apply ----

@dataclass(frozen=True)
class HunkAnchor:
    """Parsed hunk header — old-side line range (1-indexed)."""
    old_start: int   # line A in @@ -A,B +C,D @@
    old_count: int   # line B (default 1 if omitted in header)
    new_start: int   # line C
    new_count: int   # line D


def _parse_hunk_header(header: str) -> HunkAnchor:
    """Parse `@@ -A,B +C,D @@ ...` into HunkAnchor.

    B and D default to 1 when omitted. Raises ValueError on malformed input.
    """
    if not isinstance(header, str) or not header.startswith("@@"):
        raise ValueError(f"not a hunk header: {header!r}")
    # Strip leading/trailing @@
    rest = header.split("@@", 2)[1].strip()
    parts = rest.split()
    if len(parts) < 2:
        raise ValueError(f"malformed hunk header: {header!r}")
    minus, plus = parts[0], parts[1]
    if not minus.startswith("-") or not plus.startswith("+"):
        raise ValueError(f"malformed hunk header signs: {header!r}")
    minus = minus[1:]
    plus = plus[1:]

    def _split(span: str) -> tuple[int, int]:
        if "," in span:
            a, b = span.split(",", 1)
            return int(a), int(b)
        return int(span), 1

    a, b = _split(minus)
    c, d = _split(plus)
    return HunkAnchor(old_start=a, old_count=b, new_start=c, new_count=d)


def apply_hunk_to_text(target_text: str, hunk_header: str,
                        body_lines: Sequence[str]) -> str:
    """Replay one unified-diff hunk against `target_text`.

    Algorithm (D2 manual context-anchored):
      1. Parse header → HunkAnchor (old_start A, old_count B).
      2. Take target slice [A, A+B) (1-indexed → 0-indexed slice).
      3. Compare slice against body's old-side reconstruction (' ' + '-'
         lines). If any line mismatches → ApplyError(HUNK_MISMATCH).
      4. Build new slice from body's new-side (' ' + '+' lines, drop '-' and
         the '\\ No newline at end of file' marker).
      5. Splice new slice back, return mutated text.

    The function is pure: no I/O, no global state. Multi-hunk callers must
    apply hunks in REVERSE old_start order so prior offsets do not shift
    later anchors (responsibility of apply_edits_to_text).

    difflib.restore is explicitly rejected because it cannot disambiguate
    context-only hunks (no '+' or '-' lines) — it would return one of the
    two original sequences arbitrarily. Manual replay handles that branch.
    """
    if not isinstance(target_text, str):
        raise ValueError(f"target_text must be str, got {type(target_text).__name__}")
    anchor = _parse_hunk_header(hunk_header)

    # Build old/new reconstructions from body
    old_recon: list[str] = []
    new_recon: list[str] = []
    for line in body_lines:
        if not line:
            # treat empty line as a context blank line (no prefix)
            old_recon.append("")
            new_recon.append("")
            continue
        prefix = line[0]
        rest = line[1:]
        if prefix == " ":
            old_recon.append(rest)
            new_recon.append(rest)
        elif prefix == "-":
            old_recon.append(rest)
        elif prefix == "+":
            new_recon.append(rest)
        elif prefix == "\\":
            # '\ No newline at end of file' — informational marker; ignore
            continue
        else:
            raise ValueError(
                f"hunk body line has invalid prefix {prefix!r}: {line!r}"
            )

    # Verify body's old-side count matches header's old_count
    if len(old_recon) != anchor.old_count:
        raise ApplyError(
            "HUNK_MISMATCH",
            f"header old_count={anchor.old_count} but body reconstructs "
            f"{len(old_recon)} old-side lines",
        )

    # Slice the target. Lines are 1-indexed in unified diff; Python is 0-indexed.
    # An empty old_count (0) means pure-insertion at line A (insert before A).
    target_lines = target_text.split("\n")
    # Note: split keeps trailing element after final '\n' as ''. We preserve that.

    # 1-indexed [old_start, old_start+old_count) → 0-indexed [A-1, A-1+B)
    if anchor.old_count == 0:
        # Pure insertion before line old_start (1-indexed)
        idx = anchor.old_start - 1
        if idx < 0 or idx > len(target_lines):
            raise ApplyError(
                "HUNK_MISMATCH",
                f"insertion anchor old_start={anchor.old_start} out of "
                f"target line range [1, {len(target_lines)+1}]",
            )
        new_lines = target_lines[:idx] + new_recon + target_lines[idx:]
        return "\n".join(new_lines)

    start = anchor.old_start - 1
    end = start + anchor.old_count
    if start < 0 or end > len(target_lines):
        raise ApplyError(
            "HUNK_MISMATCH",
            f"slice [{anchor.old_start}, {anchor.old_start + anchor.old_count}) "
            f"out of target line range [1, {len(target_lines)+1}]",
        )

    actual_slice = target_lines[start:end]
    if actual_slice != old_recon:
        # Find the first mismatch line for diagnostic detail
        for i, (a, b) in enumerate(zip(actual_slice, old_recon)):
            if a != b:
                raise ApplyError(
                    "HUNK_MISMATCH",
                    f"target line {anchor.old_start + i}: expected {b!r}, "
                    f"found {a!r}",
                )
        raise ApplyError(
            "HUNK_MISMATCH",
            "target slice length differs from body old reconstruction",
        )

    new_lines = target_lines[:start] + new_recon + target_lines[end:]
    return "\n".join(new_lines)


def apply_edits_to_text(target_text: str,
                        edits: Sequence[tuple[str, Sequence[str]]]) -> str:
    """Replay multiple hunks against `target_text` in REVERSE old_start order.

    `edits` is a sequence of (hunk_header, body_lines) tuples. They are
    sorted by old_start descending so each apply does not shift the next
    apply's anchor. Stops on first ApplyError without partial mutation
    (operates on a local copy throughout).

    All-or-nothing: if any hunk fails, the original text is effectively
    untouched (this function returns ApplyError rather than partial state).
    """
    if not edits:
        return target_text

    # Sort hunks by old_start descending so later edits don't shift earlier
    indexed: list[tuple[int, str, Sequence[str]]] = []
    for header, body in edits:
        anchor = _parse_hunk_header(header)
        indexed.append((anchor.old_start, header, body))
    indexed.sort(key=lambda t: t[0], reverse=True)

    result = target_text
    for _, header, body in indexed:
        result = apply_hunk_to_text(result, header, body)
    return result

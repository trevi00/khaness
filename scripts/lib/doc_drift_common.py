#!/usr/bin/env python3
"""Shared helpers for the doc-drift advisory validators.

Extracted from validators/doc_code_drift.py so doc_code_drift AND its sibling
validators/self_model_drift.py share ONE copy of the hermetic source reader,
the backtick repo-path-token regex, and the markdown section-body slicer —
preventing the doc↔code drift these validators themselves detect from creeping
into a duplicated helper (harness-advancement #4, debate-1780540387-7a5009
converged gen-3 sha1 d5aa3c5b9d53d42521cf5eaa97ce72b8ca5ff4b4, decision D0).

SAFETY: pure functions + an injectable `_module_reader` hook for hermetic tests.
Tests MUST patch THIS module's `_module_reader` (doc_drift_common._module_reader);
`_read_source` reads it at call time, so both validators share the one hook.
NEVER imports/execs scanned modules.
"""
from __future__ import annotations

import re
from pathlib import Path

# Injection hook for hermetic tests (mirrors skill_source_liveness._url_opener).
# callable(Path) -> str | None. None => use the on-disk reader below.
_module_reader = None


def _read_source(path: Path) -> str | None:
    if _module_reader is not None:
        return _module_reader(path)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# Path tokens inside backticks that point at a repo module/file.
_PATH_TOKEN_RE = re.compile(
    r"`(?:~/\.claude/)?(?:scripts/)?"
    r"((?:lib|validators|handlers|engine|cli|cron|tests)/[A-Za-z0-9_./-]+\.py)`"
)


def _section_body(text: str, heading_substr: str) -> str:
    """Return the body under the first `## <heading>` whose title contains
    heading_substr (case-insensitive), up to the next `## ` heading. '' if absent."""
    hs = heading_substr.lower()
    lines = text.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if line.startswith("## "):
            if capturing:
                break
            capturing = hs in line[3:].lower()
            continue
        if capturing:
            out.append(line)
    return "\n".join(out)

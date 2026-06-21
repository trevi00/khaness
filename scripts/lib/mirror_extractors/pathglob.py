#!/usr/bin/env python3
"""mirror_extractors.pathglob — toolchain-free fallback extractor (M5 'plus' arm).

No language toolchain, no comment syntax: comment_syntax() returns (None, None) so
the hot-path normalize does whitespace-only normalization (no comment stripping).
Per BIND-4, scopes produced here are declared mode='coarse' with a coarse_reason —
they hash raw content and accept comment/formatting noise EXPLICITLY rather than
lying about a semantic extract they cannot do. This keeps the mirror functional on
any stack (Java/TS/Flutter/...) at honestly-declared degraded fidelity, so M5's
pluggable arm holds and we never fall back to 'Rust-scoped only'.
"""
from __future__ import annotations

from pathlib import Path

from .base import git_tracked_files

# common source extensions for a stack-agnostic seed
_SOURCE_EXTS = (".rs", ".py", ".java", ".kt", ".ts", ".tsx", ".js", ".jsx", ".go", ".dart", ".rb", ".cs")


class PathGlobExtractor:
    name = "pathglob"
    is_fallback = True  # always the last-resort match in pluggable detection

    def detect(self, cwd: str) -> bool:
        return True  # fallback: matches any project

    def comment_syntax(self) -> tuple[str | None, str | None]:
        return (None, None)  # no toolchain => no comment strip => scopes are coarse

    def default_scopes(self, cwd: str) -> list[dict]:
        reason = "toolchain-free pathglob fallback: no language extractor; raw content hashed, comment/format noise accepted"
        return [
            {"name": "services", "globs": ["**/services/**", "**/*service*"], "mode": "coarse", "coarse_reason": reason},
            {"name": "source", "globs": [f"**/*{e}" for e in _SOURCE_EXTS], "mode": "coarse", "coarse_reason": reason},
        ]

    def extract_structure(self, cwd: str) -> dict:
        """File-path listing only (no parse). REGENERATE-ONLY."""
        tracked = git_tracked_files(cwd) or []
        dirs: dict[str, int] = {}
        for f in tracked:
            top = f.split("/", 1)[0] if "/" in f else "."
            dirs[top] = dirs.get(top, 0) + 1
        return {
            "stack": "pathglob",
            "file_count": len(tracked),
            "top_level": sorted(({"dir": d, "files": n} for d, n in dirs.items()), key=lambda x: x["dir"]),
        }


EXTRACTOR = PathGlobExtractor()

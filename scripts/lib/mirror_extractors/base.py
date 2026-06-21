#!/usr/bin/env python3
"""mirror_extractors.base — per-project mirror context brain, deterministic core.

Locked by debate-1781435805-qb14p7 (converged gen-2, ontology SHA-1 c4ad11f4d9a2).
This module is the MACHINE half (M8): it computes the drift FINGERPRINT that the
SessionStart hot path compares — pure, git-only/file-read-only, NO toolchain (M4).
Heavy extraction (cargo/AST signatures, prose) lives in the per-stack extractor's
`extract_structure` + the on-demand regenerate command, never here.

BIND-1 (M3 non-lying, bias-to-STALE): the hot-path normalize strips ONLY full-line
comments (a line that, trimmed, starts with the stack's line-comment token). It
NEVER strips mid-line or block comments and NEVER touches string-literal content —
so two distinct code states can never collapse to one hash (a regex with no lexer
that stripped a `//` inside a string literal would produce a FALSE-CLEAN, the exact
STALE-lying-clean M3 forbids). Block/in-string-correct stripping is deferred to the
lexer-equipped regenerate extractor. Full-line stripping removes strictly fewer
chars than token-aware stripping, so distinct real code cannot collide.

BIND-2 (M4 fail-soft git): `git ls-files` is pre-checked for a .git dir and wrapped
in try/except (OSError, SubprocessError); any git absence/error returns None, which
callers treat as 'unverifiable -> inert' (never an exception across the hot path).

BIND-4 (M3/M5 coarse honesty): a scope whose extractor has no line-comment syntax
(the toolchain-free pathglob fallback) MUST be declared mode='coarse' with a
coarse_reason; coarse scopes are hashed RAW (noise accepted, declared).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Protocol

MANIFEST_RELPATH = ("atlas", "mirror", "manifest.json")
SCHEMA_VERSION = 1
_GIT_TIMEOUT = 15


class ExtractorBase(Protocol):  # coherence-ok: OCP extractor contract Protocol — satisfied by duck-typing (mirror_extractors/_REGISTRY), authoritative interface doc, no direct runtime ref by design
    """Per-stack extractor contract (OCP — registered in __init__._REGISTRY)."""

    name: str
    is_fallback: bool  # True only for the last-resort extractor (pathglob)

    def detect(self, cwd: str) -> bool:
        """True iff this extractor's stack is the project's stack (used by
        detect_extractor for OCP-clean stack selection)."""
        ...

    def comment_syntax(self) -> tuple[str | None, str | None]:
        """(line_comment_token, block_comment_regex). line token is used by the
        hot-path full-line normalize; block regex is used ONLY by regenerate.
        A None line token => this stack has no cheap normalize => its scopes are
        coarse (BIND-4)."""
        ...

    def default_scopes(self, cwd: str) -> list[dict]:
        """Seed manifest scopes[] at first regenerate (each: name, globs, mode)."""
        ...

    def extract_structure(self, cwd: str) -> dict:
        """REGENERATE-ONLY rich extract (module tree + signatures + dep edges).
        MAY shell a toolchain (cargo/AST). Never called on the hot path."""
        ...


# ── normalize (BIND-1: full-line comment strip only, whitespace-insensitive) ──

def normalize(text: str, line_comment: str | None) -> str:
    """Hot-path normalized extract. Drops full-line comments + blank lines and
    collapses whitespace runs so formatting/indent/comment-only edits do not flip
    the hash, WITHOUT a lexer. Mid-line comment tokens are left intact (a trailing
    `code(); // note` edit flips STALE — the safe-noisy direction; never false-clean)."""
    out: list[str] = []
    for raw in text.splitlines():
        trimmed = raw.strip()
        if not trimmed:
            continue  # blank line
        if line_comment and trimmed.startswith(line_comment):
            continue  # FULL-LINE comment only (never mid-line / never in-string)
        out.append(re.sub(r"\s+", " ", raw).strip())  # whitespace-insensitive
    return "\n".join(out)


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


# ── git-guarded file listing (BIND-2) ────────────────────────────────────────

def git_tracked_files(cwd: str) -> list[str] | None:
    """All git-tracked file paths (POSIX-relative), or None if not a git repo /
    git absent / git errored (fail-soft per BIND-2). Caller treats None as
    'unverifiable -> inert', never raising on the hot path."""
    root = Path(cwd)
    if not (root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def working_tree_clean(cwd: str) -> bool | None:
    """True iff no TRACKED file differs from HEAD (untracked files are IGNORED —
    they are never in a scope, which hashes only git-tracked files). None when git
    is unavailable. Enables the scan() fast-path: same HEAD + clean tracked tree =>
    the fingerprint is provably unchanged from the manifest (BIND-2 fail-soft)."""
    root = Path(cwd)
    if not (root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() == ""


# ── glob matching (** aware, POSIX paths) ────────────────────────────────────

def _glob_to_re(glob: str) -> re.Pattern:
    """Translate a path glob to a regex. `**` matches across '/'; `*` does not;
    `?` is one non-slash char."""
    i, n, out = 0, len(glob), []
    while i < n:
        c = glob[i]
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            if i < n and glob[i] == "/":
                i += 1  # `**/` also matches zero dirs
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def files_in_scope(all_files: list[str], globs: list[str]) -> list[str]:
    pats = [_glob_to_re(g) for g in globs]
    return sorted({f for f in all_files if any(p.match(f) for p in pats)})


# ── scope + fingerprint hashing ──────────────────────────────────────────────

def compute_scope_hash(cwd: str, scope: dict, all_files: list[str], line_comment: str | None) -> str:
    """sha1 over the scope's in-scope files. mode='normalized' => normalize()
    each file (BIND-1); mode='coarse' => raw bytes (BIND-4, noise declared)."""
    coarse = scope.get("mode") == "coarse"
    parts: list[str] = []
    for rel in files_in_scope(all_files, scope.get("globs", [])):
        try:
            text = (Path(cwd) / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parts.append(text if coarse else normalize(text, line_comment))
    blob = "\n\x00\n".join(parts).encode("utf-8", "replace")
    return _sha1(blob)


def compute_fingerprint(cwd: str, scopes: list[dict], line_comment: str | None):
    """Return (fingerprint, {scope_name: hash}) or (None, {}) when unverifiable
    (git absent — BIND-2). Scope order-independent (sorted by name)."""
    all_files = git_tracked_files(cwd)
    if all_files is None:
        return None, {}
    per_scope: dict[str, str] = {}
    for sc in sorted(scopes, key=lambda s: s.get("name", "")):
        per_scope[sc["name"]] = compute_scope_hash(cwd, sc, all_files, line_comment)
    fp = _sha1("\n".join(f"{n}:{per_scope[n]}" for n in sorted(per_scope)).encode())
    return fp, per_scope

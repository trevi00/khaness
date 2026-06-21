"""mirror_extractors — per-stack mirror extractor Registry (OCP).

Locked by debate-1781435805-qb14p7 (ontology c4ad11f4d9a2, M5 generality contract).

Extension policy (Open-Closed, mirrors lib/providers):
  Add a new stack:
    1. Create lib/mirror_extractors/<name>.py exposing `EXTRACTOR = YourClass()`
    2. Add an entry to `_REGISTRY` below (key = stack/alias -> module name)
  No changes anywhere else.

Consumers use `get_extractor(name)`; the hot-path drift core (base.py) never
imports concrete extractors. Rust/cargo is the first impl; `pathglob` is the
toolchain-free fallback so non-Rust mirrored projects still function (M5).
"""
from __future__ import annotations

from importlib import import_module

from .base import (  # re-export the deterministic core
    MANIFEST_RELPATH,
    SCHEMA_VERSION,
    compute_fingerprint,
    compute_scope_hash,
    files_in_scope,
    git_tracked_files,
    normalize,
    working_tree_clean,
)

# stack name or alias -> module name (under this package)
_REGISTRY: dict[str, str] = {
    "rust": "rust",
    "cargo": "rust",
    "pathglob": "pathglob",
    # Future: "java": "java", "typescript": "typescript", "flutter": "flutter"
}


def list_extractors() -> list[str]:
    return sorted(set(_REGISTRY.values()))


def list_aliases() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_extractor(name: str):
    """Return the extractor instance for a stack name/alias. Raises KeyError on
    unknown (same contract as lib.providers.get_provider)."""
    key = (name or "").strip().lower()
    if key not in _REGISTRY:
        raise KeyError(f"unknown mirror extractor {name!r}; known: {list_aliases()}")
    mod = import_module(f"{__name__}.{_REGISTRY[key]}")
    return mod.EXTRACTOR


def detect_extractor(cwd: str) -> str:
    """Pick the extractor for a project cwd by asking each registered extractor's
    detect() — OCP-clean: a new stack adds `<name>.py` (with detect()/is_fallback)
    + one _REGISTRY line, and is auto-considered here with NO edit to this function.
    Non-fallback extractors are tried first (deterministic by module name); the
    `is_fallback` extractor (pathglob) wins only when nothing else matches."""
    fallback = "pathglob"
    for modname in sorted(set(_REGISTRY.values())):
        try:
            ext = import_module(f"{__name__}.{modname}").EXTRACTOR
        except Exception:
            continue
        if getattr(ext, "is_fallback", False):
            fallback = ext.name
            continue
        try:
            if ext.detect(cwd):
                return ext.name
        except Exception:
            continue
    return fallback

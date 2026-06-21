#!/usr/bin/env python3
"""mirror_extractors.rust — Rust/Cargo extractor (M5 first impl).

comment_syntax() supplies the line-comment token the hot-path normalize uses
(BIND-1). extract_structure() is REGENERATE-ONLY and MAY shell `cargo metadata`
(M4: never on the SessionStart hot path). cargo is fail-soft: if absent, structure
degrades to a git-tree listing rather than raising.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .base import git_tracked_files

_CARGO_TIMEOUT = 60


class RustExtractor:
    name = "rust"
    is_fallback = False  # pluggable detection (OCP): matched by detect(), not hardcoded

    def detect(self, cwd: str) -> bool:
        """True iff this is a Cargo project — Cargo.toml at cwd or an immediate
        subdir (covers a git-root whose workspace lives at <project>/rust/)."""
        root = Path(cwd)
        if (root / "Cargo.toml").is_file():
            return True
        try:
            return any((p / "Cargo.toml").is_file() for p in root.iterdir() if p.is_dir())
        except OSError:
            return False

    def comment_syntax(self) -> tuple[str | None, str | None]:
        # line token used by hot-path normalize; block regex used only at regenerate.
        return ("//", r"/\*.*?\*/")

    def default_scopes(self, cwd: str) -> list[dict]:
        """Seed scopes for a Rust workspace: a normalized 'services' scope if any
        service-layer paths exist, the source tree, and a coarse crate-graph scope
        (Cargo.toml manifests change rarely; reformat noise accepted, declared)."""
        scopes: list[dict] = [
            {"name": "src", "globs": ["**/src/**/*.rs"], "mode": "normalized"},
            {"name": "services", "globs": ["**/services/**/*.rs", "**/*service*.rs"], "mode": "normalized"},
            {"name": "crate-graph", "globs": ["Cargo.toml", "**/Cargo.toml"], "mode": "coarse",
             "coarse_reason": "Cargo manifests tracked as raw content; formatting noise accepted"},
        ]
        return scopes

    def _workspace_dir(self, cwd: str) -> Path:
        """Locate the Cargo workspace dir: cwd if it holds Cargo.toml, else the
        first immediate subdir that does (e.g. a repo whose git-root is <project>
        but whose Cargo workspace lives at <project>/rust/). Falls back to cwd."""
        root = Path(cwd)
        if (root / "Cargo.toml").is_file():
            return root
        try:
            for sub in sorted(p for p in root.iterdir() if p.is_dir()):
                if (sub / "Cargo.toml").is_file():
                    return sub
        except OSError:
            pass
        return root

    def extract_structure(self, cwd: str) -> dict:
        """Module tree + dependency edges via `cargo metadata` (fail-soft to a
        git-tree listing). REGENERATE-ONLY. Runs cargo from the workspace dir,
        which may be a subdir of the git-root project (e.g. <project>/rust/)."""
        ws = self._workspace_dir(cwd)
        crates: list[dict] = []
        try:
            proc = subprocess.run(
                ["cargo", "metadata", "--format-version", "1", "--no-deps"],
                cwd=str(ws), capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_CARGO_TIMEOUT,
            )
            if proc.returncode == 0:
                meta = json.loads(proc.stdout)
                for pkg in meta.get("packages", []):
                    crates.append({
                        "name": pkg.get("name"),
                        "manifest_path": pkg.get("manifest_path"),
                        "dependencies": sorted(d.get("name") for d in pkg.get("dependencies", []) if d.get("name")),
                        "targets": sorted({t.get("kind", ["?"])[0] for t in pkg.get("targets", [])}),
                    })
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            crates = []
        if not crates:
            # toolchain-free degrade: list Cargo.toml dirs as crate stand-ins
            tracked = git_tracked_files(cwd) or []
            for f in sorted(tracked):
                if f.endswith("Cargo.toml"):
                    crates.append({"name": str(Path(f).parent) or ".", "manifest_path": f,
                                   "dependencies": [], "targets": [], "degraded": True})
        return {"stack": "rust", "crate_count": len(crates), "crates": crates}


EXTRACTOR = RustExtractor()
